#!/usr/bin/env python3
"""
深度分析器 - Helpfulness Vote 分布分析
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class HelpfulVoteAnalyzer(BaseAnalyzer):
    """Helpfulness Vote 分布分析器"""

    @property
    def name(self) -> str:
        return "[10.8] Helpfulness Vote 分布分析"

    @property
    def output_file(self) -> str:
        return "17_helpful_vote_analysis"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        return reviews_df.groupBy("helpful_vote").agg(
            F.avg("rating").alias("avg_rating"),
            F.count("*").alias("review_count")
        ).orderBy("helpful_vote")


# 注册到工厂
AnalyzerFactory.register('helpful_vote_analysis', HelpfulVoteAnalyzer)
