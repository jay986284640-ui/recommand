"""extract_dictionary — Stage 1 Phase 2: dictionary candidate extraction.

Reads raw Hive/CSV columns AND Phase 1 LLM-inferred item_tags.jsonl, then
runs every dimension (brand, category, taste, cuisine, occasion,
consumable_type) through the same pipeline:

  aggregate → normalize → frequency-filter → diff vs authoritative dict

Outputs per-dimension CSVs + diffs + a unified ``dim_dictionary_snapshot.yaml``
that Stage 2 uses to constrain LLM output.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import click
import yaml

from ..common.logging import configure_logging, get_logger
from ..data_model import HiveReadSpec, Role, TableMeta
from ..hive_reader.base import HiveReader

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Text cleaning utilities
# ---------------------------------------------------------------------------

_PAREN_RE = re.compile(r"\([^)]*\)")
_CPAREN_RE = re.compile(r"[（].*?[）]")
_SUFFIX_RE = re.compile(
    r"(有限公司|集团|股份|Co\.?|Ltd\.?|Inc\.?|LLC|GmbH)$", re.IGNORECASE
)


def clean_brand(s: str) -> str:
    """Strip branch markers, legal suffixes, and parens."""
    if not s:
        return ""
    s = s.strip()
    s = _PAREN_RE.sub("", s)
    s = _CPAREN_RE.sub("", s)
    s = _SUFFIX_RE.sub("", s)
    return s.strip()


def clean_label(s: str) -> str:
    """Light normalisation for short label values (taste / cuisine / …)."""
    if not s:
        return ""
    s = s.strip()
    s = _PAREN_RE.sub("", s)
    s = _CPAREN_RE.sub("", s)
    return s.strip()


# ---------------------------------------------------------------------------
# Edit-distance helpers (used by brand / category clustering)
# ---------------------------------------------------------------------------

def levenshtein(a: str, b: str, max_dist: int | None = None) -> int:
    """Standard DP edit distance with optional early-exit cap."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        row_min = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
            if cur[-1] < row_min:
                row_min = cur[-1]
        if max_dist is not None and row_min > max_dist:
            return max_dist + 1
        prev = cur
    return prev[-1]


def jaccard_chars(a: str, b: str, n: int = 2) -> float:
    """Character n-gram Jaccard similarity."""
    if not a or not b:
        return 0.0
    a_grams = {a[i : i + n] for i in range(len(a) - n + 1)}
    b_grams = {b[i : i + n] for i in range(len(b) - n + 1)}
    if not a_grams or not b_grams:
        return 0.0
    inter = len(a_grams & b_grams)
    union = len(a_grams | b_grams)
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass
class RawRow:
    name: str
    frequency: int = 0
    sources: set[str] = field(default_factory=set)


def aggregate_raw(rows: Iterable[tuple[str, str]]) -> dict[str, RawRow]:
    """Aggregate (name, source) tuples into a name -> RawRow map."""
    agg: dict[str, RawRow] = defaultdict(lambda: RawRow(name=""))
    for name, source in rows:
        if not name:
            continue
        if name in agg:
            agg[name].frequency += 1
            agg[name].sources.add(source)
        else:
            agg[name] = RawRow(name=name, frequency=1, sources={source})
    return dict(agg)


# ---------------------------------------------------------------------------
# Hive / CSV raw-column queries
# ---------------------------------------------------------------------------


def query_brands_from_hive(
    reader: HiveReader, sql_tables: list[TableMeta], spec: HiveReadSpec
) -> list[tuple[str, str]]:
    """Yield (raw_brand_name, item_type_str) from all configured tables.

    Only uses explicit brand columns (``brnd_nm``, ``shopname``).
    ``str_nm`` is intentionally excluded — it's a store name, not a brand.
    Brands without an explicit column come from LLM inference via
    ``_read_llm_tags``.
    """
    out: list[tuple[str, str]] = []
    for tm in sql_tables:
        for rec in reader.read(tm, spec):
            raw_brand = rec.raw.get("brnd_nm") or rec.raw.get("shopname")
            if raw_brand:
                out.append((raw_brand, rec.item_type.value))
    return out


