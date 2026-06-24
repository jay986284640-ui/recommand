# -*- coding: utf-8 -*-
"""通用测试数据构造"""

from datetime import datetime, timedelta
from pyspark.sql import DataFrame
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, LongType, DoubleType, ArrayType


def create_interactions_df(spark, include_nulls: bool = False) -> DataFrame:
    """
    创建交互数据 DataFrame

    Args:
        spark: SparkSession
        include_nulls: 是否包含 null 值（用于测试过滤）

    Returns:
        交互数据 DataFrame，包含 user_id, item_id, timestamp, rating, review_text 字段
    """
    data = [
        # 正常数据
        ("user1", "item1", 1700000000, 5.0, "Great product!"),
        ("user1", "item2", 1700000100, 4.0, "Good quality"),
        ("user2", "item1", 1700000200, 3.0, "Average"),
        ("user2", "item3", 1700000300, 5.0, "Excellent!"),
        ("user3", "item2", 1700000400, 2.0, "Not bad"),
        ("user3", "item3", 1700000500, 1.0, "Poor"),
        # 边界数据
        ("user4", "item4", 1700000600, None, "No rating"),
        ("user5", "item5", 1700000700, 4.5, ""),
    ]

    if include_nulls:
        # 添加包含 null 的数据
        data.extend([
            (None, "item6", 1700000800, 3.0, "User is null"),
            ("user6", None, 1700000900, 4.0, "Item is null"),
            ("user7", "item7", None, 5.0, "Timestamp is null"),
            ("user8", "item8", 1700001000, None, "Rating is null"),
        ])

    schema = StructType([
        StructField("user_id", StringType(), True),
        StructField("item_id", StringType(), True),
        StructField("timestamp", LongType(), True),
        StructField("rating", DoubleType(), True),
        StructField("review_text", StringType(), True),
    ])

    return spark.createDataFrame(data, schema)


def create_users_df(spark) -> DataFrame:
    """创建用户数据 DataFrame"""
    data = [
        ("user1", "Alice", 25),
        ("user2", "Bob", 30),
        ("user3", "Charlie", 35),
        ("user4", "Diana", 28),
    ]

    schema = StructType([
        StructField("user_id", StringType(), True),
        StructField("name", StringType(), True),
        StructField("age", IntegerType(), True),
    ])

    return spark.createDataFrame(data, schema)


def create_items_df(spark) -> DataFrame:
    """创建物品数据 DataFrame"""
    data = [
        ("item1", "Product A", 100.0),
        ("item2", "Product B", 200.0),
        ("item3", "Product C", 150.0),
        ("item4", "Product D", 80.0),
    ]

    schema = StructType([
        StructField("item_id", StringType(), True),
        StructField("name", StringType(), True),
        StructField("price", DoubleType(), True),
    ])

    return spark.createDataFrame(schema)


def create_text_df(spark) -> DataFrame:
    """创建文本数据 DataFrame（用于规范器测试）"""
    data = [
        (1, "HELLO WORLD", "This is a <b>bold</b> text", "café résumé"),
        (2, "hello world", "Plain text here", "naïve"),
        (3, "TeSt CaSe", "<p>HTML content</p>", "日本"),
        (4, "  multiple   spaces   ", "Text with &amp; entity", ""),
    ]

    schema = StructType([
        StructField("id", IntegerType(), True),
        StructField("text", StringType(), True),
        StructField("html_text", StringType(), True),
        StructField("unicode_text", StringType(), True),
    ])

    # 注意：由于 schema 中的字段名是 unicode_text，需要特殊处理
    return spark.createDataFrame(data, ["id", "text", "html_text", "unicode_text"])


def create_rule_test_df(spark) -> DataFrame:
    """创建用于规则过滤器测试的 DataFrame"""
    data = [
        # 基础比较测试数据
        {"id": 1, "value": 10, "name": "apple", "status": "active"},
        {"id": 2, "value": 20, "name": "banana", "status": "inactive"},
        {"id": 3, "value": 30, "name": "cherry", "status": "active"},
        {"id": 4, "value": 40, "name": "date", "status": "pending"},
        {"id": 5, "value": None, "name": "elderberry", "status": "active"},
        # 字符串长度测试数据
        {"id": 6, "value": 5, "name": "ab", "status": "a"},  # length=2
        {"id": 7, "value": 6, "name": "abc", "status": "ab"},  # length=3
        {"id": 8, "value": 7, "name": "abcd", "status": "abc"},  # length=4
        {"id": 9, "value": 8, "name": "abcde", "status": "abcd"},  # length=5
        # 正则匹配测试数据
        {"id": 10, "value": 9, "name": "test123", "status": "active"},
        {"id": 11, "value": 10, "name": "abc123", "status": "active"},
        {"id": 12, "value": 11, "name": "nodigits", "status": "inactive"},
        # 空值测试数据
        {"id": 13, "value": 12, "name": "", "status": "active"},
        {"id": 14, "value": 13, "name": None, "status": "active"},
        # 列表判断测试数据
        {"id": 15, "value": 14, "name": "apple", "status": "active"},
        {"id": 16, "value": 15, "name": "banana", "status": "inactive"},
        {"id": 17, "value": 16, "name": "cherry", "status": "unknown"},
    ]

    return spark.createDataFrame(data)


