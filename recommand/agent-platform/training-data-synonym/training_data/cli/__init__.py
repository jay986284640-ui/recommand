"""Top-level CLI for training-data (per Constitution Principle II).

Subcommands:
  tables-meta       — YAML tables → tables_meta.json
  extract-tags      — Stage 1: LLM 自由推断 + 频次统计 → dim_dictionary_snapshot.yaml
  enrich            — Stage 2: 字典约束标注 → item_tags.jsonl + item_profile.jsonl
  sft               — Stage 3: item_tags → sft_corpus.jsonl
  generate-synonyms — item_profile → synonyms_solr.txt (ES 检索)
  split             — sft_corpus → train/val/test
  verify            — summary.json → SC pass/fail report
  all               — full pipeline: enrich → sft → split → verify
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..common.config import Config
from ..common.exceptions import PipelineError
from ..common.llm_client import LLMClient, build_llm_client
from ..common.logging import configure_logging, get_logger
from ..hive_reader.base import HiveReadSpec
from ..hive_reader.mock_reader import MockHiveReader
from ..enricher.pipeline import EnrichmentPipeline

logger = get_logger(__name__)


def _resolve_llm_settings(cfg: Config, args, stage: str) -> dict:
    """Resolve LLM settings from CLI flag > env var > yaml.

    `stage` is the key under cfg.pipeline (e.g. ``"enrichment"`` / ``"sft"``).
    Resolution precedence for each field:
      - CLI flag (if non-None)
      - env var named by ``api_key_env`` (api_key only)
      - yaml value (provider / model / base_url / max_tokens / timeout_seconds)
      - hard-coded default (provider = "mock", timeout_seconds = 15, max_tokens = 1024)

    Returns a kwargs dict suitable for :func:`build_llm_client`.
    """
    llm_cfg = cfg.pipeline.get("training_data") or {}
    llm_cfg = (llm_cfg.get(stage) or {}).get("llm") or {}

    # provider
    provider = getattr(args, "provider", None) or llm_cfg.get("provider") or "mock"

    # model
    model = llm_cfg.get("model") or "mock-llm"

    # api_key: CLI > env[api_key_env] > yaml
    api_key = getattr(args, "api_key", None)
    if not api_key:
        env_name = llm_cfg.get("api_key_env") or "OPENAI_API_KEY"
        api_key = os.environ.get(env_name)
    if not api_key:
        api_key = llm_cfg.get("api_key")  # direct key in yaml

    # base_url
    base_url = getattr(args, "base_url", None)
    if base_url is None:
        base_url = llm_cfg.get("base_url")  # may be None → default in client

    # max_tokens
    max_tokens = getattr(args, "max_tokens", None)
    if max_tokens is None:
        max_tokens = llm_cfg.get("max_tokens") or 1024

    timeout_seconds = llm_cfg.get("timeout_seconds") or 15.0
    seed = getattr(args, "seed", 42) or 42

    # extra headers from yaml (for custom API gateways)
    extra_headers = llm_cfg.get("headers") or None
    verify_ssl = llm_cfg.get("verify_ssl", True)

    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "timeout_seconds": timeout_seconds,
        "max_tokens": max_tokens,
        "seed": seed,
        "extra_headers": extra_headers,
        "verify_ssl": verify_ssl,
    }


def _resolve_sql_legacy_alias(args) -> None:
    """Warn (no-op transform) when ``--sql <path>`` is supplied.

    We do NOT translate ``--sql`` to ``--tables-config`` automatically because
    the two point at different file formats (SQL DDL vs YAML). Consumers
    (:func:`cmd_enrich`, :func:`cmd_extract_dictionary`) check both flags and
    prefer ``--tables-config`` when set; otherwise they fall back to
    :func:`parse_sql` on ``args.sql``.
    """
    sql_path = getattr(args, "sql", None)
    tables_cfg = getattr(args, "tables_config", None)
    if sql_path:
        print(
            f"WARNING: --sql is deprecated; use --tables-config <path-to-yaml> "
            f"(got --sql {sql_path}, --tables-config {tables_cfg!r})",
            file=sys.stderr,
        )


def _resolve_tables_config(args) -> str:
    """Return the YAML tables-config path the consumer should use.

    Preference:
      1. ``--tables-config X`` (explicit, default ``configs/tables.yaml``)
      2. ``--sql Y`` (legacy alias; fall back to ``parse_sql(Y)``)
         We DO NOT auto-translate because SQL DDL and YAML are different
         file formats; the consumer must decide which loader to call.
         Here we just return the chosen path; consumers wire the loader.
    """
    tables_cfg = getattr(args, "tables_config", None)
    sql_path = getattr(args, "sql", None)
    # If --tables-config was explicitly set to something other than the
    # default AND --sql is also set, prefer --tables-config (newer intent).
    default_tables = "configs/tables.yaml"
    if tables_cfg and (tables_cfg != default_tables or sql_path is None):
        return tables_cfg
    if sql_path:
        return sql_path
    return tables_cfg or default_tables


def _build_hive_reader(args, configs_dir: Path):
    if args.source == "mock":
        return MockHiveReader(
            fixture_dir=configs_dir / "tests" / "fixtures" / "hive"
            if False  # placeholder; resolve from --fixture-dir or default
            else Path(args.fixture_dir or "tests/fixtures/hive")
        )
    if args.source == "hive":
        from ..hive_reader.spark_reader import SparkHiveReader

        return SparkHiveReader(
            catalog=getattr(args, "spark_catalog", "spark_catalog"),
            hive_metastore_uri=getattr(args, "hive_metastore_uri", None),
            warehouse_dir=getattr(args, "warehouse_dir", None),
        )
    if args.source == "csv":
        from ..hive_reader.csv_reader import CsvReader

        csv_dir = getattr(args, "csv_dir", None)
        csv_delimiter = getattr(args, "csv_delimiter", None) or ","
        # Fallback to pipeline.yaml config if not specified on CLI
        if csv_dir is None:
            try:
                cfg = Config.load(args.configs_dir)
                csv_cfg = ((cfg.pipeline.get("training_data") or {}).get("input") or {}).get("csv") or {}
                csv_dir = csv_cfg.get("csv_dir") or "../../knowledge_database"
                csv_delimiter = csv_cfg.get("delimiter") or csv_delimiter
            except Exception:
                csv_dir = "../../knowledge_database"
        return CsvReader(csv_dir=csv_dir, delimiter=csv_delimiter)
    raise ValueError(f"unknown source: {args.source} (expected 'mock', 'hive', or 'csv')")


def cmd_tables_meta(args) -> int:
    from ..common.tables_config import load_tables_config

    tables = load_tables_config(args.tables_config)
    out = args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "db": t.db,
            "table_name": t.table_name,
            "inferred_role": t.inferred_role.value,
            "partition_keys": t.partition_keys,
            "columns": [{"name": c.name, "type": c.type, "comment": c.comment} for c in t.columns],
            "_format_version": t._format_version,
        }
        for t in tables
    ]
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(tables)} TableMeta to {out}")
    return 0


# ---------------------------------------------------------------------------
# Shared enrichment runner — used by both Stage 1 (free-form) and Stage 2 (constrained)
# ---------------------------------------------------------------------------

def _resolve_tables_config_kwarg(args) -> tuple[str, str]:
    """Return (keyword, value) for the tables-config argument passed to pipelines."""
    tables_cfg = getattr(args, "tables_config", None)
    sql_path = getattr(args, "sql", None)
    if tables_cfg and (tables_cfg != "configs/tables.yaml" or sql_path is None):
        return "tables_config_path", tables_cfg
    if sql_path:
        return "sql_path", sql_path
    return "tables_config_path", tables_cfg or "configs/tables.yaml"


def _run_enrichment(
    args,
    *,
    constrain_to_dict: bool,
    dict_snapshot_path: str | None = None,
    stage_label: str = "enrich",
    prompt_template_path: str | None = None,
) -> dict:
    """Run EnrichmentPipeline and return the summary dict.

    Args:
        args: parsed CLI namespace (must have the standard enrich-related attrs).
        constrain_to_dict: ``False`` for Stage 1 free-form, ``True`` for Stage 2
            dictionary-constrained mode.
        dict_snapshot_path: optional path to a Stage 1 snapshot YAML whose values
            constrain the LLM output (Stage 2 mode).
        stage_label: human-readable label for log/progress messages.

    Returns the ``EnrichmentPipeline`` summary object (a dataclass with
    ``items_enriched``, ``coverage_avg``, ``dict_rejected_count``, ``sc_pass``,
    and ``__dict__`` for JSON serialisation).
    """
    cfg = Config.load(args.configs_dir)
    hive = _build_hive_reader(args, Path(args.configs_dir))
    settings = _resolve_llm_settings(cfg, args, "enrichment")
    llm: LLMClient = build_llm_client(**settings)

    if dict_snapshot_path:
        import yaml

        cfg.dim_dictionary = (
            yaml.safe_load(Path(dict_snapshot_path).read_text(encoding="utf-8")) or {}
        )
        print(f"{stage_label}: using dict snapshot from {dict_snapshot_path}")

    sample_n = getattr(args, "n_items_per_type", None) or None
    kw, val = _resolve_tables_config_kwarg(args)
    print(f"{stage_label}: building EnrichmentPipeline "
          f"(constrain_to_dict={constrain_to_dict}, llm={llm.model_name}, "
          f"sample_n={sample_n})")
    pipeline = EnrichmentPipeline(
        config=cfg,
        hive_reader=hive,
        llm_client=llm,
        output_dir=args.output_dir,
        constrain_to_dict=constrain_to_dict,
        sample_n_per_type=sample_n,
        prompt_template_path=prompt_template_path,
        **{kw: val},
    )
    print(f"{stage_label}: running enrichment pipeline...")
    return pipeline.run()


# ---------------------------------------------------------------------------
# Stage 2: enrich — 字典约束标注
# ---------------------------------------------------------------------------

def cmd_enrich(args) -> int:
    """Stage 2: 字典约束标注 → item_tags.jsonl + item_profile.jsonl.

    Requires ``--dict-snapshot`` from Stage 1 (or falls back to
    ``configs/dim_dictionary.yaml``).
    """
    summary = _run_enrichment(
        args,
        constrain_to_dict=True,
        dict_snapshot_path=getattr(args, "dict_snapshot", None),
        stage_label="Stage 2",
    )

    print(f"=== Stage 2: enrich complete ===")
    print(f"  {summary.items_enriched} items, coverage_avg={summary.coverage_avg:.2f}")
    print(f"  dict_rejected={summary.dict_rejected_count}, SC pass: {summary.sc_pass}")
    print(f"  Products: {args.output_dir}/")
    print(f"    item_profile.jsonl")
    print(f"Next: Stage 3 sft --input {args.output_dir}/item_profile.jsonl")
    return 0 if all(summary.sc_pass.values()) else 1


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Stage 1: extract-tags — 全量标签抽取 (LLM 自由推断 + 品牌/分类频次)
# ---------------------------------------------------------------------------

def _extract_tags_impl(args) -> int:
    """Stage 1: 全量标签抽取 → dim_dictionary_snapshot.yaml.

    Two-phase:
      1. LLM free-form enrich on a small sample (constrain_to_dict=False).
      2. Raw frequency extraction for brand/category from the full dataset.

    Merges both into the output directory as:
      - item_tags.jsonl (Phase 1 LLM results on the sample)
      - brands_diff.yaml + categories_diff.yaml (Phase 2 frequency stats)
      - dim_dictionary_snapshot.yaml (combined constraint set for Stage 2)
    """
    from .extract_dictionary import extract

    # ---- Phase 1: LLM free-form enrich ----
    # Priority: CLI flag > config > no limit
    sample_n = getattr(args, "n_items_per_type", None)
    if sample_n is None:
        cfg = Config.load(args.configs_dir)
        input_cfg = (cfg.pipeline.get("training_data") or {}).get("input") or {}
        sample_n = input_cfg.get("sample_n_per_type")  # may be None → all
    label = sample_n if sample_n is not None else "all"
    print(f"=== Stage 1 Phase 1: LLM free-form enrich ({label}/type) ===")

    # Temporarily override n_items_per_type for sampling (the shared runner
    # reads it from args).  Restore after the call so Phase 2 sees the original.
    saved_n = getattr(args, "n_items_per_type", None)
    args.n_items_per_type = sample_n

    summary = _run_enrichment(
        args,
        constrain_to_dict=False,
        dict_snapshot_path=None,
        stage_label="Stage 1",
        prompt_template_path="configs/prompts/extract-tags.txt",
    )

    if saved_n is not None:
        args.n_items_per_type = saved_n
    else:
        del args.n_items_per_type

    # Write LLM stats (success/failure counts, token usage, etc.)
    out_dir = Path(args.output_dir)
    llm_stats = {
        "items_processed": summary.items_processed,
        "items_enriched": summary.items_enriched,
        "items_cold_start": summary.items_cold_start,
        "llm_calls": summary.llm_calls,
        "llm_failures": summary.llm_failures,
        "dict_pass_rate": summary.dict_pass_rate,
        "coverage_avg": summary.coverage_avg,
        "dict_rejected_count": summary.dict_rejected_count,
        "started_at": summary.started_at,
        "finished_at": summary.finished_at,
    }
    (out_dir / "llm_stats.json").write_text(
        json.dumps(llm_stats, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    phase1_ok = all(summary.sc_pass.values())

    # ---- Phase 2: dictionary extraction ----

    print(f"\n=== Stage 1 Phase 2: dictionary extraction ===")

    # Read item_types from pipeline config so Phase 2 only queries tables
    # the user actually has data for (instead of requiring all 3 roles).
    cfg = Config.load(args.configs_dir)
    input_cfg = (cfg.pipeline.get("training_data") or {}).get("input") or {}
    item_types = input_cfg.get("item_types")  # None → all tables

    # Phase 1 wrote item_tags.jsonl → feed the LLM tags into Phase 2 so
    # taste / cuisine / occasion / consumable_type also get aggregated,
    # normalized, frequency-filtered, and diffed.
    item_tags_path = str(out_dir / "item_tags.jsonl")

    kw, val = _resolve_tables_config_kwarg(args)
    # Resolve csv_dir / csv_delimiter from CLI > pipeline.yaml > default
    csv_dir = getattr(args, "csv_dir", None)
    csv_delimiter = getattr(args, "csv_delimiter", None) or ","
    if csv_dir is None:
        csv_cfg = ((cfg.pipeline.get("training_data") or {}).get("input") or {}).get("csv") or {}
        csv_dir = csv_cfg.get("csv_dir") or "../../knowledge_database"
        csv_delimiter = csv_cfg.get("delimiter") or csv_delimiter

    stats = extract(
        source=args.source,
        fixture_dir=args.fixture_dir,
        **{kw: val},
        output_dir=args.output_dir,
        configs_dir=args.configs_dir,
        frequency_min=args.frequency_min,
        levenshtein_threshold=args.levenshtein_threshold,
        jaccard_threshold=args.jaccard_threshold,
        sample_n_per_type=getattr(args, "n_items_per_type", None),
        hive_metastore_uri=getattr(args, "hive_metastore_uri", None),
        warehouse_dir=getattr(args, "warehouse_dir", None),
        csv_dir=csv_dir,
        csv_delimiter=csv_delimiter,
        item_types=item_types,
        item_tags_path=item_tags_path,
    )

    # ---- Cleanup: remove intermediate files ----

    cleanup_files = [
        "item_tags.jsonl",
        "tag_enrichment_state.jsonl",
        "tag_enrichment_failures.jsonl",
        "cold_start_items.jsonl",
        "tables_meta.json",
        "summary.json",
    ]
    for fname in cleanup_files:
        fp = out_dir / fname
        if fp.exists():
            fp.unlink()

    # ---- Done ----

    print(f"\n=== Stage 1: extract-tags complete ===")
    print(f"  Phase 1 (LLM enrich):  {'OK' if phase1_ok else 'failed'}")
    print(f"  Phase 2 (dictionary):")
    # Collect all dimension names from stats dynamically
    dim_names = sorted({
        k.split("_", 1)[1] for k in stats
        if k.startswith("raw_") and not k.endswith("s")
    })
    for dim in dim_names:
        raw = stats.get(f"raw_{dim}", 0)
        norm = stats.get(f"normalized_{dim}", 0)
        added = stats.get(f"added_{dim}", 0)
        print(f"    {dim:20s}  {raw:>4} raw → {norm:>4} normalized → {added:>4} added")
    print(f"  Products: {args.output_dir}/")
    print(f"    item_profile.jsonl           (enriched item profiles)")
    print(f"    dim_dictionary_snapshot.yaml (→ Stage 2 constraint)")
    print(f"    raw_tags.json                (all tags before aggregation)")
    print(f"    llm_stats.json               (LLM call success/failure stats)")
    print(
        f"Next: Stage 2 enrich --dict-snapshot {args.output_dir}/dim_dictionary_snapshot.yaml"
    )
    return 0


# Public names bound in build_parser()
cmd_extract_tags = _extract_tags_impl
cmd_extract_dictionary = _extract_tags_impl  # legacy alias


def cmd_generate_synonyms(args) -> int:
    """Generate synonyms_solr.txt from Stage 1 item_profile via LLM.

    Each unique brand / category tag is sent individually to the LLM for
    synonym generation.  Results are merged, deduplicated, and written in
    ES Solr multi-way format.
    """
    import sys

    _synonym_dir = Path(__file__).resolve().parent.parent.parent / "synonym-dictionary"
    if str(_synonym_dir) not in sys.path:
        sys.path.insert(0, str(_synonym_dir))
    from synonym_builder import build_synonyms

    # ---- resolve paths ----
    dict_snapshot = (
        Path(args.dict_snapshot)
        if getattr(args, "dict_snapshot", None)
        else Path("output/stage1/dim_dictionary_snapshot.yaml")
    )
    if not dict_snapshot.exists():
        print(f"ERROR: dim_dictionary_snapshot.yaml not found: {dict_snapshot}", file=sys.stderr)
        print(f"  Run Stage 1 extract-tags first, or use --dict-snapshot <path>",
              file=sys.stderr)
        return 2

    output_dir = (
        Path(args.output_dir) if getattr(args, "output_dir", None)
        else _synonym_dir / "output"
    )

    prompt_template = (
        Path(args.prompt_template)
        if getattr(args, "prompt_template", None)
        else _synonym_dir / "configs" / "prompts" / "synonym_generation.txt"
    )
    if not prompt_template.exists():
        print(f"ERROR: prompt template not found: {prompt_template}", file=sys.stderr)
        return 2

    # ---- build LLM client ----
    cfg = Config.load(args.configs_dir)
    # Reuse enrichment LLM settings for synonym generation (low-temp, short response)
    settings = _resolve_llm_settings(cfg, args, "enrichment")
    # Override max_tokens for synonym generation (smaller response)
    settings.setdefault("max_tokens", 512)
    llm: LLMClient = build_llm_client(**settings)
    print(f"Synonym generation via LLM: {llm.model_name}")

    # ---- run ----
    stats = build_synonyms(
        dim_dict_path=dict_snapshot,
        output_dir=output_dir,
        llm_client=llm,
        prompt_template_path=prompt_template,
    )
    print(f"\n=== Synonyms generated ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  → {output_dir / 'ext_synonyms.txt'}   (同义词)")
    print(f"  → {output_dir / 'ext_dict.txt'}        (分词)")
    print(f"  → {output_dir / 'synonyms_meta.json'}")
    return 0


def cmd_sft(args) -> int:
    cfg = Config.load(args.configs_dir)
    settings = _resolve_llm_settings(cfg, args, "sft")
    llm = build_llm_client(**settings)
    from ..sft.pipeline import SFTPipeline

    pipeline = SFTPipeline(
        config=cfg,
        llm_client=llm,
        input_path=args.input,
        output_dir=args.output_dir,
        count_per_item=getattr(args, "count_per_item", 8),
        max_message_turns=getattr(args, "max_message_turns", 9),
        max_items=getattr(args, "max_items", None),
    )
    summary = pipeline.run()
    print(
        f"Stage 3 complete: {summary.total} samples, "
        f"{summary.sft_failures} failures"
    )
    print(f"  intent_distribution: {summary.intent_distribution}")
    print(f"  scenario_distribution: {summary.scenario_distribution}")
    return 0 if summary.sft_failures == 0 else 1


def cmd_split(args) -> int:
    """Split sft_corpus.jsonl into train/val/test.jsonl by item_id md5 bucket.

    Bucket assignment: ``int(hashlib.md5(item_id).hexdigest(), 16) % 100``.
    Each item_id goes to exactly one split (SC-010: no leak).
    Default paths and ratios come from ``configs/pipeline.yaml``.
    """
    import hashlib

    cfg = Config.load(args.configs_dir)
    split_cfg = (cfg.pipeline.get("training_data") or {}).get("split") or {}
    train_ratio = float(split_cfg.get("train_ratio", 0.8))
    val_ratio = float(split_cfg.get("val_ratio", 0.1))
    test_ratio = float(split_cfg.get("test_ratio", 0.1))

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    in_path = Path(args.input) if args.input else out_dir / "sft_corpus.jsonl"
    if not in_path.exists():
        print(f"ERROR: input not found: {in_path}", file=sys.stderr)
        return 2

    train_path = out_dir / Path(split_cfg.get("train_path", "./train.jsonl")).name
    val_path = out_dir / Path(split_cfg.get("val_path", "./val.jsonl")).name
    test_path = out_dir / Path(split_cfg.get("test_path", "./test.jsonl")).name

    # 1. group by item_id (each item can produce multiple samples)
    by_item: dict[str, list[dict]] = {}
    with in_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            by_item.setdefault(obj.get("item_id", ""), []).append(obj)

    splits: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for item_id, samples in by_item.items():
        h = int(hashlib.md5(item_id.encode("utf-8")).hexdigest(), 16) % 100
        if h < int(train_ratio * 100):
            tgt = "train"
        elif h < int((train_ratio + val_ratio) * 100):
            tgt = "val"
        else:
            tgt = "test"
        splits[tgt].extend(samples)

    # 2. write files
    for path, items in (
        (train_path, splits["train"]),
        (val_path, splits["val"]),
        (test_path, splits["test"]),
    ):
        path.write_text(
            "\n".join(json.dumps(s, ensure_ascii=False) for s in items),
            encoding="utf-8",
        )

    # 3. SC-010 no-leak check
    item_to_split: dict[str, set[str]] = {}
    for split_name, items in splits.items():
        for s in items:
            item_to_split.setdefault(s.get("item_id", ""), set()).add(split_name)
    no_leak = all(len(v) == 1 for v in item_to_split.values())

    print(
        f"Split complete: train={len(splits['train'])} "
        f"val={len(splits['val'])} test={len(splits['test'])} "
        f"no_leak={no_leak}"
    )
    print(f"  train → {train_path}")
    print(f"  val   → {val_path}")
    print(f"  test  → {test_path}")
    return 0 if no_leak else 1


def cmd_verify(args) -> int:
    """Read summary.json + train/val/test.jsonl; write verify_report.json.

    Aggregates SC checks across Stage 1 (enrich) + Stage 2 (sft) + splits.
    SC-008 / SC-009 / SC-011 are skipped when their artifacts are absent.
    """
    out_dir = Path(args.output_dir)
    summary_path = out_dir / "summary.json"

    sc_pass: dict[str, Optional[bool]] = {}
    enrich_summary: dict = {}
    sft_summary: dict = {}

    if not summary_path.exists():
        print(f"ERROR: {summary_path} not found", file=sys.stderr)
        return 2

    full = json.loads(summary_path.read_text(encoding="utf-8"))
    enrich_summary = full
    sc_pass.update(enrich_summary.get("sc_pass") or {})
    sft_summary = full.get("sft") or {}
    if "coverage_pass" in sft_summary:
        sc_pass["SC-005"] = bool(sft_summary.get("coverage_pass"))

    # SC-002: dict validation (enrich side)
    dict_rate = float(enrich_summary.get("dict_pass_rate", 0.0))
    sc_pass.setdefault("SC-002", dict_rate == 1.0)

    # SC-003: enrich-side coverage avg
    coverage = float(enrich_summary.get("coverage_avg", 0.0))
    sc_pass.setdefault("SC-003", coverage >= 6.5)

    # SC-004: item_tags.jsonl parseable + non-empty
    item_tags = out_dir / "item_tags.jsonl"
    if item_tags.exists():
        try:
            n = sum(1 for line in item_tags.open(encoding="utf-8") if line.strip())
            sc_pass["SC-004"] = n > 0
        except Exception:
            sc_pass["SC-004"] = False
    else:
        sc_pass["SC-004"] = False

    # SC-008: retention rate (only if cleaning_report.json present)
    cr_path = out_dir / "cleaning_report.json"
    if cr_path.exists():
        try:
            cr = json.loads(cr_path.read_text(encoding="utf-8"))
            retention = float(cr.get("retention_rate", 0.0))
            sc_pass["SC-008"] = retention >= 0.85
        except Exception:
            sc_pass["SC-008"] = False
    else:
        sc_pass["SC-008"] = None  # not run yet

    # SC-009: distribution warnings (only if distribution_report.json present)
    dr_path = out_dir / "distribution_report.json"
    if dr_path.exists():
        try:
            dr = json.loads(dr_path.read_text(encoding="utf-8"))
            warns = dr.get("warnings") or []
            sc_pass["SC-009"] = len(warns) <= 2
        except Exception:
            sc_pass["SC-009"] = False
    else:
        sc_pass["SC-009"] = None

    # SC-010: no item leak across train/val/test
    if all((out_dir / n).exists() for n in ["train.jsonl", "val.jsonl", "test.jsonl"]):
        item_to_split: dict[str, set[str]] = {}
        for split_name in ("train", "val", "test"):
            p = out_dir / f"{split_name}.jsonl"
            for line in p.open(encoding="utf-8"):
                if not line.strip():
                    continue
                obj = json.loads(line)
                item_to_split.setdefault(obj.get("item_id", ""), set()).add(split_name)
        sc_pass["SC-010"] = all(len(v) == 1 for v in item_to_split.values())
    else:
        sc_pass["SC-010"] = None

    # Build report
    report = {
        "sc_pass": sc_pass,
        "all_pass": all(v is True for v in sc_pass.values()),
        "ran_at": datetime.utcnow().isoformat() + "Z",
        "checked_artifacts": {
            "summary_json": str(summary_path),
            "item_tags_jsonl": str(item_tags) if item_tags.exists() else None,
            "splits": [
                str(out_dir / n)
                for n in ("train.jsonl", "val.jsonl", "test.jsonl")
                if (out_dir / n).exists()
            ],
            "cleaning_report": str(cr_path) if cr_path.exists() else None,
            "distribution_report": str(dr_path) if dr_path.exists() else None,
        },
    }
    report_path = out_dir / "verify_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=== SC verify ===")
    for k in sorted(sc_pass):
        v = sc_pass[k]
        marker = "PASS" if v is True else "FAIL" if v is False else "skip"
        print(f"  {k}: {marker} ({v})")
    print(f"\n  all_pass: {report['all_pass']}")
    print(f"  → {report_path}")
    return 0 if report["all_pass"] else 1


def cmd_all(args) -> int:
    """3-Stage pipeline: extract-tags → enrich → sft → split → verify."""
    from ..enricher.pipeline import EnrichmentPipeline
    from ..sft.pipeline import SFTPipeline

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = Config.load(args.configs_dir)
    hive = _build_hive_reader(args, Path(args.configs_dir))
    enrich_settings = _resolve_llm_settings(cfg, args, "enrichment")
    enrich_llm = build_llm_client(**enrich_settings)
    sft_settings = _resolve_llm_settings(cfg, args, "sft")
    sft_llm = build_llm_client(**sft_settings)

    # Stage 2: enrich (实际标注数据,8 维标签)
    print("=== Stage 2: enrich (实际标注数据) ===")
    enrich = EnrichmentPipeline(
        config=cfg,
        tables_config_path=args.tables_config,
        hive_reader=hive,
        llm_client=enrich_llm,
        output_dir=out_dir,
    )
    enrich_summary = enrich.run()
    if not all(enrich_summary.sc_pass.values()):
        print("Stage 2 (enrich) failed SC self-check; aborting.", file=sys.stderr)
        return 1

    # Stage 3: sft (合成 SFT 训练数据)
    print("\n=== Stage 3: sft (合成 SFT 数据) ===")
    sft = SFTPipeline(
        config=cfg,
        llm_client=sft_llm,
        input_path=out_dir / "item_tags.jsonl",
        output_dir=out_dir,
        count_per_item=getattr(args, "count_per_item", 8),
        max_message_turns=getattr(args, "max_message_turns", 6),
        negative_ratio=getattr(args, "negative_ratio", 0.10),
    )
    sft_summary = sft.run()
    if not (sft_summary.coverage_pass and sft_summary.sft_failures == 0):
        print("Stage 3 (sft) failed coverage; aborting.", file=sys.stderr)
        return 1

    # split → verify
    print("\n=== split ===")
    import argparse

    split_args = argparse.Namespace(
        configs_dir=args.configs_dir,
        tables_config=args.tables_config,
        input=str(out_dir / "sft_corpus.jsonl"),
        output_dir=str(out_dir),
        log_level=args.log_level,
    )
    rc = cmd_split(split_args)
    if rc != 0:
        return rc

    print("\n=== verify ===")
    verify_args = argparse.Namespace(
        configs_dir=args.configs_dir,
        tables_config=args.tables_config,
        output_dir=str(out_dir),
        log_level=args.log_level,
    )
    return cmd_verify(verify_args)


def build_parser() -> argparse.ArgumentParser:
    # Shared parent parser — global flags attached to every subcommand.
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--tables-config",
        default="configs/tables.yaml",
        help="YAML file declaring tables / columns / data types (replaces --sql).",
    )
    parent.add_argument(
        "--sql",
        default=None,
        help=argparse.SUPPRESS,  # deprecated alias; see _resolve_sql_legacy_alias
    )
    parent.add_argument("--configs-dir", default="configs")
    parent.add_argument("--log-level", default="INFO")
    # Hive reader config (for --source hive)
    parent.add_argument(
        "--hive-metastore-uri",
        default="thrift://localhost:9083",
        help="Hive metastore Thrift URI (spark.hadoop.hive.metastore.uris)",
    )
    parent.add_argument(
        "--warehouse-dir",
        default="/opt/bigdata/hive/warehouse",
        help="Spark SQL warehouse directory (spark.sql.warehouse.dir)",
    )
    parent.add_argument(
        "--spark-catalog",
        default="spark_catalog",
        help="Spark catalog name for Hive tables",
    )
    # LLM provider overrides (apply to every subcommand; enrichment/sft consume them)
    parent.add_argument(
        "--provider",
        default=None,
        help="LLM provider override (mock|openai_compat); default from yaml",
    )
    parent.add_argument(
        "--api-key",
        default=None,
        help="API key override; else read from $OPENAI_API_KEY (or yaml api_key_env)",
    )
    parent.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible endpoint base URL; default from yaml",
    )
    parent.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Max tokens per LLM response; default from yaml",
    )

    p = argparse.ArgumentParser(
        prog="training-data",
        description="兴业 O2O 三品类 SFT 语料生成流水线\n"
        "Stage 1 extract-tags → Stage 2 enrich → Stage 3 sft → split → verify",
        parents=[parent],
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # tables-meta
    sp = sub.add_parser("tables-meta", help="Parse SQL → tables_meta.json", parents=[parent])
    sp.add_argument("--output", type=Path, default=Path("tables_meta.json"))
    sp.set_defaults(func=cmd_tables_meta)

    # Stage 1: extract-tags (全量标签抽取)
    sp = sub.add_parser(
        "extract-tags",
        help="Stage 1: 全量标签抽取 → dim_dictionary_snapshot.yaml",
        parents=[parent],
    )
    sp.add_argument("--source", choices=["hive", "mock", "csv"], default="mock")
    sp.add_argument("--fixture-dir", default="tests/fixtures/hive")
    sp.add_argument("--output-dir", default="dict_candidates")
    sp.add_argument("--frequency-min", type=int, default=10)
    sp.add_argument("--levenshtein-threshold", type=int, default=3)
    sp.add_argument("--jaccard-threshold", type=float, default=0.6)
    sp.add_argument("--n-items-per-type", type=int, default=None)
    sp.add_argument(
        "--csv-dir", default=None, help="CSV reader directory (for --source csv)"
    )
    sp.add_argument("--csv-delimiter", default=",", help="CSV field delimiter (e.g. ',' '\\t' '|')")
    sp.set_defaults(func=cmd_extract_tags)

    # Stage 2: enrich (实际标注数据)
    sp = sub.add_parser(
        "enrich", help="Stage 2: 实际标注数据 (Hive → item_tags.jsonl)", parents=[parent]
    )
    sp.add_argument("--source", choices=["hive", "mock", "csv"], default="mock")
    sp.add_argument("--fixture-dir", default="tests/fixtures/hive")
    sp.add_argument("--n-items-per-type", type=int, default=None)
    sp.add_argument("--output-dir", type=Path, default=Path("./out"))
    sp.add_argument("--seed", type=int, default=42)
    sp.add_argument(
        "--csv-dir", default=None, help="CSV reader directory (for --source csv)"
    )
    sp.add_argument("--csv-delimiter", default=",", help="CSV field delimiter (e.g. ',' '\\t' '|')")
    sp.add_argument(
        "--dict-snapshot",
        type=Path,
        default=None,
        help="Stage 1 snapshot YAML (constrains LLM output)",
    )
    sp.set_defaults(func=cmd_enrich)

    # Stage 3: sft (合成 SFT 数据)
    sp = sub.add_parser(
        "sft", help="Stage 3: 合成 SFT 语料 (item_tags → sft_corpus.jsonl)", parents=[parent]
    )
    sp.add_argument("--input", type=Path, required=True, help="item_tags.jsonl")
    sp.add_argument("--output-dir", type=Path, default=Path("./out_sft"))
    sp.add_argument("--count-per-item", type=int, default=8)
    sp.add_argument("--max-message-turns", type=int, default=9)
    sp.add_argument("--max-items", type=int, default=None,
                    help="最多处理的 item 数（默认全部）")
    sp.set_defaults(func=cmd_sft)

    # extract-dictionary (legacy alias for extract-tags)
    sp = sub.add_parser(
        "extract-dictionary",
        help="(alias for extract-tags) Stage 1: 全量标签抽取",
        parents=[parent],
    )
    sp.add_argument("--source", choices=["hive", "mock", "csv"], default="mock")
    sp.add_argument("--fixture-dir", default="tests/fixtures/hive")
    sp.add_argument("--output-dir", default="dict_candidates")
    sp.add_argument("--frequency-min", type=int, default=10)
    sp.add_argument("--levenshtein-threshold", type=int, default=3)
    sp.add_argument("--jaccard-threshold", type=float, default=0.6)
    sp.add_argument("--n-items-per-type", type=int, default=None)
    sp.add_argument(
        "--csv-dir", default=None, help="CSV reader directory (for --source csv)"
    )
    sp.add_argument("--csv-delimiter", default=",", help="CSV field delimiter (e.g. ',' '\\t' '|')")
    sp.set_defaults(func=cmd_extract_dictionary)
    sp = sub.add_parser(
        "split",
        help="Split SFT corpus into train/val/test (80/10/10 by item_id md5)",
        parents=[parent],
    )
    sp.add_argument(
        "--input",
        type=Path,
        default=None,
        help="SFT corpus jsonl; default <output-dir>/sft_corpus.jsonl",
    )
    sp.add_argument("--output-dir", type=Path, default=Path("./out_split"))
    sp.set_defaults(func=cmd_split)
    sp = sub.add_parser(
        "generate-synonyms",
        help="dim_dictionary_snapshot → synonyms_solr.txt (LLM-driven, ES retrieval)",
        parents=[parent],
    )
    sp.add_argument(
        "--output-dir", type=Path, default=None, help="output dir for synonyms_solr.txt"
    )
    sp.add_argument(
        "--dict-snapshot", type=Path, default=None,
        help="Stage 1 dim_dictionary_snapshot.yaml path",
    )
    sp.add_argument(
        "--prompt-template", type=Path, default=None,
        help="synonym generation prompt template path",
    )
    sp.set_defaults(func=cmd_generate_synonyms)
    sp = sub.add_parser(
        "verify", help="SC self-check (Stage 1 + Stage 2 + splits)", parents=[parent]
    )
    sp.add_argument("--output-dir", type=Path, default=Path("./out"))
    sp.set_defaults(func=cmd_verify)
    sp = sub.add_parser(
        "all", help="Full pipeline: enrich → sft → split → verify", parents=[parent]
    )
    sp.add_argument("--source", choices=["hive", "mock", "csv"], default="mock")
    sp.add_argument("--fixture-dir", default="tests/fixtures/hive")
    sp.add_argument("--output-dir", type=Path, default=Path("./out_all"))
    sp.add_argument("--n-items-per-type", type=int, default=100)
    sp.add_argument("--seed", type=int, default=42)
    sp.add_argument("--count-per-item", type=int, default=8)
    sp.add_argument("--max-message-turns", type=int, default=6)
    sp.add_argument("--negative-ratio", type=float, default=0.10)
    sp.set_defaults(func=cmd_all)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _resolve_sql_legacy_alias(args)
    configure_logging(args.log_level)
    try:
        return args.func(args)
    except PipelineError as e:
        logger.error("pipeline_failed", extra={"stage": getattr(e, "stage", "?"), "error": str(e)})
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
