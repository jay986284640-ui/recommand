# -*- coding: utf-8 -*-
"""xingye_coupon 适配器单元测试

不依赖 Hive metastore,通过 monkey-patch _read_hive 注入内存 df。
运行:
    cd agent-platform/data-pipeline
    pytest tests/test_xingye_coupon_adapter.py -v
"""

import time as _time

import pytest
from pyspark.sql.types import StructType, StructField, StringType, LongType

from adapters.xingye_coupon import XingyeCouponAdapter, DEFAULT_ACTION_MAPPING


# ----------------------------------------------------------------- fixtures


@pytest.fixture
def xingye_config():
    """默认 adapter_config"""
    return {
        "hive_database": "recommand_workspace",
        "users_table": "user_profile_recommand",
        "items_table": "item_profile",
        "interactions_table": "user_seq_recommand",
        "time_format": "ms",
        "cooccurrence_enabled": True,
        "cooccurrence_window_days": 30,
        "cooccurrence_min_cooccur": 2,
        "cooccurrence_max_related": 50,
    }


@pytest.fixture
def fake_tables(spark):
    """构造 3 张派生表的内存 fixture。"""
    now_ms = int(_time.time() * 1000)

    users_data = [
        ("u001", "C", "M", "10"),
        ("u002", "B", "F", "5"),
        ("u003", "A", "M", "20"),
        ("uGhost", "X", "U", "0"),  # 有画像但没交互 → 会被级联过滤掉
    ]
    users_df = spark.createDataFrame(
        users_data, ["custref_no", "age", "sex", "self_income_round"]
    )

    items_data = [
        ("s100", "星巴克", "上海", "浦东", "121.5", "31.2", "咖啡", "餐饮"),
        ("s200", "麦当劳", "上海", "徐汇", "121.4", "31.1", "快餐", "餐饮"),
        ("s300", "肯德基", "北京", "朝阳", "116.4", "39.9", "快餐", "餐饮"),
        ("sOrphan", "孤儿门店", None, None, None, None, None, None),
    ]
    items_df = spark.createDataFrame(
        items_data,
        ["str_id", "str_nm", "city_nm", "cnty_nm", "lng", "lat", "cat_nm1", "cat_nm2"],
    )

    interactions_data = [
        ("$pageview",      now_ms - 1 * 86400 * 1000,       "u001", "s100"),
        ("$element_click", now_ms - 1 * 86400 * 1000 + 100, "u001", "s100"),
        ("$pageview",      now_ms - 2 * 86400 * 1000,       "u001", "s200"),
        ("$pageview",      now_ms - 3 * 86400 * 1000,       "u002", "s200"),
        ("coupon_receive", now_ms - 4 * 86400 * 1000,       "u002", "s200"),
        ("$pageview",      now_ms - 5 * 86400 * 1000,       "u003", "s300"),
    ]
    interactions_df = spark.createDataFrame(
        interactions_data, ["event", "time", "custref_no", "shopid"]
    )

    return {
        "user_profile_recommand": users_df,
        "item_profile": items_df,
        "user_seq_recommand": interactions_df,
    }


@pytest.fixture
def adapter(spark, xingye_config, fake_tables, monkeypatch):
    """构造适配器并把 _read_hive 重定向到内存 fixture。"""

    def fake_read(self, table):
        short = table.split(".")[-1]
        if short not in fake_tables:
            raise RuntimeError(f"fixture missing table {table}")
        return fake_tables[short].cache()

    monkeypatch.setattr(XingyeCouponAdapter, "_read_hive", fake_read)
    return XingyeCouponAdapter(spark, xingye_config)


# ------------------------------------------------------------ validate_config


class TestValidateConfig:
    def test_default_config_ok(self, spark, xingye_config):
        a = XingyeCouponAdapter(spark, xingye_config)
        a.validate_config()  # 不抛错

    def test_empty_hive_database_raises(self, spark, xingye_config):
        xingye_config["hive_database"] = ""
        a = XingyeCouponAdapter(spark, xingye_config)
        with pytest.raises(ValueError, match="hive_database"):
            a.validate_config()

    def test_empty_users_table_raises(self, spark, xingye_config):
        xingye_config["users_table"] = ""
        a = XingyeCouponAdapter(spark, xingye_config)
        with pytest.raises(ValueError, match="users_table"):
            a.validate_config()

    def test_invalid_time_format_raises(self, spark, xingye_config):
        xingye_config["time_format"] = "bogus"
        a = XingyeCouponAdapter(spark, xingye_config)
        with pytest.raises(ValueError, match="time_format"):
            a.validate_config()


