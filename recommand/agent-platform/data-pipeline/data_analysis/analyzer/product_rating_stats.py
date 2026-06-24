#!/usr/bin/env python3
"""
基础分析器 - 每个商品的评分统计
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class ProductRatingStatsAnalyzer(BaseAnalyzer):
    """商品评分统计分析器"""

    @property
    def name(self) -> str:
        return "统计每个商品的评分统计"

    @property
    def output_file(self) -> str:
        return "3_product_rating_stats"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        return reviews_df.groupBy("parent_asin").agg(
            F.max("rating").alias("max_rating"),
            F.min("rating").alias("min_rating"),
            F.avg("rating").alias("avg_rating"),
            F.count("rating").alias("rating_count"),
            F.expr("approx_percentile(rating, 0.5)").alias("median_rating")
        ).orderBy(F.desc("rating_count"))


# 注册到工厂
AnalyzerFactory.register('product_rating_stats', ProductRatingStatsAnalyzer)
