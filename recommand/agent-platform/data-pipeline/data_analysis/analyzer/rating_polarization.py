#!/usr/bin/env python3
"""
深度分析器 - 评分两极分化分析
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class RatingPolarizationAnalyzer(BaseAnalyzer):
    """评分两极分化分析器"""

    @property
    def name(self) -> str:
        return "[10.5] 评分两极分化分析"

    @property
    def output_file(self) -> str:
        return "14_rating_polarization"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        rating_polarization = reviews_df.groupBy("rating").agg(
            F.count("*").alias("count")
        )
        total = reviews_df.count()
        rating_polarization = rating_polarization.withColumn(
            "percentage",
            F.col("count") / total * 100
        )
        rating_polarization = rating_polarization.withColumn(
            "category",
            F.when(F.col("rating") == 1, "1-Star (Negative)")
            .when(F.col("rating") == 5, "5-Star (Positive)")
            .otherwise("Middle (2-4 Stars)")
        )

        return rating_polarization.groupBy("category").agg(
            F.sum("count").alias("count"),
            F.sum("percentage").alias("percentage")
        ).orderBy(F.desc("count"))


# 注册到工厂
AnalyzerFactory.register('rating_polarization', RatingPolarizationAnalyzer)