# ----------------------------------------------------------------- action map


class TestActionMapping:
    def test_default_keys_present(self):
        for k in ("$pageview", "$element_click", "$exposure", "coupon_receive", "coupon_use", "pay"):
            assert k in DEFAULT_ACTION_MAPPING

    def test_user_override_wins(self, spark, xingye_config):
        xingye_config["action_mapping"] = {"$pageview": "custom_view"}
        a = XingyeCouponAdapter(spark, xingye_config)
        assert a.action_mapping["$pageview"] == "custom_view"
        # 未覆盖的默认仍保留
        assert a.action_mapping["$element_click"] == "click"


# ---------------------------------------------------------------- load_users


class TestLoadUsers:
    def test_user_id_renamed_and_unique(self, adapter):
        u = adapter.load_users()
        assert "user_id" in u.columns
        # u001/u002/u003/uGhost 共 4 行,无重复
        assert u.count() == 4
        # user_id 是字符串
        assert dict(u.dtypes)["user_id"] == "string"

    def test_extra_columns_pass_through(self, adapter):
        u = adapter.load_users()
        for col in ("age", "sex", "self_income_round"):
            assert col in u.columns


# ---------------------------------------------------------------- load_items


class TestLoadItems:
    def test_item_id_renamed_and_unique(self, adapter):
        i = adapter.load_items()
        assert "item_id" in i.columns
        assert "item_title" in i.columns
        assert i.count() == 4
        assert dict(i.dtypes)["item_id"] == "string"

    def test_item_title_filled(self, adapter):
        i = adapter.load_items()
        titles = [r["item_title"] for r in i.collect()]
        assert "星巴克" in titles


# ----------------------------------------------------------- load_interactions


class TestLoadInteractions:
    def test_columns_and_types(self, adapter):
        inter = adapter.load_interactions()
        assert set(["user_id", "item_id", "timestamp", "action"]).issubset(set(inter.columns))
        assert dict(inter.dtypes)["timestamp"] == "bigint"
        assert dict(inter.dtypes)["user_id"] == "string"

    def test_timestamp_converted_ms_to_seconds(self, adapter):
        inter = adapter.load_interactions()
        # u001 第一条 view 的 timestamp 应在 now-86400s 附近,不是 now-86400*1000
        import datetime
        row = (
            inter.filter("user_id = 'u001' AND action = 'view'")
            .orderBy("timestamp")
            .first()
        )
        assert row is not None
        ts = row["timestamp"]
        # 13 位毫秒值会 > 1e12,这里应 < 1e12(秒级)
        assert ts < 10**12
        # 应在最近 2 天内
        now = _time.time()
        assert abs(now - ts) < 2 * 86400

    def test_action_mapping_applied(self, adapter):
        inter = adapter.load_interactions()
        actions = set(r["action"] for r in inter.select("action").distinct().collect())
        # 预期有 view / click / receive
        assert "view" in actions
        assert "click" in actions
        assert "receive" in actions

    def test_unknown_event_lowercased_passthrough(self, spark, xingye_config, fake_tables, monkeypatch):
        # 注入一个未知事件
        fake_tables["user_seq_recommand"] = fake_tables["user_seq_recommand"].unionByName(
            fake_tables["user_seq_recommand"].sql_ctx.createDataFrame(
                [("custom_event_xyz", int(_time.time() * 1000), "u001", "s100")],
                ["event", "time", "custref_no", "shopid"],
            )
        )

        def fake_read(self, table):
            short = table.split(".")[-1]
            return fake_tables[short].cache()

        monkeypatch.setattr(XingyeCouponAdapter, "_read_hive", fake_read)
        a = XingyeCouponAdapter(spark, xingye_config)
        inter = a.load_interactions()
        actions = set(r["action"] for r in inter.select("action").distinct().collect())
        assert "custom_event_xyz" in actions  # 未知事件小写化透传

    def test_empty_userid_filtered(self, spark, xingye_config, fake_tables, monkeypatch):
        # 注入空 user_id 行,应被过滤
        df = fake_tables["user_seq_recommand"]
        fake_tables["user_seq_recommand"] = df.unionByName(
            df.sql_ctx.createDataFrame(
                [("$pageview", int(_time.time() * 1000), None, "s100")],
                ["event", "time", "custref_no", "shopid"],
            )
        )

        def fake_read(self, table):
            short = table.split(".")[-1]
            return fake_tables[short].cache()

        monkeypatch.setattr(XingyeCouponAdapter, "_read_hive", fake_read)
        a = XingyeCouponAdapter(spark, xingye_config)
        inter = a.load_interactions()
        assert inter.filter("user_id IS NULL OR user_id = ''").count() == 0


