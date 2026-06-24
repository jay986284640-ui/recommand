"""Top-level CLI for training-data-synonym (per Constitution Principle II).

Subcommands:
  tables-meta  — SQL → tables_meta.json only
  enrich       — Stage 1: Hive → item_tags.jsonl
  sft          — Stage 2: item_tags → sft_corpus.jsonl
  split        — sft_corpus → train/val/test (Phase 5)
  verify       — summary.json → SC pass/fail report (Phase 5)
  all          — full pipeline (enrich → sft → split → verify) (Phase 5)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from ..common.config import Config
from ..common.exceptions import PipelineError
from ..common.llm_client import LLMClient
from ..common.logging import configure_logging, get_logger
from ..hive_reader.base import HiveReadSpec
from ..hive_reader.mock_reader import MockHiveReader
from ..enricher.pipeline import EnrichmentPipeline

logger = get_logger(__name__)


def _build_hive_reader(args, configs_dir: Path):
    if args.source == "mock":
        return MockHiveReader(
            fixture_dir=configs_dir / "tests" / "fixtures" / "hive"
            if False  # placeholder; resolve from --fixture-dir or default
            else Path(args.fixture_dir or "tests/fixtures/hive")
        )
    raise NotImplementedError(
        "Production Hive readers (SparkHiveReader / PyHiveReader) "
        "require environment wiring; use --source=mock in CI."
    )


def cmd_tables_meta(args) -> int:
    from ..sql_parser.parser import parse_sql
    tables = parse_sql(args.sql)
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


def cmd_enrich(args) -> int:
    cfg = Config.load(args.configs_dir)
    hive = _build_hive_reader(args, Path(args.configs_dir))
    from ..common.llm_client import MockLLMClient
    llm: LLMClient = MockLLMClient(seed=getattr(args, "seed", 42))
    pipeline = EnrichmentPipeline(
        config=cfg,
        sql_path=args.sql,
        hive_reader=hive,
        llm_client=llm,
        output_dir=args.output_dir,
    )
    summary = pipeline.run()
    # Write summary.json
    summary_path = Path(args.output_dir) / "summary.json"
    summary_path.write_text(
        json.dumps(summary.__dict__, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Stage 1 complete: {summary.items_enriched} items enriched, "
          f"{summary.items_cold_start} cold-start, "
          f"{summary.items_skipped_cached} cached skipped")
    print(f"  llm_calls={summary.llm_calls}, coverage_avg={summary.coverage_avg:.2f}")
    print(f"  SC pass: {summary.sc_pass}")
    print(f"  summary → {summary_path}")
    return 0 if all(summary.sc_pass.values()) else 1


def cmd_extract_dictionary(args) -> int:
    """Stage 0 dictionary candidate extraction (offline tool).

    Independent CLI — does NOT touch authoritative configs.
    Writes candidate files under args.output_dir for human review.
    """
    from .extract_dictionary import extract
    stats = extract(
        source=args.source,
        fixture_dir=args.fixture_dir,
        sql_path=args.sql,
        output_dir=args.output_dir,
        configs_dir=args.configs_dir,
        frequency_min=args.frequency_min,
        levenshtein_threshold=args.levenshtein_threshold,
        jaccard_threshold=args.jaccard_threshold,
        sample_n_per_type=args.n_items_per_type,
    )
    print("Stage 0 extract-dictionary complete:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"\nReview {args.output_dir}/brands_diff.yaml for candidates to promote.")
    return 0


def cmd_sft(args) -> int:
    cfg = Config.load(args.configs_dir)
    from ..common.llm_client import MockLLMClient
    llm = MockLLMClient(seed=getattr(args, "seed", 42))
    from ..sft.pipeline import SFTPipeline
    pipeline = SFTPipeline(
        config=cfg,
        llm_client=llm,
        input_path=args.input,
        output_dir=args.output_dir,
        count_per_item=getattr(args, "count_per_item", 8),
        max_message_turns=getattr(args, "max_message_turns", 5),
        negative_ratio=getattr(args, "negative_ratio", 0.10),
    )
    summary = pipeline.run()
    print(f"Stage 2 complete: {summary.total} samples, "
          f"{summary.sft_failures} failures, "
          f"{summary.forced_coverage_count} forced_coverage")
    print(f"  intent_distribution: {summary.intent_distribution}")
    print(f"  coverage_pass: {summary.coverage_pass}")
    return 0 if (summary.coverage_pass and summary.sft_failures == 0) else 1


def cmd_split(args) -> int:
    raise NotImplementedError("split is implemented in Phase 5; "
                              "see specs/tasks.md T073-T089")


def cmd_verify(args) -> int:
    raise NotImplementedError("verify is implemented in Phase 5; "
                              "see specs/tasks.md T073-T089")


def cmd_all(args) -> int:
    raise NotImplementedError("`all` is implemented in Phase 5; "
                              "see specs/tasks.md T073-T089")


def build_parser() -> argparse.ArgumentParser:
    # Shared parent parser — global flags attached to every subcommand.
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--sql", default="/opt/recommand/recommand/tabale_structer.sql")
    parent.add_argument("--configs-dir", default="configs")
    parent.add_argument("--log-level", default="INFO")

    p = argparse.ArgumentParser(
        prog="training-data-synonym",
        description="兴业 O2O 三品类 SFT 语料生成流水线 (Hive + 8 维 + 5 轮对话)",
        parents=[parent],
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # tables-meta
    sp = sub.add_parser("tables-meta", help="Parse SQL → tables_meta.json", parents=[parent])
    sp.add_argument("--output", type=Path, default=Path("tables_meta.json"))
    sp.set_defaults(func=cmd_tables_meta)

    # enrich
    sp = sub.add_parser("enrich", help="Stage 1: Hive → item_tags.jsonl", parents=[parent])
    sp.add_argument("--source", choices=["hive", "mock"], default="mock")
    sp.add_argument("--fixture-dir", default="tests/fixtures/hive")
    sp.add_argument("--n-items-per-type", type=int, default=100)
    sp.add_argument("--output-dir", type=Path, default=Path("./out"))
    sp.add_argument("--seed", type=int, default=42)
    sp.set_defaults(func=cmd_enrich)

    # sft / split / verify / all (Phase 4 / 5)
    sp = sub.add_parser("sft", help="Stage 2: item_tags → sft_corpus.jsonl (Phase 4)", parents=[parent])
    sp.add_argument("--input", type=Path, required=True, help="item_tags.jsonl from Stage 1")
    sp.add_argument("--output-dir", type=Path, default=Path("./out_sft"))
    sp.add_argument("--count-per-item", type=int, default=8)
    sp.add_argument("--max-message-turns", type=int, default=5)
    sp.add_argument("--negative-ratio", type=float, default=0.10)
    sp.add_argument("--seed", type=int, default=42)
    sp.set_defaults(func=cmd_sft)

    # extract-dictionary (Stage 0, offline)
    sp = sub.add_parser(
        "extract-dictionary",
        help="Stage 0: extract brand/category candidates from Hive (offline tool)",
        parents=[parent],
    )
    sp.add_argument("--source", choices=["hive", "mock"], default="mock")
    sp.add_argument("--fixture-dir", default="tests/fixtures/hive")
    sp.add_argument("--output-dir", default="dict_candidates")
    sp.add_argument("--frequency-min", type=int, default=10)
    sp.add_argument("--levenshtein-threshold", type=int, default=3)
    sp.add_argument("--jaccard-threshold", type=float, default=0.6)
    sp.add_argument("--n-items-per-type", type=int, default=None)
    sp.set_defaults(func=cmd_extract_dictionary)
    sp = sub.add_parser("split", help="train/val/test split (Phase 5)", parents=[parent])
    sp.set_defaults(func=cmd_split)
    sp = sub.add_parser("verify", help="SC self-check (Phase 5)", parents=[parent])
    sp.set_defaults(func=cmd_verify)
    sp = sub.add_parser("all", help="Full pipeline (Phase 5)", parents=[parent])
    sp.set_defaults(func=cmd_all)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    try:
        return args.func(args)
    except PipelineError as e:
        logger.error("pipeline_failed", extra={"stage": getattr(e, "stage", "?"), "error": str(e)})
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())