# -*- coding: utf-8 -*-
"""商品存在性过滤器测试"""

import pytest
from cleaning.product_exists_filter import ProductExistsFilter
from tests.fixtures.sample_data import (
    create_product_exists_df,
    create_items_for_product_exists_df
)


def test_product_exists_filter(spark):
    """测试商品存在性过滤"""
    interactions_df = create_product_exists_df(spark)
    items_df = create_items_for_product_exists_df(spark)

    before_count = interactions_df.count()  # 5 条
    assert before_count == 5

    filter_obj = ProductExistsFilter(items_df=items_df)
    result = filter_obj.filter(interactions_df)

    after_count = result.count()

    # item1, item2 在物品表中，保留
    # item3, item4 不在物品表中，过滤
    # 保留: user1-item1, user1-item2, user2-item1 = 3 条
    assert after_count == 3


def test_product_exists_filter_no_items_df(spark):
    """测试未提供物品数据"""
    interactions_df = create_product_exists_df(spark)

    filter_obj = ProductExistsFilter(items_df=None)
    result = filter_obj.filter(interactions_df)

    # 未提供物品数据，不过滤
    assert result.count() == interactions_df.count()


def test_product_exists_filter_no_item_id(spark):
    """测试交互数据中没有 item_id 列"""
    data = [
        ("user1", "review1"),
        ("user2", "review2"),
    ]
    df = spark.createDataFrame(data, ["user_id", "review_text"])

    items_df = create_items_for_product_exists_df(spark)

    filter_obj = ProductExistsFilter(items_df=items_df)
    result = filter_obj.filter(df)

    # 列不存在，不过滤
    assert result.count() == 2


def test_product_exists_filter_disabled():
    """测试禁用过滤器"""
    filter_obj = ProductExistsFilter(enabled=False)
    # 禁用后不过滤
    assert filter_obj.enabled is False