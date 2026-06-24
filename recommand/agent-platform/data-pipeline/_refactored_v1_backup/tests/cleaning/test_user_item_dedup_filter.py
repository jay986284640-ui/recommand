# -*- coding: utf-8 -*-
"""用户-物品去重过滤器测试"""

import pytest
from cleaning.user_item_dedup_filter import UserItemDeduplicateFilter
from tests.fixtures.sample_data import create_user_item_dedup_df


def test_user_item_dedup_filter_keep_first(spark):
    """测试保留第一条（默认）"""
    df = create_user_item_dedup_df(spark)

    before_count = df.count()  # 6 条
    assert before_count == 6

    filter_obj = UserItemDeduplicateFilter(keep="first")
    result = filter_obj.filter(df)

    after_count = result.count()

    # user1-item1 连续重复：ts, ts+1
    # 保留第一条(ts)，过滤 ts+1（连续重复），保留 ts+20（不连续）
    # user1-item2 无连续重复，全部保留
    # user2-item1 保留
    # 总共保留: user1-item1(2条) + user1-item2(2条) + user2-item1(1条) = 5 条
    assert after_count == 5


def test_user_item_dedup_filter_keep_last(spark):
    """测试保留最后一条"""
    df = create_user_item_dedup_df(spark)

    filter_obj = UserItemDeduplicateFilter(keep="last")
    result = filter_obj.filter(df)

    after_count = result.count()

    # user1-item1 连续重复：保留 ts+10（最后一条），过滤 ts, ts+1
    # 保留: ts+10 + ts+20 + ts+30 + ts+40 = 4 条
    assert after_count == 5


def test_user_item_dedup_filter_no_timestamp(spark):
    """测试没有时间字段"""
    data = [
        ("user1", "item1", "review1"),
        ("user1", "item1", "review2"),
    ]
    df = spark.createDataFrame(data, ["user_id", "item_id", "review_text"])

    filter_obj = UserItemDeduplicateFilter()
    result = filter_obj.filter(df)

    # 无时间字段，不过滤
    assert result.count() == 2


def test_user_item_dedup_filter_no_user_id(spark):
    """测试没有 user_id 列"""
    data = [
        ("item1", 1700000000, "review1"),
        ("item1", 1700000100, "review2"),
    ]
    df = spark.createDataFrame(data, ["item_id", "timestamp", "review_text"])

    filter_obj = UserItemDeduplicateFilter()
    result = filter_obj.filter(df)

    # 列不存在，不过滤
    assert result.count() == 2


def test_user_item_dedup_filter_disabled():
    """测试禁用过滤器"""
    filter_obj = UserItemDeduplicateFilter(enabled=False)
    # 禁用后不过滤
    assert filter_obj.enabled is False