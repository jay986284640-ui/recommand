"""audit 步骤的指标单元测试"""

import pytest
from pyspark.sql.types import StructType, StructField, StringType, LongType, DoubleType

from audit import metrics


def _inter_df(spark):
    schema = StructType([
        StructField("user_id", StringType()),
        StructField("item_id", StringType()),
        StructField("timestamp", LongType()),
        StructField("rating", DoubleType()),
    ])
    data = [
        ("u1", "i1", 1000, 5.0),
        ("u2", "i1", 2000, 4.0),
        ("u1", "i2", 3000, 3.0),
        (None, "i3", 4000, 5.0),  # 主键缺
        ("u3", "i1", 5000, None),  # rating 缺
    ]
    return spark.createDataFrame(data, schema)


def test_row_count(spark):
    df = _inter_df(spark)
    res = metrics.row_count(df)
    assert res["row_count"] == 5
    assert "user_id" in res["columns"]


def test_field_completeness(spark):
    df = _inter_df(spark)
    res = metrics.field_completeness(df, ["user_id", "rating"])
    assert res["user_id"]["non_null_count"] == 4
    assert res["rating"]["non_null_count"] == 4


def test_primary_key_uniqueness(spark):
    df = _inter_df(spark)
    res = metrics.primary_key_uniqueness(df, ["user_id"])
    assert res["user_id"]["duplicates"] >= 1  # u1 出现多次


def test_time_range(spark):
    df = _inter_df(spark)
    res = metrics.time_range(df, "timestamp")
    assert res["min_timestamp"] == 1000
    assert res["max_timestamp"] == 5000


def test_outlier_check(spark):
    df = _inter_df(spark)
    res = metrics.outlier_check(df, [{"field": "rating", "min": 1.0, "max": 5.0}])
    assert res["rating"]["outlier_count"] == 0
    res2 = metrics.outlier_check(df, [{"field": "rating", "min": 4.0, "max": 5.0}])
    assert res2["rating"]["outlier_count"] >= 1  # 3.0 算异常
