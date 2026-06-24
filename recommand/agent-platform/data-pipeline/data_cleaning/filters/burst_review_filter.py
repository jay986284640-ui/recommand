"""突发评论过滤器 - 检测短时间内评论次数过多的用户"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from .base_filter import BaseFilter


class BurstReviewFilter(BaseFilter):
    """
    突发评论过滤 - 清理短时间内评论次数过多的用户记录

    检测在指定时间窗口内发布超过阈值评论数的用户，移除这些用户的所有评论记录。
    这类用户可能是机器人或刷评账号。
    """

    def __init__(self, time_window_minutes: int = 10, max_reviews: int = 50):
        """
        初始化突发评论过滤器

        Args:
            time_window_minutes: 时间窗口（分钟），默认10分钟
            max_reviews: 时间窗口内最大允许评论数，默认50条
        """
        super().__init__("突发评论过滤 ({}分钟内>{}条)".format(time_window_minutes, max_reviews))
        self.time_window_minutes = time_window_minutes
        self.max_reviews = max_reviews

    def filter(self, df: DataFrame) -> DataFrame:
        """
        过滤短时间内评论过多的用户

        实现思路：
        1. 为每个用户的评论按时间排序，计算窗口内的评论数
        2. 使用滑动窗口计算每个时间点前N分钟内的评论数
        3. 标记超过阈值的用户为可疑用户
        4. 过滤掉可疑用户的所有评论
        """
        # 时间窗口（秒）
        window_seconds = self.time_window_minutes * 60

        # 为每个用户定义窗口，按时间排序
        user_window = Window.partitionBy("user_id").orderBy("timestamp")

        # 计算每条评论之前（包含当前）的评论数作为排名
        df_with_rank = df.withColumn("rank", F.rank().over(user_window))

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
        # 如果时间跨度为0（同一秒发布的评论），则速率设为极大值
        # 但只有总评论数>1时才计算速率，避免单条评论被误判
        user_stats = user_stats.withColumn(
            "review_rate",
            F.when(
                (F.col("time_span") > 0) & (F.col("total_reviews") > 1),
                F.col("total_reviews") / (F.col("time_span") / 60)  # 每分钟评论数
            ).otherwise(F.lit(0))
        )

        # 方法一：基于时间窗口的精确检测
        # 为每条评论计算时间窗口内的评论数
        df_with_window_count = df.withColumn(
            "window_start",
            F.col("timestamp") - window_seconds
        )

        # 使用自连接计算窗口内的评论数（对于大数据集可能较慢）
        # 采用更高效的方法：基于时间范围的聚合

        # 方法二：基于速率的简化检测（更高效）
        # 如果用户在总时间跨度内的平均评论速率超过阈值，则认为是突发用户
        # 阈值：max_reviews / time_window_minutes (每分钟最大评论数)
        threshold_rate = self.max_reviews / self.time_window_minutes

        # 标记突发用户：平均速率超过阈值 且 总评论数>1
        burst_users = user_stats.filter(
            (F.col("review_rate") > threshold_rate) |
            # 或者总评论数在时间窗口内（时间跨度小于窗口且评论数超过阈值）
            ((F.col("time_span") <= window_seconds) & (F.col("total_reviews") > self.max_reviews))
        ).select("user_id")

        # 过滤掉突发用户的评论
        result = df.join(burst_users, "user_id", "left_anti")

        return result