def _clean_cat_nm(raw: str) -> str:
    """Clean hierarchical category names from CSV.

    "地方菜系-云南菜" → "云南菜"
    "异域料理-日式料理" → "日式料理"
    "小吃快餐-米粉面馆" → "米粉面馆"
    """
    if not raw:
        return ""
    # If it has a "-" separator, take the part after the last "-"
    if "-" in raw:
        parts = raw.rsplit("-", 1)
        # Only strip if prefix looks like a broad category (全中文, no digits)
        prefix, suffix = parts[0], parts[1]
        if suffix and len(suffix) >= 2:
            return suffix.strip()
    return raw.strip()


def query_categories_from_hive(
    reader: HiveReader, sql_tables: list[TableMeta], spec: HiveReadSpec
) -> list[tuple[str, str]]:
    """Yield (raw_category_name, source_str) from all configured tables."""
    out: list[tuple[str, str]] = []
    for tm in sql_tables:
        for rec in reader.read(tm, spec):
            cat = rec.raw.get("cat_nm")
            if cat:
                cat = _clean_cat_nm(str(cat))
                if cat:
                    out.append((cat, rec.item_type.value or tm.table_name))
    return out


# ---------------------------------------------------------------------------
# LLM-inferred tag reader (Phase 1 output → Phase 2 input)
# ---------------------------------------------------------------------------

def _read_llm_tags(item_tags_path: str | Path) -> dict[str, list[tuple[str, str]]]:
    """Read Phase 1 ``item_tags.jsonl`` and extract LLM-inferred tag values.

    Returns ``{dim_name: [(value, "llm"), ...]}`` for every dimension present
    in the file.  Array-typed tags (e.g. taste) are flattened — each element
    becomes its own tuple.

    All tag dimensions are collected dynamically (no hardcoded list); every
    dimension discovered in ``item_tags.jsonl`` is aggregated.
    """
    path = Path(item_tags_path)
    if not path.exists():
        logger.warning("item_tags_missing", extra={"path": str(path)})
        return {}

    collected: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            tags = obj.get("tags", {}) if isinstance(obj, dict) else {}
            for dim, v in tags.items():
                if v is None:
                    continue
                if isinstance(v, list):
                    for x in v:
                        s = str(x).strip()
                        if s:
                            collected[dim].append((s, "llm"))
                else:
                    s = str(v).strip()
                    if s:
                        collected[dim].append((s, "llm"))
    return dict(collected)


# ---------------------------------------------------------------------------
# Normalization strategies (one per dimension type)
# ---------------------------------------------------------------------------


def _select_canonical(
    candidates: list[str], by_frequency: dict[str, int]
) -> str:
    """Pick canonical form: prefer highest frequency, tie-break by shorter."""
    return max(candidates, key=lambda n: (by_frequency.get(n, 0), -len(n)))


def normalize_brands(
    raw_rows: list[RawRow],
    *,
    levenshtein_threshold: int = 3,
    jaccard_threshold: float = 0.6,
    jaccard_ngram: int = 2,
) -> dict[str, dict]:
    """Cluster brand names via Levenshtein + Jaccard (greedy, by frequency)."""
    sorted_rows = sorted(raw_rows, key=lambda r: -r.frequency)
    by_freq = {r.name: r.frequency for r in raw_rows}

    clusters: list[set[str]] = []
    canonicals: list[str] = []

    for row in sorted_rows:
        cleaned = clean_brand(row.name)
        if not cleaned:
            continue
        placed = False
        for i, cluster in enumerate(clusters):
            canon = canonicals[i]
            if (
                levenshtein(cleaned.lower(), canon.lower(),
                            max_dist=levenshtein_threshold)
                <= levenshtein_threshold
                and jaccard_chars(cleaned, canon, n=jaccard_ngram)
                >= jaccard_threshold
            ):
                cluster.add(cleaned)
                placed = True
                break
        if not placed:
            clusters.append({cleaned})
            canonicals.append(_select_canonical([cleaned], by_freq))

    out: dict[str, dict] = {}
    for canon, cluster in zip(canonicals, clusters):
        total_freq = sum(by_freq.get(n, 0) for n in cluster)
        out[canon] = {
            "aliases": sorted(cluster),
            "frequency": total_freq,
            "n_variants": len(cluster),
            "sample_aliases": sorted(cluster)[:5],
        }
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["frequency"]))


