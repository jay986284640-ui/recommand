#!/usr/bin/env python3
"""检测器 - 用户高频/异常速度

刷单/机器/运营账号的典型特征:单日或极短窗口内交互商品数量畸多。
按用户聚合:
- total            : 总交互
- distinct_items   : 去重商品数
- active_days      : 活跃天数
- max_daily        : 单日最大交互数
- max_hourly       : 单小时最大交互数
命中任一硬阈值即判为异常用户。

timestamp 为 unix 秒,用整除分桶(天/小时)。
"""

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class UserVelocityAnomalyAnalyzer(BaseAnalyzer):
    """用户高频异常分析器"""

    @property
    def name(self) -> str:
        return "用户高频/异常速度(单日/短窗交互量)"

    @property
    def output_file(self) -> str:
        return "user_velocity_anomaly"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        max_daily_threshold = int(self.config.get("max_daily_threshold", 100))
        max_hourly_threshold = int(self.config.get("max_hourly_threshold", 50))
        min_total = int(self.config.get("min_total", 1))

        df = reviews_df.withColumn(
            "day", (F.col("timestamp") / F.lit(86400)).cast("long")
        ).withColumn("hour", (F.col("timestamp") / F.lit(3600)).cast("long"))

        # 单日 / 单小时计数
        daily = df.groupBy("user_id", "day").agg(F.count("*").alias("c"))
        max_daily = daily.groupBy("user_id").agg(F.max("c").alias("max_daily"))

        hourly = df.groupBy("user_id", "hour").agg(F.count("*").alias("c"))
        max_hourly = hourly.groupBy("user_id").agg(F.max("c").alias("max_hourly"))

        base = df.groupBy("user_id").agg(
            F.count("*").alias("total"),
            F.countDistinct("item_id").alias("distinct_items"),
            F.countDistinct("day").alias("active_days"),
        )

        result = (
            base.join(max_daily, "user_id", "left")
            .join(max_hourly, "user_id", "left")
            .na.fill({"max_daily": 0, "max_hourly": 0})
        )

        result = result.withColumn(
            "flag_user_velocity",
            (F.col("total") >= F.lit(min_total))
            & (
                (F.col("max_daily") >= F.lit(max_daily_threshold))
                | (F.col("max_hourly") >= F.lit(max_hourly_threshold))
            ),
        )

        return result.orderBy(F.desc("max_daily"))


AnalyzerFactory.register("user_velocity_anomaly", UserVelocityAnomalyAnalyzer)
