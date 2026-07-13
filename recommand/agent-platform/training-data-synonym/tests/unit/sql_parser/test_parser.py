"""Unit tests for SQL parser role inference (T029)."""

from __future__ import annotations

from training_data.data_model import Role
from training_data.sql_parser.parser import parse_sql, role_from_tablename


def test_role_inference_rules():
    assert role_from_tablename("o2o_new_gut_shop_base_third") == Role.MEITUAN_SHOP
    assert role_from_tablename("o2o_new_gut_shop_base") == Role.SELF_SHOP
    assert role_from_tablename("o2o_new_gut_coupon_template") == Role.COUPON
    assert role_from_tablename("o2o_new_gut_shop_address") == Role.ADDRESS
    assert role_from_tablename("o2o_new_gut_shop_category_meituan") == Role.CATEGORY
    assert role_from_tablename("o2o_new_gut_shop_category_mapping") == Role.CATEGORY
    assert role_from_tablename("o2o_new_gut_coupon_shop") == Role.COUPON_SHOP
    assert role_from_tablename("o2o_new_gut_discounts_pay") == Role.DISCOUNT
    assert role_from_tablename("CDM_ADM_CUST_INFO_STAT_F") == Role.CUSTOMER
    assert role_from_tablename("c10_ods_events_xysh") == Role.EVENTS
    assert role_from_tablename("unknown_table_xyz") == Role.UNKNOWN


def test_parse_tabale_structer_sql():
    tables = parse_sql("/opt/recommand/recommand/tabale_structer.sql")
    assert len(tables) >= 10  # at least the 10 main tables

    by_name = {t.table_name: t for t in tables}
    assert "o2o_new_gut_shop_base_third" in by_name
    mt = by_name["o2o_new_gut_shop_base_third"]
    assert mt.db == "recommand_workspace"
    assert mt.inferred_role == Role.MEITUAN_SHOP
    # Columns include Lng / Lat
    col_names = {c.name for c in mt.columns}
    assert "lng" in col_names
    assert "lat" in col_names


def test_partition_keys_extracted():
    tables = parse_sql("/opt/recommand/recommand/tabale_structer.sql")
    by_name = {t.table_name: t for t in tables}
    mt = by_name["o2o_new_gut_shop_base_third"]
    assert "etl_dt" in mt.partition_keys


def test_no_duplicate_tables():
    tables = parse_sql("/opt/recommand/recommand/tabale_structer.sql")
    keys = [(t.db, t.table_name) for t in tables]
    assert len(keys) == len(set(keys))