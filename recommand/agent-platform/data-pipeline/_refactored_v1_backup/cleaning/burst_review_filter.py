"""突发评论过滤器"""

import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class BurstReviewFilter(BaseFilter):
    """过滤短时间窗口内评论过频的刷评/机器人用户"""

    def __init__(self, time_window_minutes: int = 10, max_reviews: int = 50, enabled: bool = True):
        super().__init__(f"突发评论过滤 ({time_window_minutes}分钟内>{max_reviews}条)", enabled)
        self.time_window_minutes = time_window_minutes
        self.max_reviews = max_reviews

    def filter(self, df: DataFrame) -> DataFrame:
        if "user_id" not in df.columns or "timestamp" not in df.columns:
            logger.warning("user_id 或 timestamp 列不存在,跳过突发评论过滤")
            return df

        window_seconds = self.time_window_minutes * 60
        user_stats = df.groupBy("user_id").agg(
            F.count("*").alias("total_reviews"),
            F.min("timestamp").alias("min_timestamp"),
            F.max("timestamp").alias("max_timestamp"),
        )
        user_stats = user_stats.withColumn("time_span", F.col("max_timestamp") - F.col("min_timestamp"))
        user_stats = user_stats.withColumn(
            "review_rate",
            F.when(
                (F.col("time_span") > 0) & (F.col("total_reviews") > 1),
                F.col("total_reviews") / (F.col("time_span") / 60),
            ).otherwise(F.lit(0)),
        )
        threshold_rate = self.max_reviews / self.time_window_minutes
        burst_users = user_stats.filter(
            (F.col("review_rate") > threshold_rate)
            | ((F.col("time_span") <= window_seconds) & (F.col("total_reviews") > self.max_reviews))
        ).select("user_id")
        return df.join(burst_users, "user_id", "left_anti")
