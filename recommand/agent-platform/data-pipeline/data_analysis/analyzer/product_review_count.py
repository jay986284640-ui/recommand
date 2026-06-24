#!/usr/bin/env python3
"""
基础分析器 - 每个商品的评论数量
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class ProductReviewCountAnalyzer(BaseAnalyzer):
    """商品评论数量分析器"""

    @property
    def name(self) -> str:
        return "统计每个商品的评论数量"

    @property
    def output_file(self) -> str:
        return "2_product_review_count"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        return reviews_df.groupBy("parent_asin").agg(
            F.count("*").alias("review_count")
        ).orderBy(F.desc("review_count"))


# 注册到工厂
AnalyzerFactory.register('product_review_count', ProductReviewCountAnalyzer)
