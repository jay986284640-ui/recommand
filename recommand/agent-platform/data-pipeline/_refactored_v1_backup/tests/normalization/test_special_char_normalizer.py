# -*- coding: utf-8 -*-
"""特殊符号规范化器测试"""

import pytest
from normalization.special_char_normalizer import SpecialCharNormalizer


def test_special_char_normalizer_basic(spark):
    """测试基本特殊符号清理"""
    data = [
        (1, "Hello@World!"),
        (2, "Price: $100"),
        (3, "Text with #hashtag @mention"),
        (4, "Math: a + b = c"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = SpecialCharNormalizer()
    result = normalizer.process(df, text_column="text")

    texts = [row.text for row in result.orderBy("id").collect()]

    # @ 和 # 应该被替换为空格
    assert "@" not in texts[0]
    assert "#" not in texts[2]
    # 保留的字符应该还在
    assert "Hello" in texts[0]
    assert "World" in texts[0]


def test_special_char_normalizer_preserves_punctuation(spark):
    """测试保留常见标点"""
    data = [
        (1, "Hello, world! How are you? I'm fine."),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = SpecialCharNormalizer()
    result = normalizer.process(df, text_column="text")

    text = result.first().text
    # 常见标点应该保留
    assert "," in text
    assert "!" in text
    assert "?" in text
    assert "'" in text


def test_special_char_normalizer_column_not_exists(spark):
    """测试列不存在"""
    data = [(1, "hello")]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = SpecialCharNormalizer()
    result = normalizer.process(df, text_column="non_existent")

    assert result.count() == 1