def normalize_categories(
    raw_rows: list[RawRow],
    *,
    jaccard_threshold: float = 0.6,
) -> dict[str, dict]:
    """Cluster category names (character n-gram Jaccard only — categories are
    short enough that Levenshtein creates false merges)."""
    sorted_rows = sorted(raw_rows, key=lambda r: -r.frequency)
    by_freq = {r.name: r.frequency for r in raw_rows}

    clusters: list[set[str]] = []
    canonicals: list[str] = []

    for row in sorted_rows:
        cleaned = clean_label(row.name)
        if not cleaned:
            continue
        placed = False
        for i, canon in enumerate(canonicals):
            if jaccard_chars(cleaned, canon, n=2) >= jaccard_threshold:
                clusters[i].add(cleaned)
                placed = True
                break
        if not placed:
            clusters.append({cleaned})
            canonicals.append(_select_canonical([cleaned], by_freq))

    out: dict[str, dict] = {}
    for canon, cluster in zip(canonicals, clusters):
        total_freq = sum(by_freq.get(n, 0) for n in cluster)
        out[canon] = {
            "aliases": sorted(cluster),
            "frequency": total_freq,
            "n_variants": len(cluster),
        }
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["frequency"]))


def normalize_labels(
    raw_rows: list[RawRow],
) -> dict[str, dict]:
    """Deduplicate short label values (taste / cuisine / occasion /
    consumable_type).  No clustering — these are controlled categories where
    "辣" and "麻辣" should stay distinct.

    Light cleaning (strip parens / whitespace) is applied; synonymous forms
    that differ only by parens are merged.
    """
    merged: dict[str, RawRow] = {}
    for row in raw_rows:
        cleaned = clean_label(row.name)
        if not cleaned:
            continue
        if cleaned in merged:
            merged[cleaned].frequency += row.frequency
            merged[cleaned].sources |= row.sources
        else:
            merged[cleaned] = RawRow(
                name=cleaned,
                frequency=row.frequency,
                sources=set(row.sources),
            )

    return {
        name: {
            "aliases": [name],
            "frequency": r.frequency,
            "n_variants": 1,
        }
        for name, r in sorted(
            merged.items(), key=lambda kv: -kv[1].frequency
        )
    }


# ---------------------------------------------------------------------------
# Diff vs authoritative dictionaries
# ---------------------------------------------------------------------------


def diff_brands(current_yaml: dict, normalized: dict[str, dict]) -> dict:
    """Compute added / existing / removed against brand_dictionary.yaml."""
    existing_set = set(current_yaml.get("values", []) or [])
    candidate_set = set(normalized.keys())

    added_sorted = sorted(
        candidate_set - existing_set,
        key=lambda n: -normalized[n]["frequency"],
    )
    existing_sorted = sorted(
        candidate_set & existing_set,
        key=lambda n: -normalized[n]["frequency"],
    )
    removed_sorted = sorted(existing_set - candidate_set)

    return {
        "_meta": {
            "candidate_count": len(candidate_set),
            "existing_count": len(existing_set),
            "added_count": len(added_sorted),
            "removed_count": len(removed_sorted),
        },
        "added": [
            {
                "name": n,
                "frequency": normalized[n]["frequency"],
                "n_variants": normalized[n]["n_variants"],
                "sample_aliases": normalized[n].get("sample_aliases", []),
            }
            for n in added_sorted
        ],
        "existing": [
            {"name": n, "frequency": normalized[n]["frequency"]}
            for n in existing_sorted
        ],
        "removed": [{"name": n} for n in removed_sorted],
    }


