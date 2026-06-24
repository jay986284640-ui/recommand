#!/usr/bin/env python3
"""
深度分析器 - 评论长度与评分相关性分析
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class LengthByRatingAnalyzer(BaseAnalyzer):
    """评论长度与评分相关性分析器"""

    @property
    def name(self) -> str:
        return "[10.4] 评论长度与评分相关性分析"

    @property
    def output_file(self) -> str:
        return "13_length_by_rating"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        return reviews_df.groupBy("rating").agg(
            F.avg("review_text_length").alias("avg_text_length"),
            F.avg("review_title_length").alias("avg_title_length"),
            F.count("*").alias("review_count")
        ).orderBy("rating")


# 注册到工厂
AnalyzerFactory.register('length_by_rating', LengthByRatingAnalyzer)
