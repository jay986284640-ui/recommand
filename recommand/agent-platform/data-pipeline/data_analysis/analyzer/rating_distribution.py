#!/usr/bin/env python3
"""
基础分析器 - 商品平均分分布
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class RatingDistributionAnalyzer(BaseAnalyzer):
    """商品平均分分布分析器"""

    @property
    def name(self) -> str:
        return "统计商品平均分分布"

    @property
    def output_file(self) -> str:
        return "5_rating_distribution"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        # 计算每个商品的平均分
        product_avg_rating = reviews_df.groupBy("parent_asin").agg(
            F.avg("rating").alias("avg_rating")
        )

        # 对平均分进行分桶统计
        return product_avg_rating.withColumn(
            "rating_bucket",
            F.floor(F.col("avg_rating") * 2) / 2  # 0.5分桶
        ).groupBy("rating_bucket").agg(
            F.count("*").alias("product_count")
        ).orderBy("rating_bucket")


# 注册到工厂
AnalyzerFactory.register('rating_distribution', RatingDistributionAnalyzer)
