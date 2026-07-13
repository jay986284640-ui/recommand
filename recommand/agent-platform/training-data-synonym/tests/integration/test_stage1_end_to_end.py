"""Integration test for Stage 1 end-to-end (T036).

Runs the full enrich pipeline against mock Hive fixtures and verifies
SC-001 / SC-002 / SC-003 self-check.
"""

from __future__ import annotations

import json
from pathlib import Path

from training_data.common.config import Config
from training_data.common.llm_client import MockLLMClient
from training_data.enricher.pipeline import EnrichmentPipeline
from training_data.hive_reader.mock_reader import MockHiveReader


def test_stage1_end_to_end(fixtures_dir: Path, repo_root: Path, tmp_output_dir: Path):
    cfg = Config.load(repo_root / "configs")
    hive = MockHiveReader(fixture_dir=fixtures_dir / "hive")
    llm = MockLLMClient(seed=42)
    pipeline = EnrichmentPipeline(
        config=cfg,
        tables_config_path=repo_root / "configs" / "tables.yaml",
        hive_reader=hive,
        llm_client=llm,
        output_dir=tmp_output_dir,
    )
    summary = pipeline.run()

    # SC-001: 3 core tables must be found
    assert summary.sc_pass.get("SC-001") is True
    # SC-002: dict_pass_rate = 1.0 (mock LLM emits in-vocab values)
    assert summary.dict_pass_rate == 1.0
    # Part B: mock LLM is in-vocab → no rejections
    assert summary.dict_rejected_count == 0
    # Output files exist
    assert (tmp_output_dir / "item_tags.jsonl").exists()
    assert (tmp_output_dir / "tables_meta.json").exists()
    assert (tmp_output_dir / "summary.json").exists()

    # Read item_tags.jsonl and assert sample invariants
    with (tmp_output_dir / "item_tags.jsonl").open() as f:
        rows = [json.loads(l) for l in f if l.strip()]
    assert len(rows) >= 100  # at least 100 across 3 types
    for r in rows:
        assert r["_format_version"] == "item_tags_v2"
        assert r["item_type"] in {"meituan_shop", "self_shop", "coupon"}
        # distance always null at Stage 1
        assert r["tags"]["distance"] is None
        # tag_source.distance ∈ {geo, missing}
        assert r["tag_source"]["distance"] in {"geo", "missing"}


def test_incremental_skips_cached(tmp_output_dir: Path, fixtures_dir: Path, repo_root: Path):
    """Second run on same fixture should produce 0 enriched (all cached)."""
    cfg = Config.load(repo_root / "configs")
    hive = MockHiveReader(fixture_dir=fixtures_dir / "hive")
    llm = MockLLMClient(seed=42)
    pipeline = EnrichmentPipeline(
        config=cfg,
        tables_config_path=repo_root / "configs" / "tables.yaml",
        hive_reader=hive,
        llm_client=llm,
        output_dir=tmp_output_dir,
    )
    summary1 = pipeline.run()
    n1 = summary1.items_enriched

    # Second run
    pipeline2 = EnrichmentPipeline(
        config=cfg,
        tables_config_path=repo_root / "configs" / "tables.yaml",
        hive_reader=MockHiveReader(fixture_dir=fixtures_dir / "hive"),
        llm_client=MockLLMClient(seed=42),
        output_dir=tmp_output_dir,
    )
    summary2 = pipeline2.run()
    assert summary2.items_enriched == 0
    assert summary2.items_skipped_cached == n1