# --------------------------------------------------------- load_co_occurrence


class TestLoadCoOccurrence:
    def test_returns_dataframe(self, adapter):
        co = adapter.load_co_occurrence()
        assert co is not None
        assert "item_id" in co.columns
        assert "related_items" in co.columns

    def test_cooccurrence_for_overlapping_user(self, adapter):
        # u001 看过 s100 和 s200 → s100 与 s200 应互为 related_items
        co = adapter.load_co_occurrence().collect()
        items = {r["item_id"]: set(r["related_items"]) for r in co}
        # 至少 s100 或 s200 一方进入 related_items 集合
        s100_set = items.get("s100", set())
        s200_set = items.get("s200", set())
        # u001 在 s100 和 s200 都看过,且两个动作间隔小于 30 天
        assert "s200" in s100_set or "s100" in s200_set

    def test_disabled_returns_none(self, spark, xingye_config, fake_tables, monkeypatch):
        xingye_config["cooccurrence_enabled"] = False

        def fake_read(self, table):
            short = table.split(".")[-1]
            return fake_tables[short].cache()

        monkeypatch.setattr(XingyeCouponAdapter, "_read_hive", fake_read)
        a = XingyeCouponAdapter(spark, xingye_config)
        assert a.load_co_occurrence() is None

    def test_min_cooccur_filters_low_freq(self, spark, xingye_config, fake_tables, monkeypatch):
        # 把 min_cooccur 调到 3,原始数据无任何 pair 达到 3 次 → 应为空
        xingye_config["cooccurrence_min_cooccur"] = 3

        def fake_read(self, table):
            short = table.split(".")[-1]
            return fake_tables[short].cache()

        monkeypatch.setattr(XingyeCouponAdapter, "_read_hive", fake_read)
        a = XingyeCouponAdapter(spark, xingye_config)
        co = a.load_co_occurrence()
        assert co.count() == 0


# -------------------------------------------------------- time format branch


class TestTimeFormat:
    def test_seconds_branch(self, spark, xingye_config, fake_tables, monkeypatch):
        # 把 time 改为秒级(13 位 → 10 位)
        df = fake_tables["user_seq_recommand"]
        schema = StructType([
            StructField("event", StringType(), True),
            StructField("time", LongType(), True),
            StructField("custref_no", StringType(), True),
            StructField("shopid", StringType(), True),
        ])
        fake_tables["user_seq_recommand"] = df.sql_ctx.createDataFrame(
            [("$pageview", 1_700_000_000, "u001", "s100")], schema
        )
        xingye_config["time_format"] = "s"

        def fake_read(self, table):
            short = table.split(".")[-1]
            return fake_tables[short].cache()

        monkeypatch.setattr(XingyeCouponAdapter, "_read_hive", fake_read)
        a = XingyeCouponAdapter(spark, xingye_config)
        ts = a.load_interactions().first()["timestamp"]
        assert ts == 1_700_000_000  # 秒级直通

    def test_datetime_branch(self, spark, xingye_config, fake_tables, monkeypatch):
        df = fake_tables["user_seq_recommand"]
        schema = StructType([
            StructField("event", StringType(), True),
            StructField("time", StringType(), True),
            StructField("custref_no", StringType(), True),
            StructField("shopid", StringType(), True),
        ])
        fake_tables["user_seq_recommand"] = df.sql_ctx.createDataFrame(
            [("$pageview", "2026-06-24 12:00:00", "u001", "s100")], schema
        )
        xingye_config["time_format"] = "datetime"

        def fake_read(self, table):
            short = table.split(".")[-1]
            return fake_tables[short].cache()

        monkeypatch.setattr(XingyeCouponAdapter, "_read_hive", fake_read)
        a = XingyeCouponAdapter(spark, xingye_config)
        ts = a.load_interactions().first()["timestamp"]
        assert ts > 0
        import datetime
        assert datetime.datetime.fromtimestamp(ts) == datetime.datetime(2026, 6, 24, 12, 0, 0)


# -------------------------------------------------------- _full_table_name


class TestFullTableName:
    def test_bare_name_prefixed(self, adapter):
        assert adapter._full_table_name("foo") == "recommand_workspace.foo"

    def test_qualified_name_preserved(self, adapter):
        assert adapter._full_table_name("other.bar") == "other.bar"