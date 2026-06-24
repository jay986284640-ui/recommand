# -*- coding: utf-8 -*-
"""去重过滤器测试"""

import pytest
from cleaning.deduplicate_filter import DeduplicateFilter


def test_deduplicate_filter_all_columns(spark):
    """测试全列去重"""
    data = [
        (1, "a", 100),
        (1, "a", 100),  # 完全重复
        (2, "b", 200),
        (1, "a", 100),  # 完全重复
    ]
    df = spark.createDataFrame(data, ["id", "name", "value"])

    filter_obj = DeduplicateFilter()
    result = filter_obj.filter(df)

    # 去重后应该只有 2 条
    assert result.count() == 2


def test_deduplicate_filter_key_column(spark):
    """测试指定列去重"""
    data = [
        (1, "a", 100),
        (1, "b", 200),  # id 重复
        (2, "c", 300),
        (2, "d", 400),  # id 重复
    ]
    df = spark.createDataFrame(data, ["id", "name", "value"])

    filter_obj = DeduplicateFilter(key_column="id")
    result = filter_obj.filter(df)

    # 按 id 去重后应该只有 2 条
    assert result.count() == 2


def test_deduplicate_filter_key_not_exists(spark):
    """测试去重列不存在"""
    data = [
        (1, "a"),
        (2, "b"),
    ]
    df = spark.createDataFrame(data, ["id", "name"])

    filter_obj = DeduplicateFilter(key_column="non_existent")
    result = filter_obj.filter(df)

    # 列不存在，不过滤
    assert result.count() == 2


def test_deduplicate_filter_disabled():
    """测试禁用过滤器"""
    filter_obj = DeduplicateFilter(enabled=False)
    # 禁用后不过滤
    assert filter_obj.enabled is False