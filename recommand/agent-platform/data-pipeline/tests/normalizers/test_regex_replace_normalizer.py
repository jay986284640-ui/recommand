# -*- coding: utf-8 -*-
"""正则替换规范化器测试"""

import pytest
from processing.normalizers.regex_replace_normalizer import RegexReplaceNormalizer


def test_regex_replace_normalizer_basic(spark):
    """测试基本正则替换"""
    data = [
        (1, "hello world"),
        (2, "test@email.com"),
        (3, "price: $99.99"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = RegexReplaceNormalizer([
        {"pattern": r"@.*\.com", "replacement": "[EMAIL]"},
        {"pattern": r"\$", "replacement": "USD "},
    ])
    result = normalizer.process(df, text_column="text")

    texts = [row.text for row in result.orderBy("id").collect()]

    assert "[EMAIL]" in texts[1]
    assert "USD " in texts[2]


def test_regex_replace_normalizer_empty_rules(spark):
    """测试空规则"""
    data = [
        (1, "hello world"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = RegexReplaceNormalizer(rules=[])
    result = normalizer.process(df, text_column="text")

    # 空规则不修改
    assert result.first().text == "hello world"


def test_regex_replace_normalizer_column_not_exists(spark):
    """测试列不存在"""
    data = [(1, "hello")]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = RegexReplaceNormalizer([
        {"pattern": r"hello", "replacement": "hi"}
    ])
    result = normalizer.process(df, text_column="non_existent")

    assert result.count() == 1


def test_regex_replace_normalizer_add_rule(spark):
    """测试 add_rule 方法"""
    data = [
        (1, "hello world"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = RegexReplaceNormalizer()
    normalizer.add_rule(r"world", "python")
    result = normalizer.process(df, text_column="text")

    assert "python" in result.first().text