"""异常值过滤器"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from datetime import datetime

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base_filter import BaseFilter


class OutlierFilter(BaseFilter):
    """异常值过滤 - 评分和时间戳异常"""

    def __init__(self, min_rating: float = 1.0, max_rating: float = 5.0, min_year: int = 1990):
        super().__init__("异常值过滤 (评分、时间)")
        self.min_rating = min_rating
        self.max_rating = max_rating
        self.min_timestamp = int(datetime(min_year, 1, 1).timestamp())
        self.max_timestamp = int(datetime.now().timestamp())

    def filter(self, df: DataFrame) -> DataFrame:
        """过滤评分和时间戳异常的记录"""
        # 评分异常：评分必须在1-5之间
        # 时间戳异常：检查时间戳是否在合理范围内
        return df.filter(
            (F.col("rating").isNotNull()) &
            (F.col("rating") >= self.min_rating) &
            (F.col("rating") <= self.max_rating) &
            (F.col("timestamp") >= self.min_timestamp) &
            (F.col("timestamp") <= self.max_timestamp)
        )
