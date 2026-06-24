#!/usr/bin/env python3
"""
深度分析器 - 验证购买 vs 非验证购买评分对比
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class VerifiedPurchaseAnalyzer(BaseAnalyzer):
    """验证购买分析器"""

    @property
    def name(self) -> str:
        return "[10.1] 验证购买 vs 非验证购买评分分析"

    @property
    def output_file(self) -> str:
        return "10_verified_purchase_comparison"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        verified_comparison = reviews_df.groupBy("is_verified").agg(
            F.avg("rating").alias("avg_rating"),
            F.count("*").alias("review_count"),
            F.expr("approx_percentile(rating, 0.5)").alias("median_rating"),
            F.stddev("rating").alias("stddev_rating")
        )
        return verified_comparison.withColumn(
            "purchase_type",
            F.when(F.col("is_verified") == True, "Verified Purchase").otherwise("Non-Verified")
        )


# 注册到工厂
AnalyzerFactory.register('verified_purchase_comparison', VerifiedPurchaseAnalyzer)
