#!/usr/bin/env python3
"""
深度分析器 - 评分分布随时间变化
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class MonthlyRatingDistributionAnalyzer(BaseAnalyzer):
    """评分分布随时间变化分析器"""

    @property
    def name(self) -> str:
        return "[10.10] 评分分布随时间变化"

    @property
    def output_file(self) -> str:
        return "19_monthly_rating_distribution"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        return reviews_df.groupBy("review_year_month", "rating").agg(
            F.count("*").alias("count")
        ).orderBy("review_year_month", "rating")


# 注册到工厂
AnalyzerFactory.register('monthly_rating_distribution', MonthlyRatingDistributionAnalyzer)
