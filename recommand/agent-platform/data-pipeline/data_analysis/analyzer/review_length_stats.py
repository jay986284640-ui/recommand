#!/usr/bin/env python3
"""
基础分析器 - 评论长度统计
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class ReviewLengthStatsAnalyzer(BaseAnalyzer):
    """评论长度统计分析器"""

    @property
    def name(self) -> str:
        return "统计评论长度"

    @property
    def output_file(self) -> str:
        return "6_review_length_stats"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        return reviews_df.groupBy("parent_asin").agg(
            F.avg("review_text_length").alias("avg_review_length"),
            F.max("review_text_length").alias("max_review_length"),
            F.min("review_text_length").alias("min_review_length"),
            F.count("review_text_length").alias("review_count")
        ).orderBy(F.desc("review_count"))


# 注册到工厂
AnalyzerFactory.register('review_length_stats', ReviewLengthStatsAnalyzer)
