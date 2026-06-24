# -*- coding: utf-8 -*-
"""空格规范化器测试"""

import pytest
from processing.normalizers.whitespace_normalizer import WhitespaceNormalizer


def test_whitespace_normalizer_basic(spark):
    """测试基本空格规范化"""
    data = [
        (1, "hello   world"),
        (2, "  multiple   spaces  "),
        (3, "\ttab\tspaces\t"),
        (4, "no extra spaces"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = WhitespaceNormalizer()
    result = normalizer.process(df, text_column="text")

    texts = [row.text for row in result.orderBy("id").collect()]

    # 多个空格应变成单个空格
    assert "  " not in texts[0]
    assert texts[0] == "hello world"
    # 首尾空格应被去除
    assert texts[1] == "multiple spaces"
    assert texts[2] == "tab spaces"


def test_whitespace_normalizer_newlines(spark):
    """测试换行符处理"""
    data = [
        (1, "line1\n\nline2\nline3"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = WhitespaceNormalizer()
    result = normalizer.process(df, text_column="text")

    text = result.first().text
    # 换行符应变成空格
    assert "\n" not in text
    assert "line1 line2 line3" in text


def test_whitespace_normalizer_column_not_exists(spark):
    """测试列不存在"""
    data = [(1, "hello")]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = WhitespaceNormalizer()
    result = normalizer.process(df, text_column="non_existent")

    assert result.count() == 1


def test_whitespace_normalizer_null_handling(spark):
    """测试 null 值处理"""
    data = [
        (1, None),
        (2, "  spaces  "),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = WhitespaceNormalizer()
    result = normalizer.process(df, text_column="text")

    texts = [row.text for row in result.orderBy("id").collect()]
    assert texts[0] is None
    assert texts[1] == "spaces"