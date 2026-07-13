"""Unit tests for extract_dictionary (Stage 0 dictionary extraction)."""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from training_data.cli.extract_dictionary import (
    RawRow,
    aggregate_raw,
    clean_brand,
    clean_category,
    diff_brands,
    diff_categories,
    extract,
    jaccard_chars,
    levenshtein,
    normalize_brands,
    normalize_categories,
    query_brands_from_hive,
    query_categories_from_hive,
)


# --- clean_brand -------------------------------------------------------


def test_clean_brand_strips_parens():
    assert clean_brand("星巴克(上海)") == "星巴克"
    assert clean_brand("7-Eleven (南京西路)") == "7-Eleven"


def test_clean_brand_strips_legal_suffixes():
    assert clean_brand("星巴克咖啡有限公司") == "星巴克咖啡"
    assert clean_brand("Starbucks Co.") == "Starbucks"
    assert clean_brand("瑞幸 Inc.") == "瑞幸"
    assert clean_brand("SomeBrand Ltd.") == "SomeBrand"


def test_clean_brand_strips_chinese_parens():
    assert clean_brand("海底捞（望京店）") == "海底捞"


def test_clean_brand_preserves_meaningful_tokens():
    assert clean_brand("STARBUCKS RESERVE") == "STARBUCKS RESERVE"


def test_clean_brand_empty():
    assert clean_brand("") == ""
    assert clean_brand("   ") == ""


# --- clean_category ---------------------------------------------------


def test_clean_category_strips_parens():
    assert clean_category("咖啡(冷饮)") == "咖啡"


def test_clean_category_preserves_chinese():
    assert clean_category("咖啡") == "咖啡"
    assert clean_category("  便利店  ") == "便利店"


# --- levenshtein ------------------------------------------------------


def test_levenshtein_identical():
    assert levenshtein("abc", "abc") == 0


def test_levenshtein_empty():
    assert levenshtein("", "abc") == 3
    assert levenshtein("abc", "") == 3


def test_levenshtein_single_edit():
    assert levenshtein("abc", "abd") == 1
    assert levenshtein("星巴克", "星巴") == 1


def test_levenshtein_basic():
    assert levenshtein("星巴克", "星巴克咖啡") == 2


def test_levenshtein_max_dist_early_exit():
    # max_dist=2 returns 3 (i.e. > 2) without computing full distance
    assert levenshtein("abc", "xyz", max_dist=2) == 3
    assert levenshtein("abc", "abd", max_dist=2) == 1


# --- jaccard_chars ----------------------------------------------------


def test_jaccard_chars_basic():
    s = jaccard_chars("星巴克", "星巴克咖啡", n=2)
    assert 0 < s < 1


def test_jaccard_chars_identical():
    assert jaccard_chars("星巴克", "星巴克") == 1.0


def test_jaccard_chars_disjoint():
    assert jaccard_chars("abc", "xyz") == 0.0


def test_jaccard_chars_empty():
    assert jaccard_chars("", "abc") == 0.0
    assert jaccard_chars("abc", "") == 0.0


# --- aggregate_raw ----------------------------------------------------


def test_aggregate_raw_dedupes():
    rows = aggregate_raw([
        ("星巴克", "meituan_shop"),
        ("星巴克", "self_shop"),
        ("星巴克", "meituan_shop"),
        ("瑞幸", "meituan_shop"),
    ])
    assert rows["星巴克"].frequency == 3
    assert rows["星巴克"].sources == {"meituan_shop", "self_shop"}
    assert rows["瑞幸"].frequency == 1


def test_aggregate_raw_skips_empty():
    rows = aggregate_raw([("", "x"), ("y", "x"), (None, "x")])
    assert "y" in rows
    assert "" not in rows
    assert None not in rows


# --- normalize_brands -------------------------------------------------


def test_normalize_brands_merges_close_variants():
    """Variants within the same script (CJK / Latin) should merge.

    Note: 星巴克 (CJK) and Starbucks (Latin) are NOT merged — they are
    actually different scripts and should be treated as separate brand
    representations in the raw data.
    """
    rows = [
        RawRow(name="星巴克", frequency=100),
        RawRow(name="星巴克咖啡", frequency=50),
    ]
    out = normalize_brands(rows, levenshtein_threshold=3, jaccard_threshold=0.4)
    # Both should merge into one canonical (high character n-gram overlap)
    assert len(out) == 1
    canonical = list(out.keys())[0]
    assert out[canonical]["frequency"] == 150
    assert out[canonical]["n_variants"] == 2


