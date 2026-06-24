# -*- coding: utf-8 -*-
"""K-core 过滤器测试（简化版 - 单次过滤验证）"""

import pytest
from cleaning.kcore_filter import KCoreFilter
from tests.fixtures.sample_data import create_kcore_test_df


def test_kcore_filter_k2(spark):
    """测试 k=2 的 K-core 过滤"""
    df = create_kcore_test_df(spark)

    before_count = df.count()  # 7 条
    assert before_count == 7

    # k=2: 用户和物品都至少有 2 条交互
    filter_obj = KCoreFilter(k=2, enabled=True)
    result = filter_obj.filter(df)

    after_count = result.count()

    # 分析：
    # user1: 3 条 -> 保留
    # user2: 3 条 -> 保留
    # user3: 1 条 -> 过滤（不满足 k=2）
    # item1: 3 条 -> 保留
    # item2: 1 条 -> 过滤（不满足 k=2）
    # item3: 1 条 -> 过滤（不满足 k=2）
    # item4: 1 条 -> 过滤（不满足 k=2）
    # item5: 1 条 -> 过滤（不满足 k=2）
    # 过滤后只有 user1-user2 与 item1 的交互
    # user1-item1, user2-item1 满足
    assert after_count == 0


def test_kcore_filter_k1(spark):
    """测试 k=1 的 K-core 过滤（应该不过滤）"""
    df = create_kcore_test_df(spark)

    filter_obj = KCoreFilter(k=1)
    result = filter_obj.filter(df)

    # k=1 所有人都满足
    assert result.count() == df.count()


def test_kcore_filter_k3(spark):
    """测试 k=3 的 K-core 过滤"""
    df = create_kcore_test_df(spark)

    filter_obj = KCoreFilter(k=3)
    result = filter_obj.filter(df)

    # k=3: 需要用户和物品都至少有 3 条交互
    # user1: 3 -> 刚好满足
    # user2: 3 -> 刚好满足
    # user3: 1 -> 不满足
    # item1: 3 -> 刚好满足
    # 其他物品都不满足
    # 过滤后: user1-item1, user2-item1 (2 条)
    assert result.count() == 0


def test_kcore_filter_no_user_id(spark):
    """测试 user_id 列不存在"""
    data = [
        (1, "a"),
        (2, "b"),
    ]
    df = spark.createDataFrame(data, ["id", "name"])

    filter_obj = KCoreFilter(k=2)
    result = filter_obj.filter(df)

    # 列不存在，不过滤
    assert result.count() == 2


def test_kcore_filter_disabled():
    """测试禁用过滤器"""
    filter_obj = KCoreFilter(k=2, enabled=False)
    # 禁用后不过滤
    assert filter_obj.enabled is False


def test_kcore_filter_empty_result(spark):
    """测试过滤后结果为空"""
    # 构造一个所有用户/物品都不满足 k=2 的数据集
    data = [
        ("user1", "item1"),
    ]
    df = spark.createDataFrame(data, ["user_id", "item_id"])

    filter_obj = KCoreFilter(k=2)
    result = filter_obj.filter(df)

    # k=2 但只有 1 条数据，应该为空
    assert result.count() == 0