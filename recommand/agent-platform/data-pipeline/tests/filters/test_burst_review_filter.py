# -*- coding: utf-8 -*-
"""突发评论过滤器测试"""

from processing.filters.burst_review_filter import BurstReviewFilter
from tests.fixtures.sample_data import create_burst_review_df


def test_burst_review_filter_default(spark):
    """测试默认参数（10分钟内超过50条）"""
    df = create_burst_review_df(spark)

    before_count = df.count()  # 115 条
    assert before_count == 115

    filter_obj = BurstReviewFilter()
    result = filter_obj.filter(df)

    after_count = result.count()

    # user1: 100条/5分钟 -> 突发，被过滤
    # user2: 10条/1小时 -> 正常，保留
    # user3: 5条 -> 正常，保留
    # 保留: 10 + 5 = 15 条
    assert after_count == 15
    assert after_count < before_count


def test_burst_review_filter_custom_threshold(spark):
    """测试自定义阈值"""
    df = create_burst_review_df(spark)

    before_count = df.count()
    assert before_count == 115

    # 更严格的阈值：1分钟内超过5条
    filter_obj = BurstReviewFilter(time_window_minutes=1, max_reviews=5)
    result = filter_obj.filter(df)

    after_count = result.count()
    # user1: 100条在5分钟内，任何1分钟窗口都有大量评论 -> 突发
    # user2: 10条/1小时 = 6分钟一条，1分钟窗口最多1条 -> 正常
    # user3: 5条分布在1小时内 -> 正常
    assert after_count < before_count


def test_burst_review_filter_no_timestamp(spark):
    """测试 timestamp 列不存在"""
    data = [
        ("user1", "review1"),
        ("user2", "review2"),
    ]
    df = spark.createDataFrame(data, ["user_id", "review_text"])

    filter_obj = BurstReviewFilter()
    result = filter_obj.filter(df)

    # 列不存在，不过滤
    assert result.count() == 2


def test_burst_review_filter_no_user_id(spark):
    """测试 user_id 列不存在"""
    data = [
        (1700000000, "review1"),
        (1700000100, "review2"),
    ]
    df = spark.createDataFrame(data, ["timestamp", "review_text"])

    filter_obj = BurstReviewFilter()
    result = filter_obj.filter(df)

    # 列不存在，不过滤
    assert result.count() == 2


def test_burst_review_filter_disabled():
    """测试禁用过滤器"""
    filter_obj = BurstReviewFilter(enabled=False)
    # 禁用后不过滤
    assert filter_obj.enabled is False