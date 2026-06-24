# -*- coding: utf-8 -*-
"""数据质量过滤器测试"""

import pytest
from processing.filters.quality_filter import QualityFilter
from tests.fixtures.sample_data import create_quality_filter_df


def test_quality_filter_default(spark):
    """测试默认质量过滤（最小长度 10）"""
    df = create_quality_filter_df(spark)

    before_count = df.count()  # 6 条
    assert before_count == 6

    filter_obj = QualityFilter()
    result = filter_obj.filter(df)

    after_count = result.count()

    # 过滤掉长度小于 10 和为空的记录
    # 保留: id=1, 5 (长度足够)
    # 过滤: id=2(short), 3(""), 4(null), 6(short)
    assert after_count == 2


def test_quality_filter_custom_min_length(spark):
    """测试自定义最小长度"""
    data = [
        (1, "Hello World"),  # 11 chars
        (2, "Hi"),  # 2 chars
        (3, "Hello"),  # 5 chars
    ]
    df = spark.createDataFrame(data, ["id", "review_text"])

    filter_obj = QualityFilter(min_text_length=10)
    result = filter_obj.filter(df)

    # 只保留长度 >= 10 的
    assert result.count() == 1
    assert result.first().id == 1


def test_quality_filter_column_not_exists(spark):
    """测试列不存在"""
    data = [
        (1, "text"),
        (2, "text"),
    ]
    df = spark.createDataFrame(data, ["id", "content"])

    filter_obj = QualityFilter(text_column="non_existent")
    result = filter_obj.filter(df)

    # 列不存在，不过滤
    assert result.count() == 2


def test_quality_filter_disabled():
    """测试禁用过滤器"""
    filter_obj = QualityFilter(enabled=False)
    # 禁用后不过滤
    assert filter_obj.enabled is False