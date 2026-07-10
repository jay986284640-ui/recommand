#!/usr/bin/env python3
"""检测器 - 单品热度异常

标记交互量畸高、或 "交互数/去重用户数" 比值畸高的商品(运营爆款 / 刷量的典型特征)。

输入: reviews_df = 标准交互(user_id/item_id/timestamp/action ...)
输出(每 item 一行): item_id, interaction_count, distinct_users,
                     interaction_per_user, flag_popularity
"""

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class ItemPopularityAnomalyAnalyzer(BaseAnalyzer):
    """单品热度异常分析器"""

    @property
    def name(self) -> str:
        return "单品热度异常(交互量长尾 / 交互-用户比)"

    @property
    def output_file(self) -> str:
        return "item_popularity_anomaly"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        # 阈值配置
        pct = float(self.config.get("popularity_pct", 0.99))
        min_hot = int(self.config.get("min_interactions_for_hot", 500))
        ratio_threshold = float(self.config.get("interaction_per_user_threshold", 3.0))

        per_item = reviews_df.groupBy("item_id").agg(
            F.count("*").alias("interaction_count"),
            F.countDistinct("user_id").alias("distinct_users"),
        )
        per_item = per_item.withColumn(
            "interaction_per_user",
            F.when(
                F.col("distinct_users") > 0,
                F.col("interaction_count") / F.col("distinct_users"),
            ).otherwise(F.lit(0.0)),
        )

        # 全局分位数阈值(交互量)
        hot_cut = per_item.agg(
            F.expr(f"approx_percentile(interaction_count, {pct})")
        ).first()[0]
        hot_cut = max(hot_cut or 0, min_hot)

        per_item = per_item.withColumn(
            "flag_popularity",
            (F.col("interaction_count") >= F.lit(hot_cut))
            | (F.col("interaction_per_user") >= F.lit(ratio_threshold)),
        )

        return per_item.orderBy(F.desc("interaction_count"))


AnalyzerFactory.register("item_popularity_anomaly", ItemPopularityAnomalyAnalyzer)
