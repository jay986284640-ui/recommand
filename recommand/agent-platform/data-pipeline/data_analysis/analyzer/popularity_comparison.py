#!/usr/bin/env python3
"""
深度分析器 - 热门商品 vs 冷门商品评分对比
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class PopularityComparisonAnalyzer(BaseAnalyzer):
    """热门 vs 冷门商品分析器"""

    @property
    def name(self) -> str:
        return "[10.9] 热门商品 vs 冷门商品评分对比"

    @property
    def output_file(self) -> str:
        return "18_popularity_rating_comparison"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        # 计算每个商品的评论数
        product_counts = reviews_df.groupBy("parent_asin").agg(
            F.count("*").alias("review_count"),
            F.avg("rating").alias("avg_rating")
        )

        # 计算中位数评论数
        median_reviews = product_counts.agg(F.expr("approx_percentile(review_count, 0.5)")).collect()[0][0]

        # 标记热门程度
        product_counts = product_counts.withColumn(
            "popularity",
            F.when(F.col("review_count") >= median_reviews, "Popular").otherwise("Niche")
        )

        return product_counts.groupBy("popularity").agg(
            F.avg("avg_rating").alias("overall_avg_rating"),
            F.avg("review_count").alias("avg_review_count"),
            F.count("*").alias("product_count")
        )


# 注册到工厂
AnalyzerFactory.register('popularity_comparison', PopularityComparisonAnalyzer)
