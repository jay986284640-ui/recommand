#!/usr/bin/env python3
"""检测器 - 单品时间突刺(运营行为最强信号)

秒杀 / 抢券 会让某个商品的交互在极短时间窗口内爆发。按固定时间桶(小时/天)
聚合每个商品的交互,计算:
- busiest_bucket_count : 最忙桶的交互数
- spike_ratio          : 最忙桶 / 平均桶(= busiest * n_buckets / total)
- top_bucket_share     : 最忙桶 / 总交互
命中(spike_ratio 高且量足)或(单桶占比过高)即判为突刺。

timestamp 为 unix 秒;用整除分桶,规避时区问题。
"""

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class ItemTimeBurstAnalyzer(BaseAnalyzer):
    """单品时间突刺分析器"""

    @property
    def name(self) -> str:
        return "单品时间突刺(秒杀/抢券)"

    @property
    def output_file(self) -> str:
        return "item_time_burst"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        bucket = str(self.config.get("bucket", "hour")).lower()
        bucket_seconds = 86400 if bucket == "day" else 3600
        spike_threshold = float(self.config.get("spike_ratio_threshold", 5.0))
        min_burst_count = int(self.config.get("min_burst_count", 100))
        top_share_threshold = float(self.config.get("top_bucket_share_threshold", 0.5))

        bucketed = reviews_df.withColumn(
            "bucket", (F.col("timestamp") / F.lit(bucket_seconds)).cast("long")
        )

        per_bucket = bucketed.groupBy("item_id", "bucket").agg(
            F.count("*").alias("bucket_count")
        )

        per_item = per_bucket.groupBy("item_id").agg(
            F.sum("bucket_count").alias("interaction_count"),
            F.max("bucket_count").alias("busiest_bucket_count"),
            F.countDistinct("bucket").alias("active_buckets"),
        )

        per_item = per_item.withColumn(
            "spike_ratio",
            F.when(
                F.col("interaction_count") > 0,
                F.col("busiest_bucket_count")
                * F.col("active_buckets")
                / F.col("interaction_count"),
            ).otherwise(F.lit(0.0)),
        ).withColumn(
            "top_bucket_share",
            F.when(
                F.col("interaction_count") > 0,
                F.col("busiest_bucket_count") / F.col("interaction_count"),
            ).otherwise(F.lit(0.0)),
        )

        per_item = per_item.withColumn(
            "flag_burst",
            (
                (F.col("spike_ratio") >= F.lit(spike_threshold))
                & (F.col("busiest_bucket_count") >= F.lit(min_burst_count))
            )
            | (
                (F.col("top_bucket_share") >= F.lit(top_share_threshold))
                & (F.col("busiest_bucket_count") >= F.lit(min_burst_count))
            ),
        )

        return per_item.orderBy(F.desc("busiest_bucket_count"))


AnalyzerFactory.register("item_time_burst", ItemTimeBurstAnalyzer)
