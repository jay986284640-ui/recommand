# -*- coding: utf-8 -*-
"""小写转换规范化器测试"""

import pytest
from processing.normalizers.lowercase_normalizer import LowercaseNormalizer
from tests.fixtures.sample_data import create_text_df


def test_lowercase_normalizer_basic(spark):
    """测试基本小写转换"""
    df = create_text_df(spark)

    normalizer = LowercaseNormalizer()
    result = normalizer.process(df, text_column="text")

    # 验证转换结果
    texts = [row.text for row in result.orderBy("id").collect()]
    assert texts[0] == "hello world"
    assert texts[1] == "hello world"
    assert texts[2] == "test case"
    assert texts[3] == "  multiple   spaces   "


def test_lowercase_normalizer_column_not_exists(spark):
    """测试列不存在"""
    df = create_text_df(spark)

    normalizer = LowercaseNormalizer()
    result = normalizer.process(df, text_column="non_existent")

    # 列不存在，返回原 DataFrame
    assert result.count() == df.count()


def test_lowercase_normalizer_is_column_supported(spark):
    """测试列类型支持检查"""
    normalizer = LowercaseNormalizer()

    # StringType 应该支持
    data = [(1, "hello")]
    df = spark.createDataFrame(data, ["id", "text"])
    assert normalizer.is_column_supported(df, "text") is True

    # IntegerType 不应该支持
    data2 = [(1, 123)]
    df2 = spark.createDataFrame(data2, ["id", "value"])
    assert normalizer.is_column_supported(df2, "value") is False