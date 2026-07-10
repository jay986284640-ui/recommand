# -*- coding: utf-8 -*-
"""xingye_coupon_csv 适配器 + 运营行为检测器/打标 单元测试

不依赖真实 CSV,通过 monkey-patch _read_csv 注入内存 df。
运行:
    cd agent-platform/data-pipeline
    pytest tests/test_xingye_coupon_csv_adapter.py -v
"""

import pytest
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, LongType, DoubleType,
)

from adapters.xingye_coupon_csv import XingyeCouponCsvAdapter
from data_analysis.analyzer.item_time_burst import ItemTimeBurstAnalyzer
from data_analysis.analyzer.item_popularity_anomaly import ItemPopularityAnomalyAnalyzer
from data_analysis.analyzer.user_velocity_anomaly import UserVelocityAnomalyAnalyzer
from data_analysis.analyzer.item_funnel_stats import ItemFunnelStatsAnalyzer
from data_analysis.analyzer import campaign_scorer


# ----------------------------------------------------------------- fixtures


@pytest.fixture
def csv_config():
    return {
        "items_path": "/fake/item_profile.csv",
        "interactions_path": "/fake/user_seq.csv",
        "time_format": "s",
        "btn_action_mapping": {"收藏": "favorite", "领取": "receive"},
        "default_click_action": "click",
    }


@pytest.fixture
def fake_csv(spark):
    items_df = spark.createDataFrame(
        [
            ("100", "星巴克", "coupon", "上海市", "浦东", "121.5", "31.2", "咖啡"),
            ("200", "麦当劳", "coupon", "上海市", "徐汇", "121.4", "31.1", "快餐"),
        ],
        ["item_id", "item_nm", "type", "city_nm", "cnty_nm", "lon", "lat", "cat_nm1"],
    )
    # event: showPage / Click;Click 的行为看 btn_nm
    inter_schema = StructType([
        StructField("custref_no", StringType(), True),
        StructField("event", StringType(), True),
        StructField("event_time", LongType(), True),
        StructField("item_id", StringType(), True),
        StructField("lat", DoubleType(), True),
        StructField("lon", DoubleType(), True),
        StructField("btn_nm", StringType(), True),
        StructField("cls_info", StringType(), True),
    ])
    inter_df = spark.createDataFrame(
        [
            ("u1", "showPage", 1_700_000_000, "100", 31.2, 121.5, None, None),
            ("u1", "Click", 1_700_000_050, "100", 31.2, 121.5, "收藏", None),
            ("u2", "Click", 1_700_000_060, "100", 31.2, 121.5, "领取", None),
            ("u2", "Click", 1_700_000_070, "100", 31.2, 121.5, "未知按钮", None),
            ("u3", "showPage", 1_700_000_080, "200", 31.1, 121.4, None, None),
            (None, "showPage", 1_700_000_090, "200", 31.1, 121.4, None, None),  # 空用户
        ],
        inter_schema,
    )
    return {"/fake/item_profile.csv": items_df, "/fake/user_seq.csv": inter_df}


@pytest.fixture
def adapter(spark, csv_config, fake_csv, monkeypatch):
    def fake_read(self, path):
        return fake_csv[path].cache()

    monkeypatch.setattr(XingyeCouponCsvAdapter, "_read_csv", fake_read)
    return XingyeCouponCsvAdapter(spark, csv_config)


# ---------------------------------------------------------------- load_items


class TestLoadItems:
    def test_item_id_and_geo_renamed(self, adapter):
        i = adapter.load_items()
        assert "item_id" in i.columns
        assert "item_title" in i.columns
        assert "item_lon" in i.columns and "item_lat" in i.columns
        assert "lon" not in i.columns and "lat" not in i.columns
        assert dict(i.dtypes)["item_lat"] == "double"
        assert i.count() == 2


# ----------------------------------------------------------- load_interactions


