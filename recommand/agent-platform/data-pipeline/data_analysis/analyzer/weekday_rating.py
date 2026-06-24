#!/usr/bin/env python3
"""
深度分析器 - 按星期评分分布
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class WeekdayRatingAnalyzer(BaseAnalyzer):
    """按星期评分分布分析器"""

    @property
    def name(self) -> str:
        return "[10.3] 评分按星期分布"

    @property
    def output_file(self) -> str:
        return "12_weekday_rating"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        weekday_rating = reviews_df.groupBy("review_weekday").agg(
            F.avg("rating").alias("avg_rating"),
            F.count("*").alias("review_count")
        )

        # 排序
        return weekday_rating.withColumn(
            "sort_order",
            F.when(F.col("review_weekday") == "Monday", 1)
            .when(F.col("review_weekday") == "Tuesday", 2)
            .when(F.col("review_weekday") == "Wednesday", 3)
            .when(F.col("review_weekday") == "Thursday", 4)
            .when(F.col("review_weekday") == "Friday", 5)
            .when(F.col("review_weekday") == "Saturday", 6)
            .when(F.col("review_weekday") == "Sunday", 7)
        ).orderBy("sort_order").drop("sort_order")


# 注册到工厂
AnalyzerFactory.register('weekday_rating', WeekdayRatingAnalyzer)
