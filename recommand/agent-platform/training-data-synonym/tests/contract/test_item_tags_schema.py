"""Contract test for item_tags_v2 schema (per contracts/item_tags_v2.md).

Verifies:
- _format_version == item_tags_v2
- 8-dim tag field order (DIM_ORDER)
- tag_source 3-family enum restrictions
- `tag == None ⇔ source == missing` invariant for non-distance dims
- distance tag always null at Stage 1; source ∈ {geo, missing} only
- sensitive columns absent from raw_record
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from training_data_synonym.common.versioning import ITEM_TAGS_V
from training_data_synonym.data_model import DIM_ORDER


SENSITIVE_COLUMNS = [
    "MASTERCARD_CUST_ID",
    "Crt_Psn_Id",
    "Updt_Psn_Id",
    "Opr_Psn_Id",
    "creator",
    "updatePerson",
]


@pytest.fixture
def tags_path(repo_root: Path, tmp_output_dir: Path) -> Path:
    """Run a small enrich to materialize item_tags.jsonl (CI / mock LLM only)."""
    import subprocess
    result = subprocess.run(
        [
            "python", "-m", "training_data_synonym.cli", "enrich",
            "--tables-config", str(repo_root / "configs" / "tables.yaml"),
            "--source", "mock",
            "--fixture-dir", str(repo_root / "tests/fixtures/hive"),
            "--output-dir", str(tmp_output_dir),
            "--log-level", "WARNING",
        ],
        check=False, capture_output=True, text=True,
    )
    # Note: we don't assert returncode==0 because mock LLM is intentionally
    # noisy and SC-003 may fail (coverage_avg depends on random mock output).
    # We only care about the artifact being produced.
    assert (tmp_output_dir / "item_tags.jsonl").exists(), (
        f"enrich produced no item_tags.jsonl: {result.stderr}"
    )
    return tmp_output_dir / "item_tags.jsonl"


def test_format_version(tags_path: Path):
    with tags_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            assert rec["_format_version"] == ITEM_TAGS_V
            break


def test_tags_field_order(tags_path: Path):
    with tags_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            assert list(rec["tags"].keys()) == list(DIM_ORDER)
            break


def test_distance_source_enum(tags_path: Path):
    """tag_source.distance ∈ {geo, missing} ONLY."""
    allowed = {"geo", "missing"}
    with tags_path.open() as f:
        for line in f:
            rec = json.loads(line)
            assert rec["tag_source"]["distance"] in allowed


def test_distance_value_always_null(tags_path: Path):
    """tags.distance is always None at Stage 1 (per spec v2.4 FR-008b)."""
    with tags_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            assert rec["tags"]["distance"] is None


def test_consumable_type_source_enum(tags_path: Path):
    """tag_source.consumable_type ∈ {derived, ai, missing} ONLY."""
    allowed = {"derived", "ai", "missing"}
    with tags_path.open() as f:
        for line in f:
            rec = json.loads(line)
            assert rec["tag_source"]["consumable_type"] in allowed


def test_other_dims_source_enum(tags_path: Path):
    """Non-{distance, consumable_type} dims ∈ {raw, ai, missing}."""
    allowed = {"raw", "ai", "missing"}
    other_dims = [d for d in DIM_ORDER if d not in ("distance", "consumable_type")]
    with tags_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            for d in other_dims:
                assert rec["tag_source"][d] in allowed, f"{d} has bad source"


def test_invariant_non_distance(tags_path: Path):
    """For non-distance dims: tag == None ⇔ source == missing."""
    other_dims = [d for d in DIM_ORDER if d != "distance"]
    with tags_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            for d in other_dims:
                tag_null = rec["tags"][d] is None
                src_missing = rec["tag_source"][d] == "missing"
                assert tag_null == src_missing, f"{d} invariant violated: tag={rec['tags'][d]}, src={rec['tag_source'][d]}"


def test_no_sensitive_columns(tags_path: Path):
    """raw_record must NOT contain any sensitive column from blocklist."""
    with tags_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            for col in SENSITIVE_COLUMNS:
                assert col not in rec["raw_record"], f"sensitive '{col}' leaked into {rec['item_id']}"


def test_item_type_set(tags_path: Path):
    """item_type ∈ {meituan_shop, self_shop, coupon} for Stage 1."""
    allowed = {"meituan_shop", "self_shop", "coupon"}
    with tags_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            assert rec["item_type"] in allowed