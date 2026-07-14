"""synonym builder — LLM-driven ES Solr synonym generation.

Reads ``item_profile.jsonl`` (Stage 1/2 output), extracts unique values across
all dimensions (brand, category, cuisine, taste, occasion) plus cleaned store
names, sends each term individually to the LLM for synonym expansion, merges
overlapping groups, and writes ``synonyms_solr.txt`` in ES Solr multi-way
format.

Usage::

    from synonym_builder import build_synonyms

    build_synonyms(
        profile_path="output/stage1/item_profile.jsonl",
        dim_dict_path="output/stage1/dim_dictionary_snapshot.yaml",
        output_dir="output/synonyms",
        llm_client=llm,
        prompt_template_path="configs/prompts/synonym_generation.txt",
    )
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_dim_dict(path: Path) -> dict[str, Any]:
    """Load dim_dictionary_snapshot.yaml; return {} if absent."""
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# ---------------------------------------------------------------------------
# LLM synonym generation
# ---------------------------------------------------------------------------


def _build_term_prompt(template: str, value: str) -> str:
    """Build a prompt — just drop the raw term into the template."""
    return template.replace("{input_term}", value)


def _parse_synonym_response(payload: Any) -> list[str]:
    """Extract synonym list from LLM response.

    Handles:
      - ``{"synonyms": [...]}`` (preferred)
      - ``["...", ...]`` (plain array — new prompt may produce this)
      - Legacy dict with dimension-specific keys.
    """
    if isinstance(payload, list):
        return [str(x).strip() for x in payload if x and str(x).strip()]

    if isinstance(payload, dict):
        # Preferred format
        raw = payload.get("synonyms")
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if x and str(x).strip()]
        # Legacy multi-key format
        all_syns: list[str] = []
        for key in ("brand_synonyms", "category_synonyms",
                     "taste_synonyms", "occasion_synonyms"):
            raw = payload.get(key)
            if isinstance(raw, list):
                all_syns.extend(str(x).strip() for x in raw if x and str(x).strip())
        return all_syns

    return []


def _generate_synonyms_for_dim(
    terms: set[str],
    dim_name: str,
    template: str,
    llm_client: Any,
    logger: Any,
) -> list[list[str]]:
    """Send each term to LLM, collect synonym groups."""
    groups: list[list[str]] = []
    total = len(terms)
    success = 0
    failed = 0

    for i, term in enumerate(sorted(terms), 1):
        prompt = _build_term_prompt(template, term)
        logger.info("synonym_llm", extra={
            "stage": "synonym", "dim": dim_name,
            "term": term, "progress": f"{i}/{total}",
        })
        try:
            resp = llm_client.complete(prompt, temperature=0.3, item_id=f"{dim_name}:{term}")
            synonyms = _parse_synonym_response(resp)

            group = {term}
            group.update(s for s in synonyms if s and s != term)
            groups.append(sorted(group) if len(group) >= 2 else [term])
            success += 1
        except Exception as e:
            logger.warning("synonym_llm_failed", extra={
                "stage": "synonym", "dim": dim_name, "term": term, "error": str(e),
            })
            groups.append([term])
            failed += 1

    logger.info("synonym_done", extra={
        "stage": "synonym", "dim": dim_name,
        "total": total, "success": success, "failed": failed,
    })
    return groups


# ---------------------------------------------------------------------------
# Merge / deduplicate
# ---------------------------------------------------------------------------


def _merge_overlapping_groups(groups: list[list[str]]) -> list[list[str]]:
    """Iteratively merge groups that share ≥ 1 token, drop singletons."""
    merged: list[set[str]] = []
    for g in groups:
        gset = set(g)
        if len(gset) <= 1:
            continue
        overlapped = [i for i, m in enumerate(merged) if m & gset]
        if overlapped:
            merged[overlapped[0]] |= gset
            for i in reversed(overlapped[1:]):
                merged[overlapped[0]] |= merged[i]
                del merged[i]
        else:
            merged.append(gset)

    seen: set[tuple[str, ...]] = set()
    result: list[list[str]] = []
    for m in merged:
        key = tuple(sorted(m))
        if key not in seen and len(key) >= 2:
            seen.add(key)
            result.append(sorted(m))
    return result


# ---------------------------------------------------------------------------
# Output writer
# ---------------------------------------------------------------------------


def _write_solr_synonyms(groups: list[list[str]], out_dir: Path) -> int:
    """Write two files:

    - ``ext_dict.txt`` — 分词词表（一行一词，IK ext_dict）
    - ``ext_synonyms.txt`` — 同义词词表（逗号分隔分组，ES synonym_graph）
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    all_tokens: set[str] = set()

    # Synonym groups (comma-separated)
    with (out_dir / "ext_synonyms.txt").open("w", encoding="utf-8") as sf:
        for g in groups:
            if len(g) <= 1:
                continue
            sf.write(", ".join(g) + "\n")
            all_tokens.update(g)

    # Flat token list (one per line)
    with (out_dir / "ext_dict.txt").open("w", encoding="utf-8") as df:
        for t in sorted(all_tokens):
            df.write(f"{t}\n")

    return len(all_tokens)


