"""5 类特征提取的单元测试"""

import pytest
from pyspark.sql.types import StructType, StructField, StringType, LongType, IntegerType, DoubleType

from feature_extraction import (
    extract_item_features,
    extract_user_features,
    build_user_interaction_history,
    build_co_purchase,
    build_impression_log_stub,
)


def _items(spark):
    schema = "item_id STRING, content_type STRING, category STRING"
    return spark.createDataFrame(
        [
            ("i1", "meituan_coupon", "咖啡"),
            ("i2", "meituan_coupon", "咖啡"),
            ("i3", "self_operated_coupon", "奶茶"),
            ("i4", "external_coupon", "咖啡"),
        ],
        schema,
    )


def _users(spark):
    return spark.createDataFrame(
        [("u1", "Alice"), ("u2", "Bob"), ("u3", "Charlie")],
        "user_id STRING, name STRING",
    )


def _inter(spark):
    schema = StructType([
        StructField("user_id", StringType()),
        StructField("item_id", StringType()),
        StructField("timestamp", LongType()),
        StructField("action", StringType()),
    ])
    return spark.createDataFrame(
        [
            ("u1", "i1", 1000, "buy"),
            ("u1", "i2", 2000, "buy"),
            ("u2", "i1", 3000, "use"),
            ("u2", "i3", 4000, "buy"),
            ("u3", "i4", 5000, "buy"),
        ],
        schema,
    )


def test_extract_item_features_marks_cold(spark):
    inter = _inter(spark)
    items = _items(spark)
    out = extract_item_features(items, inter, cold_threshold=3)
    rows = {r["item_id"]: r for r in out.collect()}
    assert rows["i1"]["interaction_count"] == 2
    assert rows["i1"]["is_cold"] is True
    assert rows["i3"]["is_cold"] is True
    # i1 被 2 个 user 买过
    assert rows["i1"]["buyer_count"] == 2


def test_extract_user_features_computes_prefs(spark):
    users = _users(spark)
    items = _items(spark)
    inter = _inter(spark)
    out = extract_user_features(users, inter, items, new_user_threshold=10)
    rows = {r["user_id"]: r for r in out.collect()}
    # u1 主要买咖啡类(2 次),u2 咖啡 1 次 + 奶茶 1 次
    assert "咖啡" in rows["u1"]["category_pref"]
    assert rows["u1"]["is_new_user"] is False
    assert rows["u3"]["is_new_user"] is True  # 只 1 次


def test_build_user_interaction_history_orders_by_ts(spark):
    inter = _inter(spark)
    out = build_user_interaction_history(inter, max_seq_length=10)
    row = out.filter("user_id = 'u1'").first()
    seq = row["sequence"]
    # 序列应按 timestamp 升序
    assert [s["timestamp"] for s in seq] == [1000, 2000]
    assert row["seq_length"] == 2


def test_build_user_interaction_history_truncates(spark):
    inter = _inter(spark)
    out = build_user_interaction_history(inter, max_seq_length=1)
    row = out.filter("user_id = 'u1'").first()
    assert row["seq_length"] == 1
    assert row["sequence"][0]["timestamp"] == 1000


def test_build_co_purchase_pairs_within_window(spark):
    inter = _inter(spark)
    out = build_co_purchase(inter, window_days=30)
    # i1 应该与 i2 共购(都是 u1)
    rows = {r["item_id"]: r for r in out.collect()}
    assert "i1" in rows
    related = {x["related_item_id"] for x in rows["i1"]["co_items"]}
    assert "i2" in related
    # 权重应该是 float
    weight = rows["i1"]["co_items"][0]["co_weight"]
    assert isinstance(weight, float) or hasattr(weight, "as_py")
    assert float(weight) > 0


def test_build_impression_log_stub_returns_empty_with_schema(spark):
    df = build_impression_log_stub(spark)
    # 字段名应符合约定
    expected = {"trace_id", "user_id", "session_id", "item_id", "content_type",
                "position", "rank_method", "impression_ts", "is_click", "is_convert"}
    assert set(df.columns) == expected
    assert df.count() == 0
