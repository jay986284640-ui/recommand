"""异常值过滤器(评分 + 时间戳)"""

import logging
from datetime import datetime
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class OutlierFilter(BaseFilter):
    """过滤评分和时间戳异常的记录"""

    def __init__(self, min_rating: float = 1.0, max_rating: float = 5.0, min_year: int = 1990, enabled: bool = True):
        super().__init__(f"异常值过滤 (评分 {min_rating}-{max_rating}, 时间 >= {min_year})", enabled)
        self.min_rating = min_rating
        self.max_rating = max_rating
        self.min_timestamp = int(datetime(min_year, 1, 1).timestamp())

    def filter(self, df: DataFrame) -> DataFrame:
        condition = F.lit(True)
        if "rating" in df.columns:
            condition = condition & (
                F.col("rating").isNotNull()
                & (F.col("rating") >= self.min_rating)
                & (F.col("rating") <= self.max_rating)
            )
        if "timestamp" in df.columns:
            condition = condition & (F.col("timestamp") >= self.min_timestamp)
        if condition == F.lit(True):
            logger.warning("rating 和 timestamp 列都不存在,跳过异常值过滤")
            return df
        return df.filter(condition)