def _write_meta(out_dir: Path, *, total_groups: int, total_written: int,
                stats: dict[str, int]) -> None:
    """Write synonyms_meta.json."""
    meta: dict[str, Any] = {
        "_format_version": "synonyms_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "llm",
        "total_groups_assembled": total_groups,
        "total_groups_written": total_written,
        "stats": stats,
    }
    (out_dir / "synonyms_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_synonyms(
    *,
    dim_dict_path: str | Path,
    output_dir: str | Path,
    llm_client: Any,
    prompt_template_path: str | Path,
) -> dict[str, int]:
    """Generate ``synonyms_solr.txt`` via LLM-driven synonym expansion.

    Reads terms exclusively from ``dim_dictionary_snapshot.yaml``.
    Each unique value from every dimension is sent individually to the LLM.

    Returns stats dict.
    """
    import logging as _logging
    logger = _logging.getLogger(__name__)

    dim_dict = Path(dim_dict_path)
    out_dir = Path(output_dir)
    prompt_path = Path(prompt_template_path)

    if not dim_dict.exists():
        raise FileNotFoundError(f"dim_dictionary_snapshot.yaml not found: {dim_dict}")
    if not prompt_path.exists():
        raise FileNotFoundError(f"prompt template not found: {prompt_path}")

    # ---- load terms from dict snapshot only ----
    dim_data = _load_dim_dict(dim_dict)
    dims = sorted(k for k in dim_data if not k.startswith("_"))

    tags: dict[str, set[str]] = {}
    for dim_name in dims:
        dim_vals = (dim_data.get(dim_name) or {}).get("values", []) or []
        tags[dim_name] = {str(v).strip() for v in dim_vals if v and str(v).strip()}

    template = prompt_path.read_text(encoding="utf-8")

    # ---- summary ----
    total_terms = sum(len(tags[d]) for d in dims)
    print(f"Generating synonyms via LLM ({llm_client.model_name}):")
    for d in dims:
        print(f"  {d:16s} {len(tags[d]):>4} terms")
    print(f"  {'TOTAL':16s} {total_terms:>4} LLM calls")

    # ---- generate ----
    stats: dict[str, int] = {}
    all_groups: list[list[str]] = []

    for dim_name in dims:
        terms = tags[dim_name]
        if not terms:
            stats[f"{dim_name}_terms"] = 0
            stats[f"{dim_name}_groups"] = 0
            continue
        print(f"\n--- {dim_name} ({len(terms)} terms) ---")
        groups = _generate_synonyms_for_dim(terms, dim_name, template, llm_client, logger)
        all_groups.extend(groups)
        stats[f"{dim_name}_terms"] = len(terms)
        stats[f"{dim_name}_groups"] = len(groups)

    # ---- merge & deduplicate ----
    merged = _merge_overlapping_groups(all_groups)
    stats["total_groups"] = len(merged)

    # ---- write ----
    total_written = _write_solr_synonyms(merged, out_dir)
    stats["total_written"] = total_written
    _write_meta(out_dir, total_groups=len(merged), total_written=total_written, stats=stats)

    print(f"\n=== Synonyms generated ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  → {out_dir / 'ext_synonyms.txt'}   (同义词词表)")
    print(f"  → {out_dir / 'ext_dict.txt'}        (分词词表)")
    print(f"  → {out_dir / 'synonyms_meta.json'}")

    return stats


__all__ = ["build_synonyms"]
