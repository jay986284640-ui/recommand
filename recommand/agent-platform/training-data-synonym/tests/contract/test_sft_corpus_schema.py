"""Contract test for sft_corpus_v2 schema (T050)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from training_data_synonym.common.versioning import SFT_CORPUS_V
from training_data_synonym.data_model import DIM_ORDER


@pytest.fixture
def sft_path(repo_root: Path, tmp_output_dir: Path) -> Path:
    import subprocess
    # Run Stage 1 first
    r1 = subprocess.run(
        [
            "python", "-m", "training_data_synonym.cli", "enrich",
            "--sql", str(repo_root.parent.parent / "tabale_structer.sql"),
            "--source", "mock",
            "--fixture-dir", str(repo_root / "tests/fixtures/hive"),
            "--output-dir", str(tmp_output_dir),
            "--log-level", "WARNING",
        ],
        check=False, capture_output=True, text=True,
    )
    # Run Stage 2
    r2 = subprocess.run(
        [
            "python", "-m", "training_data_synonym.cli", "sft",
            "--input", str(tmp_output_dir / "item_tags.jsonl"),
            "--output-dir", str(tmp_output_dir),
            "--count-per-item", "4",
            "--log-level", "WARNING",
        ],
        check=False, capture_output=True, text=True,
    )
    assert r2.returncode == 0, f"sft failed: {r2.stderr}"
    return tmp_output_dir / "sft_corpus.jsonl"


def test_format_version(sft_path: Path):
    with sft_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            assert rec["_format_version"] == SFT_CORPUS_V
            break


def test_params_field_order(sft_path: Path):
    with sft_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            assert list(rec["params"].keys()) == list(DIM_ORDER)
            break


def test_intent_in_set(sft_path: Path):
    allowed = {"search_item", "use_coupon", "pay", "view_order", "browse"}
    with sft_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            assert rec["intent"] in allowed


def test_order_by_in_set(sft_path: Path):
    allowed = {None, "distance", "price", "rating", "time"}
    with sft_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            assert rec["order_by"] in allowed


def test_messages_length_1_to_5(sft_path: Path):
    with sft_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            assert 1 <= len(rec["messages"]) <= 5


def test_messages_first_user(sft_path: Path):
    with sft_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            assert rec["messages"][0]["role"] == "user"


def test_negative_consistency(sft_path: Path):
    with sft_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec["negative"]:
                assert rec["negative_type"] in {"reject", "pivot", "unsatisfiable"}
            else:
                assert rec["negative_type"] is None


def test_param_op_in_4_set(sft_path: Path):
    allowed = {"eq", "in", "contains", "not_in"}
    with sft_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            for dim, spec in rec["params"].items():
                if spec is not None:
                    assert spec["op"] in allowed, f"{dim}.op '{spec['op']}' not in {allowed}"


def test_consumable_type_op_must_be_eq(sft_path: Path):
    """consumable_type is op=eq, values ∈ {food, drink, mixed, none}."""
    allowed_vals = {"food", "drink", "mixed", "none"}
    with sft_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            ct = rec["params"]["consumable_type"]
            if ct is not None:
                assert ct["op"] == "eq"
                assert ct["values"] in allowed_vals


def test_item_id_format(sft_path: Path):
    with sft_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            assert rec["item_id"].startswith(("mt-", "self-", "cpn-"))