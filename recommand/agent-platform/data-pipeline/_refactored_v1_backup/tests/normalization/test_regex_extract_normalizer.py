# -*- coding: utf-8 -*-
"""正则提取规范化器测试"""

import pytest
from normalization.regex_extract_normalizer import RegexExtractNormalizer


def test_regex_extract_normalizer_price_dollar(spark):
    """测试提取美元价格"""
    data = [
        (1, "Price: $19.99", "original"),
        (2, "Cost: $1,000.50", "original"),
        (3, "No price here", "original"),
    ]
    df = spark.createDataFrame(data, ["id", "text", "other"])

    normalizer = RegexExtractNormalizer(columns={
        "text": {"pattern": r"\$([\d,]+\.?\d*)", "group": 1, "remove": ",", "default": "0"}
    })
    result = normalizer.process(df)

    texts = [row.text for row in result.orderBy("id").collect()]

    assert texts[0] == "19.99"
    assert texts[1] == "1000.50"
    # 提取失败使用默认值
    assert texts[2] == "0"


def test_regex_extract_normalizer_price_euro(spark):
    """测试提取欧元价格（使用 | 匹配多种格式）"""
    data = [
        (1, "Price: 19.99 EUR"),
        (2, "Cost: 100.50 Euro"),
        (3, "Value: 50 EUR"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = RegexExtractNormalizer(columns={
        "text": {"pattern": r"([\d.]+)\s+(EUR|Euro)", "group": 1, "remove": "", "default": "0"}
    })
    result = normalizer.process(df)

    texts = [row.text for row in result.orderBy("id").collect()]

    assert texts[0] == "19.99"
    assert texts[1] == "100.50"
    assert texts[2] == "50"


def test_regex_extract_normalizer_rating(spark):
    """测试提取评分"""
    data = [
        (1, "Rating: 4.5/5"),
        (2, "Score: 3/5 stars"),
        (3, "No rating"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = RegexExtractNormalizer(columns={
        "text": {"pattern": r"([\d.]+)/5", "group": 1, "default": "0"}
    })
    result = normalizer.process(df)

    texts = [row.text for row in result.orderBy("id").collect()]

    assert texts[0] == "4.5"
    assert texts[1] == "3"
    assert texts[2] == "0"


def test_regex_extract_normalizer_empty_columns(spark):
    """测试空配置"""
    data = [
        (1, "hello world"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = RegexExtractNormalizer(columns={})
    result = normalizer.process(df)

    # 空配置不修改
    assert result.first().text == "hello world"


def test_regex_extract_normalizer_column_not_exists(spark):
    """测试列不存在"""
    data = [(1, "hello")]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = RegexExtractNormalizer(columns={
        "non_existent": {"pattern": r"hello", "group": 1}
    })
    result = normalizer.process(df)

    # 列不存在时不修改原数据
    assert result.count() == 1
    assert result.first().text == "hello"


def test_regex_extract_normalizer_add_column_rule(spark):
    """测试 add_column_rule 方法"""
    data = [
        (1, "Price: $50"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = RegexExtractNormalizer()
    normalizer.add_column_rule("text", r"\$([\d]+)", group=1, remove="", default="0")
    result = normalizer.process(df)

    assert result.first().text == "50"


def test_regex_extract_normalizer_multiple_columns(spark):
    """测试多列配置"""
    data = [
        (1, "$19.99", "4.5/5"),
        (2, "$100", "3/5"),
    ]
    df = spark.createDataFrame(data, ["id", "price", "rating"])

    normalizer = RegexExtractNormalizer(columns={
        "price": {"pattern": r"\$([\d.]+)", "group": 1, "remove": "", "default": "0"},
        "rating": {"pattern": r"([\d.]+)/5", "group": 1, "default": "0"}
    })
    result = normalizer.process(df)

    rows = result.orderBy("id").collect()

    assert rows[0].price == "19.99"
    assert rows[0].rating == "4.5"
    assert rows[1].price == "100"
    assert rows[1].rating == "3"