class TestLoadInteractions:
    def test_columns_present(self, adapter):
        inter = adapter.load_interactions()
        for c in ("user_id", "item_id", "timestamp", "action", "event", "btn_nm", "user_lat", "user_lon"):
            assert c in inter.columns
        assert dict(inter.dtypes)["timestamp"] == "bigint"

    def test_action_derived_from_event_and_btn(self, adapter):
        inter = adapter.load_interactions()
        rows = {(r["user_id"], r["timestamp"]): r["action"] for r in inter.collect()}
        assert rows[("u1", 1_700_000_000)] == "impression"   # showPage
        assert rows[("u1", 1_700_000_050)] == "favorite"     # Click + 收藏
        assert rows[("u2", 1_700_000_060)] == "receive"      # Click + 领取
        assert rows[("u2", 1_700_000_070)] == "click"        # Click + 未知按钮 → 兜底

    def test_empty_user_filtered(self, adapter):
        inter = adapter.load_interactions()
        assert inter.filter("user_id IS NULL OR user_id = ''").count() == 0

    def test_seconds_passthrough(self, adapter):
        inter = adapter.load_interactions()
        ts = inter.orderBy("timestamp").first()["timestamp"]
        assert ts == 1_700_000_000


# --------------------------------------------------------------- 检测器


class TestDetectors:
    def test_time_burst_flags_spiky_item(self, spark):
        # b1: 200 条集中在同一小时;b2: 均匀分散 20 天
        base = 1_700_000_000
        burst = [("u%d" % i, "b1", base + i) for i in range(200)]
        spread = [("u%d" % i, "b2", base + i * 86400) for i in range(20)]
        df = spark.createDataFrame(
            burst + spread, ["user_id", "item_id", "timestamp"]
        ).withColumn("action", F.lit("impression"))
        cfg = {"bucket": "hour", "spike_ratio_threshold": 5.0,
               "min_burst_count": 50, "top_bucket_share_threshold": 0.5}
        res = {r["item_id"]: r["flag_burst"]
               for r in ItemTimeBurstAnalyzer(spark, cfg, "/tmp").analyze(df).collect()}
        assert res["b1"] is True
        assert res["b2"] is False

    def test_popularity_flags_hot_item(self, spark):
        base = 1_700_000_000
        hot = [("u1", "h1", base + i) for i in range(300)]      # 1 用户 300 次 → ratio 高
        normal = [("u%d" % i, "n1", base + i) for i in range(10)]
        df = spark.createDataFrame(hot + normal, ["user_id", "item_id", "timestamp"]) \
            .withColumn("action", F.lit("impression"))
        cfg = {"popularity_pct": 0.99, "min_interactions_for_hot": 1000,
               "interaction_per_user_threshold": 3.0}
        res = {r["item_id"]: r["flag_popularity"]
               for r in ItemPopularityAnomalyAnalyzer(spark, cfg, "/tmp").analyze(df).collect()}
        assert res["h1"] is True   # 交互/用户比 = 300 >> 3
        assert res["n1"] is False

    def test_user_velocity_flags_hyperactive(self, spark):
        base = 1_700_000_000
        hyper = [("bot", "i%d" % i, base + i) for i in range(120)]  # 同小时 120 次
        calm = [("human", "i%d" % i, base + i * 86400) for i in range(5)]
        df = spark.createDataFrame(hyper + calm, ["user_id", "item_id", "timestamp"]) \
            .withColumn("action", F.lit("impression"))
        cfg = {"max_daily_threshold": 100, "max_hourly_threshold": 50}
        res = {r["user_id"]: r["flag_user_velocity"]
               for r in UserVelocityAnomalyAnalyzer(spark, cfg, "/tmp").analyze(df).collect()}
        assert res["bot"] is True
        assert res["human"] is False

    def test_scorer_marks_campaign_item(self, spark):
        base = 1_700_000_000
        burst = [("u%d" % i, "b1", base + i) for i in range(200)]
        spread = [("u%d" % i, "b2", base + i * 86400) for i in range(20)]
        df = spark.createDataFrame(burst + spread, ["user_id", "item_id", "timestamp"]) \
            .withColumn("action", F.lit("impression"))
        burst_res = ItemTimeBurstAnalyzer(
            spark, {"bucket": "hour", "min_burst_count": 50}, "/tmp"
        ).analyze(df)
        flags = campaign_scorer.score_items({"item_time_burst": burst_res}, min_score=1)
        d = {r["item_id"]: r["is_campaign_item"] for r in flags.collect()}
        assert d["b1"] is True
        assert d["b2"] is False