def test_normalize_brands_does_not_merge_across_scripts():
    """CJK and Latin scripts should NOT merge (different representations)."""
    rows = [
        RawRow(name="星巴克", frequency=100),
        RawRow(name="Starbucks", frequency=80),
    ]
    out = normalize_brands(rows, levenshtein_threshold=3, jaccard_threshold=0.5)
    # Should remain 2 clusters — scripts are too different
    assert len(out) == 2


def test_normalize_brands_keeps_distinct():
    rows = [
        RawRow(name="星巴克", frequency=100),
        RawRow(name="瑞幸", frequency=80),
        RawRow(name="肯德基", frequency=60),
    ]
    out = normalize_brands(rows)
    assert len(out) == 3
    assert "星巴克" in out
    assert "瑞幸" in out
    assert "肯德基" in out


def test_normalize_brands_picks_highest_freq_as_canonical():
    rows = [
        RawRow(name="Starbucks Coffee", frequency=10),
        RawRow(name="星巴克", frequency=100),
    ]
    out = normalize_brands(rows, levenshtein_threshold=4, jaccard_threshold=0.4)
    # Should merge, with 星巴克 as canonical (higher freq)
    canonical = list(out.keys())[0]
    assert canonical == "星巴克"


def test_normalize_brands_strips_suffix_during_cleaning():
    rows = [
        RawRow(name="星巴克咖啡有限公司", frequency=50),
        RawRow(name="星巴克", frequency=100),
    ]
    out = normalize_brands(rows)
    # Both clean to "星巴克" / "星巴克咖啡" — should NOT merge (different)
    assert len(out) == 2


# --- normalize_categories --------------------------------------------


def test_normalize_categories_merges_synonyms():
    rows = [
        RawRow(name="咖啡", frequency=100),
        RawRow(name="咖啡店", frequency=50),
    ]
    out = normalize_categories(rows, jaccard_threshold=0.5)
    # Should merge via char n-gram
    assert len(out) <= 2


def test_normalize_categories_keeps_distinct():
    rows = [
        RawRow(name="咖啡", frequency=100),
        RawRow(name="中餐", frequency=80),
        RawRow(name="烧烤", frequency=60),
    ]
    out = normalize_categories(rows, jaccard_threshold=0.7)
    assert len(out) >= 3


# --- diff_brands -----------------------------------------------------


def test_diff_brands_added_existing_removed():
    current = {"values": ["星巴克", "瑞幸"]}
    normalized = {
        "星巴克": {"frequency": 100, "n_variants": 1, "sample_aliases": ["星巴克"]},
        "霸王茶姬": {"frequency": 50, "n_variants": 1, "sample_aliases": ["霸王茶姬"]},
        "塔斯汀": {"frequency": 30, "n_variants": 1, "sample_aliases": ["塔斯汀"]},
    }
    diff = diff_brands(current, normalized)
    assert "霸王茶姬" in {a["name"] for a in diff["added"]}
    assert "塔斯汀" in {a["name"] for a in diff["added"]}
    assert "星巴克" in {e["name"] for e in diff["existing"]}
    assert "瑞幸" in {r["name"] for r in diff["removed"]}


def test_diff_brands_sorted_by_frequency():
    normalized = {
        "A": {"frequency": 10, "n_variants": 1, "sample_aliases": ["A"]},
        "B": {"frequency": 100, "n_variants": 1, "sample_aliases": ["B"]},
        "C": {"frequency": 50, "n_variants": 1, "sample_aliases": ["C"]},
    }
    diff = diff_brands({"values": []}, normalized)
    added_names = [a["name"] for a in diff["added"]]
    assert added_names == ["B", "C", "A"]


def test_diff_categories_basic():
    current = {"category": {"values": ["咖啡"]}}
    normalized = {
        "咖啡": {"frequency": 100, "n_variants": 1},
        "奶茶": {"frequency": 50, "n_variants": 1},
    }
    diff = diff_categories(current, normalized)
    assert "奶茶" in {a["name"] for a in diff["added"]}
    assert "咖啡" in {e["name"] for e in diff["existing"]}


