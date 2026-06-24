#!/usr/bin/env python3
"""
深度分析器 - 商品评论数长尾分布
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class ProductReviewTailAnalyzer(BaseAnalyzer):
    """商品评论数长尾分布分析器"""

    @property
    def name(self) -> str:
        return "[10.6] 商品评论数长尾分布"

    @property
    def output_file(self) -> str:
        return "15_product_review_tail"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        product_review_dist = reviews_df.groupBy("parent_asin").agg(
            F.count("*").alias("review_count")
        )

        # 按评论数分桶
        product_review_dist = product_review_dist.withColumn(
            "count_bucket",
            F.when(F.col("review_count") == 1, "1")
            .when(F.col("review_count") <= 3, "2-3")
            .when(F.col("review_count") <= 10, "4-10")
            .when(F.col("review_count") <= 50, "11-50")
            .when(F.col("review_count") <= 100, "51-100")
            .otherwise("100+")
        )

        return product_review_dist.groupBy("count_bucket").agg(
            F.count("*").alias("product_count")
        ).withColumn(
            "bucket_order",
            F.when(F.col("count_bucket") == "1", 1)
            .when(F.col("count_bucket") == "2-3", 2)
            .when(F.col("count_bucket") == "4-10", 3)
            .when(F.col("count_bucket") == "11-50", 4)
            .when(F.col("count_bucket") == "51-100", 5)
            .otherwise(6)
        ).orderBy("bucket_order").drop("bucket_order")


# 注册到工厂
AnalyzerFactory.register('product_review_tail', ProductReviewTailAnalyzer)
