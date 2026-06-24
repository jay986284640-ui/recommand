#!/usr/bin/env python3
"""
深度分析器 - 用户首次评论 vs 后续评论评分对比
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class FirstVsSubsequentAnalyzer(BaseAnalyzer):
    """首次 vs 后续评论分析器"""

    @property
    def name(self) -> str:
        return "[10.2] 用户首次评论 vs 后续评论评分对比"

    @property
    def output_file(self) -> str:
        return "11_first_vs_subsequent_review"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        # 为每个用户的评论按时间排序，标记是第几条评论
        window_spec = Window.partitionBy("user_id").orderBy("timestamp")
        reviews_with_order = reviews_df.withColumn(
            "review_order",
            F.row_number().over(window_spec)
        )

        # 首次评论 vs 非首次评论
        return reviews_with_order.withColumn(
            "is_first_review",
            F.when(F.col("review_order") == 1, "First Review").otherwise("Subsequent Review")
        ).groupBy("is_first_review").agg(
            F.avg("rating").alias("avg_rating"),
            F.count("*").alias("review_count"),
            F.expr("approx_percentile(rating, 0.5)").alias("median_rating")
        )


# 注册到工厂
AnalyzerFactory.register('first_vs_subsequent_review', FirstVsSubsequentAnalyzer)
