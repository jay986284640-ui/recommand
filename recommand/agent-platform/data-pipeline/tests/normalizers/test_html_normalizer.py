# -*- coding: utf-8 -*-
"""HTML 规范化器测试"""

import pytest
from processing.normalizers.html_normalizer import HtmlNormalizer
from tests.fixtures.sample_data import create_text_df


def test_html_normalizer_string_type(spark):
    """测试 String 类型的 HTML 清理"""
    data = [
        (1, "This is a <b>bold</b> text"),
        (2, "<p>Paragraph</p> with &amp; entity"),
        (3, "Text with &lt;script&gt;alert('xss')&lt;/script&gt;"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = HtmlNormalizer()
    result = normalizer.process(df, text_column="text")

    texts = [row.text for row in result.orderBy("id").collect()]

    # 验证 HTML 标签被移除
    assert "<b>" not in texts[0]
    assert "bold" in texts[0]
    # 验证 HTML 实体被解码
    assert "&" in texts[1]
    assert "<" not in texts[2]


def test_html_normalizer_array_type(spark):
    """测试 Array 类型的 HTML 清理"""
    from pyspark.sql.types import ArrayType, StringType

    data = [
        (1, ["<b>bold</b>", "normal text"]),
        (2, ["<p>para</p>", None, "text"]),
    ]
    df = spark.createDataFrame(data, ["id", "descriptions"])

    normalizer = HtmlNormalizer()
    result = normalizer.process(df, text_column="descriptions")

    # 验证结果
    row1 = result.filter("id = 1").first()
    assert "<b>" not in row1.descriptions[0]
    assert "bold" in row1.descriptions[0]


def test_html_normalizer_column_not_exists(spark):
    """测试列不存在"""
    df = create_text_df(spark)

    normalizer = HtmlNormalizer()
    result = normalizer.process(df, text_column="non_existent")

    assert result.count() == df.count()


def test_html_normalizer_null_handling(spark):
    """测试 null 值处理"""
    data = [
        (1, None),
        (2, "<b>text</b>"),
    ]
    df = spark.createDataFrame(data, ["id", "text"])

    normalizer = HtmlNormalizer()
    result = normalizer.process(df, text_column="text")

    # null 值应该被保留
    texts = [row.text for row in result.orderBy("id").collect()]
    assert texts[0] is None
    assert texts[1] is not None