def create_time_filter_df(spark, use_recent_years: bool = True) -> DataFrame:
    """创建用于时间过滤测试的 DataFrame"""
    now = datetime.now()
    # 最近 1 年的数据
    recent_ts = int((now - timedelta(days=100)).timestamp())
    # 5 年前的数据
    old_ts = int((now - timedelta(days=365 * 5)).timestamp())
    # 15 年前的数据（应该被过滤）
    very_old_ts = int((now - timedelta(days=365 * 15)).timestamp())

    if use_recent_years:
        data = [
            ("user1", "item1", recent_ts, "recent review 1"),
            ("user2", "item2", recent_ts + 1000, "recent review 2"),
            ("user3", "item3", old_ts, "old review"),
            ("user4", "item4", very_old_ts, "very old review"),
        ]
    else:
        # 全部使用旧时间，用于测试不过滤的情况
        data = [
            ("user1", "item1", old_ts, "review 1"),
            ("user2", "item2", old_ts + 1000, "review 2"),
        ]

    schema = StructType([
        StructField("user_id", StringType(), True),
        StructField("item_id", StringType(), True),
        StructField("timestamp", LongType(), True),
        StructField("review", StringType(), True),
    ])

    return spark.createDataFrame(data, schema)


def create_kcore_test_df(spark) -> DataFrame:
    """
    创建用于 K-core 过滤测试的 DataFrame

    数据设计：
    - user1, user2 各自有 3 条交互（满足 k=2）
    - user3 只有 1 条交互（不满足 k=2）
    - item1 有 3 条交互（满足 k=2）
    - item2 只有 1 条交互（不满足 k=2）
    """
    data = [
        ("user1", "item1"),
        ("user1", "item2"),
        ("user1", "item3"),
        ("user2", "item1"),
        ("user2", "item4"),
        ("user2", "item5"),
        ("user3", "item1"),  # user3 只有 1 条，不满足 k=2
    ]

    schema = StructType([
        StructField("user_id", StringType(), True),
        StructField("item_id", StringType(), True),
    ])

    return spark.createDataFrame(data, schema)


def create_burst_review_df(spark) -> DataFrame:
    """
    创建用于突发评论过滤测试的 DataFrame

    数据设计：
    - user1: 100 条评论，集中在 5 分钟内（突发用户）
    - user2: 10 条评论，均匀分布在 1 小时内（正常用户）
    - user3: 5 条评论（正常用户）
    """
    now_ts = int(datetime.now().timestamp())
    base_ts = now_ts - 3600  # 1 小时前

    data = []

    # user1: 100 条评论在 5 分钟内（300秒）
    for i in range(100):
        ts = base_ts + (i * 3)  # 每 3 秒一条，5 分钟内发完
        data.append(("user1", ts, f"review {i}"))

    # user2: 10 条评论均匀分布在 1 小时内
    for i in range(10):
        ts = base_ts + (i * 360)  # 每 6 分钟一条
        data.append(("user2", ts, f"review {i}"))

    # user3: 5 条评论
    for i in range(5):
        ts = base_ts + (i * 720)
        data.append(("user3", ts, f"review {i}"))

    schema = StructType([
        StructField("user_id", StringType(), True),
        StructField("timestamp", LongType(), True),
        StructField("review_text", StringType(), True),
    ])

    return spark.createDataFrame(data, schema)


def create_user_item_dedup_df(spark) -> DataFrame:
    """
    创建用于用户-物品去重测试的 DataFrame

    数据设计：
    - user1 -> item1 有连续重复（timestamp 相同或相邻）
    - user1 -> item2 无连续重复
    """
    ts = 1700000000

    data = [
        # user1 -> item1 连续重复（时间相邻）
        ("user1", "item1", ts, "review 1"),
        ("user1", "item1", ts + 1, "review 2"),  # 连续重复
        ("user1", "item1", ts + 25, "review 3"),  # 非连续（中间有 ts+20 隔开）
        # user1 -> item2 非连续（中间有 ts+25 隔开）
        ("user1", "item2", ts + 20, "review 4"),
        ("user1", "item2", ts + 30, "review 5"),
        # user2 -> item1
        ("user2", "item1", ts + 40, "review 6"),
    ]

    schema = StructType([
        StructField("user_id", StringType(), True),
        StructField("item_id", StringType(), True),
        StructField("timestamp", LongType(), True),
        StructField("review_text", StringType(), True),
    ])

    return spark.createDataFrame(data, schema)


def create_quality_filter_df(spark) -> DataFrame:
    """创建用于质量过滤测试的 DataFrame"""
    data = [
        (1, "This is a good product with enough text"),
        (2, "Short"),  # 太短
        (3, ""),  # 空字符串
        (4, None),  # null
        (5, "Another decent review with sufficient length"),
        (6, "a"),  # 太短
    ]

    schema = StructType([
        StructField("id", IntegerType(), True),
        StructField("review_text", StringType(), True),
    ])

    return spark.createDataFrame(data, schema)


def create_product_exists_df(spark) -> DataFrame:
    """创建用于商品存在性过滤测试的交互数据"""
    data = [
        ("user1", "item1"),
        ("user1", "item2"),
        ("user1", "item3"),  # item3 不在物品表中
        ("user2", "item1"),
        ("user2", "item4"),  # item4 不在物品表中
    ]

    schema = StructType([
        StructField("user_id", StringType(), True),
        StructField("item_id", StringType(), True),
    ])

    return spark.createDataFrame(data, schema)


def create_items_for_product_exists_df(spark) -> DataFrame:
    """创建用于商品存在性过滤测试的物品数据"""
    data = [
        ("item1", "Product A"),
        ("item2", "Product B"),
    ]

    schema = StructType([
        StructField("item_id", StringType(), True),
        StructField("name", StringType(), True),
    ])

    return spark.createDataFrame(data, schema)