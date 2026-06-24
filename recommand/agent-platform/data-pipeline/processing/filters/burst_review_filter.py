"""突发评论过滤器"""

import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class BurstReviewFilter(BaseFilter):
    """
    突发评论过滤 - 清理短时间内评论次数过多的用户记录

    检测在指定时间窗口内发布超过阈值评论数的用户，移除这些用户的所有评论记录。
    这类用户可能是机器人或刷评账号。
    """

    def __init__(self, time_window_minutes: int = 10, max_reviews: int = 50, enabled: bool = True):
        """
        初始化突发评论过滤器

        Args:
            time_window_minutes: 时间窗口（分钟），默认10分钟
            max_reviews: 时间窗口内最大允许评论数，默认50条
            enabled: 是否启用
        """
        super().__init__("突发评论过滤 ({}分钟内>{}条)".format(time_window_minutes, max_reviews), enabled)
        self.time_window_minutes = time_window_minutes
        self.max_reviews = max_reviews

    def filter(self, df: DataFrame) -> DataFrame:
        """过滤短时间内评论过多的用户"""
        if "user_id" not in df.columns or "timestamp" not in df.columns:
            logger.warning("user_id 或 timestamp 列不存在，跳过突发评论过滤")
            return df

        # 时间窗口（秒）
        window_seconds = self.time_window_minutes * 60

        # 计算每个用户的评论总数和最小/最大时间戳
        user_stats = df.groupBy("user_id").agg(
            F.count("*").alias("total_reviews"),
            F.min("timestamp").alias("min_timestamp"),
            F.max("timestamp").alias("max_timestamp")
        )

        # 计算用户的时间跨度（秒）
        user_stats = user_stats.withColumn(
            "time_span",
            F.col("max_timestamp") - F.col("min_timestamp")
        )

        # 计算平均评论速率（评论数/时间跨度）
        user_stats = user_stats.withColumn(
            "review_rate",
            F.when(
                (F.col("time_span") > 0) & (F.col("total_reviews") > 1),
                F.col("total_reviews") / (F.col("time_span") / 60)  # 每分钟评论数
            ).otherwise(F.lit(0))
        )

        # 阈值：max_reviews / time_window_minutes (每分钟最大评论数)
        threshold_rate = self.max_reviews / self.time_window_minutes

        # 标记突发用户
        burst_users = user_stats.filter(
            (F.col("review_rate") > threshold_rate) |
            ((F.col("time_span") <= window_seconds) & (F.col("total_reviews") > self.max_reviews))
        ).select("user_id")

        # 过滤掉突发用户的评论
        return df.join(burst_users, "user_id", "left_anti")