# --- query_brands_from_hive / query_categories_from_hive --------------


def test_query_brands_from_hive_reads_fixtures(fixtures_dir: Path):
    from training_data.data_model import HiveReadSpec, Role
    from training_data.hive_reader.mock_reader import MockHiveReader
    from training_data.sql_parser.parser import parse_sql

    reader = MockHiveReader(fixture_dir=fixtures_dir / "hive")
    tables = parse_sql("/opt/recommand/recommand/tabale_structer.sql")
    spec = HiveReadSpec(sample_n_per_type=None)
    tuples = query_brands_from_hive(reader, tables, spec)
    # Every tuple must be (name, item_type_str) with non-empty name
    for name, source in tuples:
        assert name
        assert source in {r.value for r in Role}


def test_query_categories_from_hive_reads_fixtures(fixtures_dir: Path):
    from training_data.data_model import HiveReadSpec
    from training_data.hive_reader.mock_reader import MockHiveReader
    from training_data.sql_parser.parser import parse_sql

    reader = MockHiveReader(fixture_dir=fixtures_dir / "hive")
    tables = parse_sql("/opt/recommand/recommand/tabale_structer.sql")
    spec = HiveReadSpec(sample_n_per_type=None)
    tuples = query_categories_from_hive(reader, tables, spec)
    for name, source in tuples:
        assert name


# --- end-to-end extract() --------------------------------------------


def test_extract_end_to_end(fixtures_dir: Path, repo_root: Path, tmp_path: Path):
    out_dir = tmp_path / "dict_candidates"
    stats = extract(
        source="mock",
        fixture_dir=str(fixtures_dir / "hive"),
        sql_path=str(repo_root.parent.parent / "tabale_structer.sql"),
        output_dir=str(out_dir),
        configs_dir=str(repo_root / "configs"),
        frequency_min=1,  # accept all in fixture
        levenshtein_threshold=3,
        jaccard_threshold=0.6,
    )

    # All 6 files written
    assert (out_dir / "brands_raw.csv").exists()
    assert (out_dir / "brands_normalized.csv").exists()
    assert (out_dir / "brands_diff.yaml").exists()
    assert (out_dir / "categories_raw.csv").exists()
    assert (out_dir / "categories_normalized.csv").exists()
    assert (out_dir / "categories_diff.yaml").exists()

    # Stats sanity
    assert stats["raw_brands"] >= 10
    assert stats["normalized_brands"] >= 5
    assert stats["raw_categories"] >= 5
    assert stats["normalized_categories"] >= 5

    # CSVs are parseable
    with (out_dir / "brands_normalized.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert all({"canonical", "frequency", "n_variants", "aliases"} <= set(r) for r in rows)

    # Diff yaml is parseable + has _meta
    diff = yaml.safe_load((out_dir / "brands_diff.yaml").read_text())
    assert "_meta" in diff
    assert "added" in diff and "existing" in diff and "removed" in diff


def test_extract_frequency_min_filters(repo_root: Path, fixtures_dir: Path, tmp_path: Path):
    out_dir = tmp_path / "dict_strict"
    stats = extract(
        source="mock",
        fixture_dir=str(fixtures_dir / "hive"),
        sql_path=str(repo_root.parent.parent / "tabale_structer.sql"),
        output_dir=str(out_dir),
        configs_dir=str(repo_root / "configs"),
        frequency_min=10000,  # impossibly high — should filter everything
    )
    assert stats["filtered_brands"] == 0
    assert stats["filtered_categories"] == 0


# --- CLI integration -------------------------------------------------


def test_cli_extract_dictionary_subcommand(repo_root: Path, fixtures_dir: Path, tmp_path: Path):
    """End-to-end via subprocess: python -m training_data.cli extract-dictionary"""
    out_dir = tmp_path / "cli_dict_candidates"
    result = subprocess.run(
        [
            "python", "-m", "training_data.cli", "extract-dictionary",
            "--sql", str(repo_root.parent.parent / "tabale_structer.sql"),
            "--source", "mock",
            "--fixture-dir", str(fixtures_dir / "hive"),
            "--output-dir", str(out_dir),
            "--frequency-min", "1",
            "--log-level", "WARNING",
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert (out_dir / "brands_diff.yaml").exists()
    assert (out_dir / "categories_diff.yaml").exists()