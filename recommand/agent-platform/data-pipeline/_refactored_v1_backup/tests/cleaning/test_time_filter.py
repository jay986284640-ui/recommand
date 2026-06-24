# -*- coding: utf-8 -*-
"""时间过滤器测试"""

import pytest
from cleaning.time_filter import TimeFilter
from tests.fixtures.sample_data import create_time_filter_df


def test_time_filter_default_years(spark):
    """测试默认过滤 10 年"""
    df = create_time_filter_df(spark, use_recent_years=True)

    before_count = df.count()  # 4 条
    assert before_count == 4

    # 使用默认 10 年过滤
    filter_obj = TimeFilter(years=10)
    result = filter_obj.filter(df)

    after_count = result.count()

    # 4 年前的数据应该保留，15 年前的数据应该被过滤
    # 但由于使用当前时间动态计算，这里只验证过滤有效果
    assert after_count == 3


def test_time_filter_custom_years(spark):
    """测试自定义年份过滤"""
    df = create_time_filter_df(spark, use_recent_years=True)

    # 过滤最近 1 年
    filter_obj = TimeFilter(years=1)
    result = filter_obj.filter(df)

    # 最近 100 天的数据应该保留
    assert result.count() == 2


def test_time_filter_no_timestamp_column(spark):
    """测试 timestamp 列不存在"""
    data = [
        (1, "a"),
        (2, "b"),
    ]
    df = spark.createDataFrame(data, ["id", "name"])

    filter_obj = TimeFilter(years=5)
    result = filter_obj.filter(df)

    # 列不存在，不过滤
    assert result.count() == 2


def test_time_filter_all_old_data(spark):
    """测试全部数据都是旧数据"""
    df = create_time_filter_df(spark, use_recent_years=False)

    filter_obj = TimeFilter(years=1)
    result = filter_obj.filter(df)

    # 全部数据都超过 1 年，应该被全部过滤
    assert result.count() == 0


def test_time_filter_disabled():
    """测试禁用过滤器"""
    filter_obj = TimeFilter(years=1, enabled=False)

    # 禁用后不过滤
    assert filter_obj.enabled is False
