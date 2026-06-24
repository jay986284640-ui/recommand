#!/usr/bin/env python3
"""
基础分析器 - 评论标题长度统计
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class TitleLengthStatsAnalyzer(BaseAnalyzer):
    """评论标题长度统计分析器"""

    @property
    def name(self) -> str:
        return "统计评论标题长度"

    @property
    def output_file(self) -> str:
        return "7_title_length_stats"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        return reviews_df.groupBy("parent_asin").agg(
            F.avg("review_title_length").alias("avg_title_length"),
            F.max("review_title_length").alias("max_title_length"),
            F.min("review_title_length").alias("min_title_length"),
            F.count("review_title_length").alias("review_count")
        ).orderBy(F.desc("review_count"))


# 注册到工厂
AnalyzerFactory.register('title_length_stats', TitleLengthStatsAnalyzer)
