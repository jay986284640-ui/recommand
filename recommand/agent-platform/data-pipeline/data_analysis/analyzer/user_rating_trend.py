#!/usr/bin/env python3
"""
深度分析器 - 用户评分趋势分析
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class UserRatingTrendAnalyzer(BaseAnalyzer):
    """用户评分趋势分析器"""

    @property
    def name(self) -> str:
        return "[10.7] 用户评分趋势分析"

    @property
    def output_file(self) -> str:
        return "16_user_rating_trend"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        # 找出发表过多条评论的用户
        user_review_counts = reviews_df.groupBy("user_id").agg(
            F.count("*").alias("total_reviews")
        )
        prolific_users = user_review_counts.filter(F.col("total_reviews") >= 2).select("user_id")

        # 对这些用户的评论按时间排序并计算评分变化
        prolific_reviews = reviews_df.join(prolific_users, "user_id")

        # 使用窗口函数计算每个用户第N条评论的平均评分
        order_window = Window.partitionBy("user_id").orderBy("timestamp")
        prolific_reviews = prolific_reviews.withColumn(
            "review_number",
            F.row_number().over(order_window)
        )

        # 按第N条评论统计平均评分
        return prolific_reviews.groupBy("review_number").agg(
            F.avg("rating").alias("avg_rating"),
            F.count("*").alias("review_count")
        ).filter(F.col("review_number") <= 10).orderBy("review_number")


# 注册到工厂
AnalyzerFactory.register('user_rating_trend', UserRatingTrendAnalyzer)
