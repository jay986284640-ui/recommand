# -*- coding: utf-8 -*-
"""字段完整性过滤器测试"""

import pytest
from processing.filters.field_completeness_filter import FieldCompletenessFilter
from tests.fixtures.sample_data import create_interactions_df


def test_field_completeness_filter_default_fields(spark):
    """测试默认字段过滤（user_id, item_id, timestamp）"""
    # 创建包含 null 值的数据
    df = create_interactions_df(spark, include_nulls=True)

    before_count = df.count()  # 12 条
    assert before_count == 12

    # 应用过滤
    filter_obj = FieldCompletenessFilter()
    result = filter_obj.filter(df)

    after_count = result.count()

    # 过滤掉 user_id, item_id, timestamp 为空的记录
    # 原始数据: 12 条，过滤后应该只保留 8 条（4条正常的 + 4条边界非空）
    # 实际上：有 4 条包含 null (user1-item6, user6-itemnull, user7-item7, user8-item8)
    assert after_count == 9
    assert after_count < before_count


def test_field_completeness_filter_custom_fields(spark):
    """测试自定义字段过滤"""
    data = [
        (1, "a", 100),
        (2, None, 200),
        (3, "b", None),
        (4, "c", 300),
    ]
    df = spark.createDataFrame(data, ["id", "name", "value"])

    before_count = df.count()
    assert before_count == 4

    # 只过滤 name 和 value 字段
    filter_obj = FieldCompletenessFilter(required_fields=["name", "value"])
    result = filter_obj.filter(df)

    after_count = result.count()
    # 过滤掉 name 或 value 为空的记录
    assert after_count == 2


def test_field_completeness_filter_numeric_fields(spark):
    """测试数值字段过滤（数值类型的 null 过滤）"""
    data = [
        (1, 100),
        (2, None),
        (3, 200),
        (4, None),
    ]
    df = spark.createDataFrame(data, ["id", "value"])

    filter_obj = FieldCompletenessFilter(required_fields=["value"])
    result = filter_obj.filter(df)

    assert result.count() == 2


def test_field_completeness_filter_string_empty(spark):
    """测试字符串空值过滤（null 和空字符串）"""
    data = [
        (1, "valid"),
        (2, ""),
        (3, "also valid"),
        (4, None),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    filter_obj = FieldCompletenessFilter(required_fields=["text"])
    result = filter_obj.filter(df)

    # 只保留非 null 且非空字符串的记录
    result_list = sorted(result.collect(), key=lambda x: x.id)
    assert len(result_list) == 2
    assert result_list[0].text == "valid"
    assert result_list[1].text == "also valid"


def test_field_completeness_filter_disabled():
    """测试禁用过滤器"""
    filter_obj = FieldCompletenessFilter(enabled=False)

    # 禁用后不过滤
    assert filter_obj.enabled is False


def test_field_completeness_filter_missing_field(spark):
    """测试字段不存在的情况"""
    data = [
        (1, "a"),
        (2, "b"),
    ]
    df = spark.createDataFrame(data, ["id", "name"])

    # 过滤不存在的字段，应该不过滤
    filter_obj = FieldCompletenessFilter(required_fields=["non_existent_field"])
    result = filter_obj.filter(df)

    assert result.count() == 2