def diff_dimension(
    current_yaml: dict, dim_name: str, normalized: dict[str, dict]
) -> dict:
    """Compute added / existing / removed for a single dimension inside
    ``dim_dictionary.yaml`` (category / taste / cuisine / occasion /
    consumable_type)."""
    dim_entry = (current_yaml.get(dim_name) or {})
    existing_set = set(dim_entry.get("values", []) or [])
    candidate_set = set(normalized.keys())

    added_sorted = sorted(
        candidate_set - existing_set,
        key=lambda n: -normalized[n]["frequency"],
    )
    existing_sorted = sorted(
        candidate_set & existing_set,
        key=lambda n: -normalized[n]["frequency"],
    )
    removed_sorted = sorted(existing_set - candidate_set)

    return {
        "_meta": {
            "candidate_count": len(candidate_set),
            "existing_count": len(existing_set),
            "added_count": len(added_sorted),
            "removed_count": len(removed_sorted),
        },
        "added": [
            {
                "name": n,
                "frequency": normalized[n]["frequency"],
                "n_variants": normalized[n]["n_variants"],
                "aliases": normalized[n].get("aliases", []),
            }
            for n in added_sorted
        ],
        "existing": [
            {"name": n, "frequency": normalized[n]["frequency"]}
            for n in existing_sorted
        ],
        "removed": [{"name": n} for n in removed_sorted],
    }


# Backward-compatible aliases (pre-v2.6)
clean_category = clean_label


def diff_categories(current_yaml: dict, normalized: dict[str, dict]) -> dict:
    """Backward-compatible wrapper for diff_dimension with ``category`` key."""
    return diff_dimension(current_yaml, "category", normalized)

# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, allow_unicode=True, default_flow_style=False,
                  sort_keys=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Dimension processing helper
# ---------------------------------------------------------------------------


