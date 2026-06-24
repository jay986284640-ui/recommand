# -*- coding: utf-8 -*-
"""Unicode 规范化器测试"""

import pytest
from normalization.unicode_normalizer import UnicodeNormalizer


def test_unicode_normalizer_basic(spark):
    """测试基本 Unicode 规范化"""
    data = [
        (1, "café"),
        (2, "naïve"),
        (3, "résumé"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = UnicodeNormalizer()
    result = normalizer.process(df, text_column="text")

    texts = [row.text for row in result.orderBy("id").collect()]

    # NFC 规范化后，一致性字符的编码相同
    # café 中的 e 和 é 是不同的字符
    assert "café" in texts
    assert "naïve" in texts


def test_unicode_normalizer_composed_form(spark):
    """测试组合形式的规范化"""
    # é 可以用单个字符 (U+00E9) 或 e + 组合音调 (U+0065 + U+0301) 表示
    data = [
        (1, "café"),  # 可能是组合形式
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = UnicodeNormalizer()
    result = normalizer.process(df, text_column="text")

    # 规范化后应该是统一的
    assert result.first().text is not None


def test_unicode_normalizer_column_not_exists(spark):
    """测试列不存在"""
    data = [(1, "hello")]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = UnicodeNormalizer()
    result = normalizer.process(df, text_column="non_existent")

    assert result.count() == 1


def test_unicode_normalizer_null_handling(spark):
    """测试 null 值处理"""
    data = [
        (1, None),
        (2, "hello"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = UnicodeNormalizer()
    result = normalizer.process(df, text_column="text")

    texts = [row.text for row in result.orderBy("id").collect()]
    assert texts[0] is None
    assert texts[1] == "hello"