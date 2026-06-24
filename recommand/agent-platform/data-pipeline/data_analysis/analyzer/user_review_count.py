#!/usr/bin/env python3
"""
基础分析器 - 每个用户发表的评论数量
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class UserReviewCountAnalyzer(BaseAnalyzer):
    """用户评论数量分析器"""

    @property
    def name(self) -> str:
        return "统计每个用户的评论数量"

    @property
    def output_file(self) -> str:
        return "1_user_review_count"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        return reviews_df.groupBy("user_id").agg(
            F.count("*").alias("review_count")
        ).orderBy(F.desc("review_count"))


# 注册到工厂
AnalyzerFactory.register('user_review_count', UserReviewCountAnalyzer)
