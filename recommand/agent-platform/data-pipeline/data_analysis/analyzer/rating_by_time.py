#!/usr/bin/env python3
"""
基础分析器 - 评分随时间变化
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class RatingByTimeAnalyzer(BaseAnalyzer):
    """评分时间变化分析器"""

    @property
    def name(self) -> str:
        return "统计评分随时间变化"

    @property
    def output_file(self) -> str:
        return "4_rating_by_time"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        return reviews_df.groupBy("review_year_month").agg(
            F.avg("rating").alias("avg_rating"),
            F.count("*").alias("review_count"),
            F.max("rating").alias("max_rating"),
            F.min("rating").alias("min_rating")
        ).orderBy("review_year_month")


# 注册到工厂
AnalyzerFactory.register('rating_by_time', RatingByTimeAnalyzer)
