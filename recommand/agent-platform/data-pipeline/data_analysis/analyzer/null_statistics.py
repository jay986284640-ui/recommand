#!/usr/bin/env python3
"""
基础分析器 - 空值占比统计
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class NullStatisticsAnalyzer(BaseAnalyzer):
    """空值占比统计分析器"""

    @property
    def name(self) -> str:
        return "统计各字段空值占比"

    @property
    def output_file(self) -> str:
        return "8_null_statistics"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        total_count = reviews_df.count()

        null_stats = []
        for col_name in reviews_df.columns:
            null_count = reviews_df.filter(
                F.col(col_name).isNull() | (F.col(col_name) == "")
            ).count()
            null_ratio = null_count / total_count * 100 if total_count > 0 else 0
            null_stats.append({
                "field": col_name,
                "null_count": null_count,
                "null_ratio": f"{null_ratio:.2f}%"
            })

        return self.spark.createDataFrame(null_stats)


# 注册到工厂
AnalyzerFactory.register('null_statistics', NullStatisticsAnalyzer)