def _process_dimension(
    *,
    dim_name: str,
    tuples: list[tuple[str, str]],
    normalizer,
    normalizer_kwargs: dict | None,
    current_dict: dict,
    dict_type: str,  # "brand" | "dim"
    frequency_min: int,
    output_dir: Path,
    extra_meta: dict | None = None,
) -> dict:
    """Run one dimension through the full pipeline and return stats.

    Returns a dict with keys: raw_count, normalized_count, filtered_count,
    added_count, removed_count, dim_name, raw_tuples.
    """
    raw = aggregate_raw(tuples)

    kwargs = normalizer_kwargs or {}
    norm = normalizer(list(raw.values()), **kwargs)
    norm_filtered = {
        k: v for k, v in norm.items() if v["frequency"] >= frequency_min
    }

    if dict_type == "brand":
        diff = diff_brands(current_dict, norm_filtered)
    else:
        diff = diff_dimension(current_dict, dim_name, norm_filtered)

    diff["_meta"]["frequency_min"] = frequency_min
    diff["_meta"]["raw_count"] = len(raw)
    diff["_meta"]["normalized_count"] = len(norm)
    diff["_meta"]["filtered_count"] = len(norm_filtered)
    if extra_meta:
        diff["_meta"].update(extra_meta)

    return {
        "dim_name": dim_name,
        "raw_count": len(raw),
        "normalized_count": len(norm),
        "filtered_count": len(norm_filtered),
        "added_count": diff["_meta"]["added_count"],
        "removed_count": diff["_meta"]["removed_count"],
        "candidates": norm_filtered,
        # keep raw tuples for the aggregated raw_tags.json output
        "raw_tuples": [
            {"value": r.name, "frequency": r.frequency,
             "sources": sorted(r.sources)}
            for r in sorted(raw.values(), key=lambda x: -x.frequency)
        ],
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def extract(
    *,
    tables_config_path: str | None = None,
    sql_path: str | None = None,
    output_dir: str = "dict_candidates",
    configs_dir: str = "configs",
    frequency_min: int = 10,
    levenshtein_threshold: int = 3,
    jaccard_threshold: float = 0.6,
    sample_n_per_type: int | None = None,
    hive_metastore_uri: str | None = None,
    warehouse_dir: str | None = None,
    csv_dir: str = "tests/fixtures/csv",
    csv_delimiter: str = ",",
    item_types: list[str] | None = None,
    item_tags_path: str | None = None,
) -> dict:
    """Run frequency extraction + normalisation for every dimension.

    Dimensions covered:
      - **brand** — from raw Hive/CSV columns (brnd_nm / str_nm / …)
      - **category** — merged from raw columns (cat_nm) AND Phase 1 LLM output
      - **taste, cuisine, occasion, consumable_type** — from Phase 1 LLM output

    Each dimension goes through: aggregate → normalize → frequency-filter →
    diff vs authoritative dictionary.  Per-dimension CSVs and diffs are written
    alongside a unified ``dim_dictionary_snapshot.yaml``.

    Args:
        item_tags_path: path to Phase 1 ``item_tags.jsonl``.  When provided,
            LLM-inferred values are read and merged into the corresponding
            dimensions.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    configs = Path(configs_dir)

    # ---- reader -----------------------------------------------------------

        from ..hive_reader.spark_reader import SparkHiveReader
        reader = SparkHiveReader(
            hive_metastore_uri=hive_metastore_uri,
            warehouse_dir=warehouse_dir,
        )
    elif source == "csv":
        from ..hive_reader.csv_reader import CsvReader
        reader = CsvReader(csv_dir=csv_dir, delimiter=csv_delimiter)
    else:
        raise ValueError(f"unknown source: {source}")

    # ---- tables -----------------------------------------------------------

    if sql_path:
        from ..sql_parser.parser import parse_sql
        sql_tables = parse_sql(sql_path)
    else:
        from ..common.tables_config import load_tables_config
        sql_tables = load_tables_config(tables_config_path)

    if item_types:
        target_roles = {Role(t) for t in item_types}
        sql_tables = [t for t in sql_tables if t.inferred_role in target_roles]

    print(f"  [extract] {len(sql_tables)} tables, source={source}")
    for t in sql_tables:
        print(f"    - {t.table_name} ({t.inferred_role.value})")

    spec = HiveReadSpec(source=source, sample_n_per_type=sample_n_per_type)

    # ---- read Phase 1 LLM tags --------------------------------------------

    llm_tags = _read_llm_tags(item_tags_path) if item_tags_path else {}

    # ---- authoritative dictionaries ---------------------------------------

    current_brand = (
        yaml.safe_load((configs / "brand_dictionary.yaml").read_text(encoding="utf-8"))
        if (configs / "brand_dictionary.yaml").exists()
        else {"values": []}
    )
    current_dim = (
        yaml.safe_load((configs / "dim_dictionary.yaml").read_text(encoding="utf-8"))
        if (configs / "dim_dictionary.yaml").exists()
        else {}
    )

    # ---- collect raw tuples per dimension ---------------------------------

    # brand: raw columns + LLM tags (union)
    brand_tuples = query_brands_from_hive(reader, sql_tables, spec) + llm_tags.get("brand", [])

    # category: LLM tags only (raw cat_nm is unreliable — contains cuisines,
    # hierarchical prefixes, etc.).  LLM inference provides clean categories.
    cat_tuples = llm_tags.get("category", [])

    # Remaining LLM-inferred label dims — exclude brand/category (special
    # handling) and numeric/geo dims that are not labels (avg_prc, distance, age).
    label_dims = {
        d: tuples
        for d, tuples in llm_tags.items()
        if d not in {"brand", "category", "avg_prc", "distance", "age"}
    }

    # ---- process each dimension -------------------------------------------

    dims: list[dict] = []

    # brand — special: diff vs brand_dictionary.yaml, not dim_dictionary.yaml
    dims.append(_process_dimension(
        dim_name="brand",
        tuples=brand_tuples,
        normalizer=normalize_brands,
        normalizer_kwargs={
            "levenshtein_threshold": levenshtein_threshold,
            "jaccard_threshold": jaccard_threshold,
        },
        current_dict=current_brand,
        dict_type="brand",
        frequency_min=frequency_min,
        output_dir=out,
        extra_meta={
            "levenshtein_threshold": levenshtein_threshold,
            "jaccard_threshold": jaccard_threshold,
        },
    ))

    # category — diff vs dim_dictionary.yaml.category
    dims.append(_process_dimension(
        dim_name="category",
        tuples=cat_tuples,
        normalizer=normalize_categories,
        normalizer_kwargs={"jaccard_threshold": jaccard_threshold},
        current_dict=current_dim,
        dict_type="dim",
        frequency_min=frequency_min,
        output_dir=out,
    ))

    # All remaining LLM-inferred dims — simple label dedup
    for dim_name in sorted(label_dims):
        dims.append(_process_dimension(
            dim_name=dim_name,
            tuples=label_dims[dim_name],
            normalizer=normalize_labels,
            normalizer_kwargs=None,
            current_dict=current_dim,
            dict_type="dim",
            frequency_min=frequency_min,
            output_dir=out,
        ))

    # ---- unified dim_dictionary_snapshot.yaml -----------------------------
    # ---- Save raw tags before aggregation ---------------------------------

    raw_tags: dict = {}
    snapshot: dict = {
        "_meta": {
            "version": "2.6-stage1-snapshot",
            "generated_from": {
                "raw_source": source,
                "item_tags": item_tags_path,
                "frequency_min": frequency_min,
            },
        },
    }
    for d in dims:
        name = d["dim_name"]
        candidates = d.get("candidates", {})
        snapshot[name] = {
            "desc": f"Stage 1 {name} values ({len(candidates)} unique)",
            "op": "in",
            "values": sorted(candidates.keys()),
        }
        raw_tags[name] = d.get("raw_tuples", [])
    _write_yaml(out / "dim_dictionary_snapshot.yaml", snapshot)

    with (out / "raw_tags.json").open("w", encoding="utf-8") as f:
        json.dump(raw_tags, f, ensure_ascii=False, indent=2, default=str)

    # ---- stats ------------------------------------------------------------

    stats: dict = {}
    for d in dims:
        name = d["dim_name"]
        stats[f"raw_{name}"] = d["raw_count"]
        stats[f"normalized_{name}"] = d["normalized_count"]
        stats[f"filtered_{name}"] = d["filtered_count"]
        stats[f"added_{name}"] = d["added_count"]
        stats[f"removed_{name}"] = d["removed_count"]
    stats["output_dir"] = str(out)

    return stats


# ---------------------------------------------------------------------------
# Click CLI (kept for backwards-compatible direct invocation)
# ---------------------------------------------------------------------------


@click.command()
@click.option("--fixture-dir", default="tests/fixtures/hive",
              help="mock fixture dir")
@click.option(
    "--tables-config", "tables_config_path", default=None,
    help="YAML declaring tables/columns (replaces --sql)",
)
@click.option(
    "--sql", "sql_path", default=None,
    help="(deprecated) SQL DDL file (use --tables-config instead)",
)
@click.option("--output-dir", default="dict_candidates")
@click.option("--configs-dir", default="configs")
@click.option("--frequency-min", default=10, type=int,
              help="min occurrences to include")
@click.option("--levenshtein-threshold", default=3, type=int)
@click.option("--jaccard-threshold", default=0.6, type=float)
@click.option("--n-items-per-type", type=int, default=None)
@click.option("--item-tags-path", default=None,
              help="Phase 1 item_tags.jsonl (for LLM-inferred dims)")
@click.option("--log-level", default="INFO")
def main(
    frequency_min, levenshtein_threshold, jaccard_threshold,
    n_items_per_type, item_tags_path, log_level,
):
    """Stage 0 dictionary candidate extraction (offline CLI)."""
    configure_logging(log_level)
    if tables_config_path and tables_config_path != "configs/tables.yaml":
        kw = "tables_config_path"
        val = tables_config_path
    elif sql_path:
        kw = "sql_path"
        val = sql_path
    else:
        kw = "tables_config_path"
        val = "configs/tables.yaml"
    stats = extract(
        source=source,
        **{kw: val},
        output_dir=output_dir,
        configs_dir=configs_dir,
        frequency_min=frequency_min,
        levenshtein_threshold=levenshtein_threshold,
        jaccard_threshold=jaccard_threshold,
        sample_n_per_type=n_items_per_type,
        item_tags_path=item_tags_path,
    )
    click.echo("Stage 0 extract-dictionary complete:")
    for k, v in stats.items():
        click.echo(f"  {k}: {v}")
    click.echo(
        f"\nReview {output_dir}/dim_dictionary_snapshot.yaml "
        f"for candidates to promote."
    )


if __name__ == "__main__":
    main()
