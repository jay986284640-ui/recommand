"""Unit tests for MockHiveReader behavior (T030)."""

from __future__ import annotations

from training_data_synonym.data_model import HiveReadSpec
from training_data_synonym.hive_reader.mock_reader import MockHiveReader
from training_data_synonym.sql_parser.parser import parse_sql


def test_default_etl_dt_partition(fixtures_dir):
    reader = MockHiveReader(fixture_dir=fixtures_dir / "hive")
    tables = parse_sql("/opt/recommand/recommand/tabale_structer.sql")
    mt = next(t for t in tables if t.table_name == "o2o_new_gut_shop_base_third")
    assert reader.list_partitions(mt) == ["20260620"]


def test_sensitive_columns_dropped(fixtures_dir):
    reader = MockHiveReader(fixture_dir=fixtures_dir / "hive")
    tables = parse_sql("/opt/recommand/recommand/tabale_structer.sql")
    mt = next(t for t in tables if t.table_name == "o2o_new_gut_shop_base_third")
    spec = HiveReadSpec(sample_n_per_type=20)
    for rec in reader.read(mt, spec):
        assert "Crt_Psn_Id" not in rec.raw
        assert "Opr_Psn_Id" not in rec.raw


def test_sample_truncation(fixtures_dir):
    reader = MockHiveReader(fixture_dir=fixtures_dir / "hive")
    tables = parse_sql("/opt/recommand/recommand/tabale_structer.sql")
    mt = next(t for t in tables if t.table_name == "o2o_new_gut_shop_base_third")
    rows_5 = list(reader.read(mt, HiveReadSpec(sample_n_per_type=5)))
    assert len(rows_5) == 5
    rows_full = list(reader.read(mt, HiveReadSpec(sample_n_per_type=None)))
    assert len(rows_full) == 100


def test_invalid_source_raises(fixtures_dir):
    import pytest
    reader = MockHiveReader(fixture_dir=fixtures_dir / "hive")
    tables = parse_sql("/opt/recommand/recommand/tabale_structer.sql")
    mt = next(t for t in tables if t.table_name == "o2o_new_gut_shop_base_third")
    with pytest.raises(ValueError):
        list(reader.read(mt, HiveReadSpec(etl_dt_mode="invalid_mode")))