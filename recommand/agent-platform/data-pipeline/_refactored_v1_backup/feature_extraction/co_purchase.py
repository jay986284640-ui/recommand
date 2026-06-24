"""共购信息(同用户同时段共购的 item 对)

产出 co_purchase:
- item_id
- co_items: array<struct<related_item_id, co_count, co_weight>>  按 co_count 降序
"""

import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window


logger = logging.getLogger(__name__)


def build_co_purchase(
    interactions_df: DataFrame,
    window_days: int = 30,
) -> DataFrame:
    """按 (user, 时间窗口内) 自连接出 item 对,再按 item_id 聚合"""
    if "timestamp" not in interactions_df.columns:
        logger.warning("interactions 没有 timestamp,无法构建共购,返回空")
        return interactions_df.sparkSession.createDataFrame(
            [], "item_id STRING, co_items ARRAY<STRUCT<related_item_id: STRING, co_count: LONG, co_weight: DOUBLE>>"
        )

    window_sec = window_days * 86400
    a = interactions_df.select(
        F.col("user_id"),
        F.col("item_id").alias("a_id"),
        F.col("timestamp").alias("a_ts"),
    )
    b = interactions_df.select(
        F.col("user_id"),
        F.col("item_id").alias("b_id"),
        F.col("timestamp").alias("b_ts"),
    )
    pairs = (
        a.join(b, on="user_id", how="inner")
        .filter((F.col("a_id") != F.col("b_id")) & ((F.col("a_ts") - F.col("b_ts")).between(-window_sec, window_sec)))
        .select(F.col("a_id").alias("item_id"), F.col("b_id").alias("related_item_id"))
    )
    counts = pairs.groupBy("item_id", "related_item_id").agg(F.count("*").alias("co_count"))
    # 共购权重 = 1 / log10(全局商品热度 + 1),把长尾商品的共购信号放大
    item_pop = interactions_df.groupBy("item_id").agg(F.count("*").alias("pop"))
    counts = counts.join(item_pop, on="item_id", how="left")
    counts = counts.withColumn("co_weight", 1.0 / F.log10(F.col("pop") + F.lit(10)))
    counts = counts.drop("pop")

    # 取每个 item 的 Top-50 共购 item
    w = Window.partitionBy("item_id").orderBy(F.desc("co_count"))
    ranked = counts.withColumn("rk", F.row_number().over(w)).filter(F.col("rk") <= 50)
    entry = F.struct(
        F.col("related_item_id"),
        F.col("co_count"),
        F.col("co_weight"),
    )
    grouped = ranked.groupBy("item_id").agg(F.collect_list(entry).alias("co_items"))
    logger.info("共购信息产出: %d 行 (window=%d天)", grouped.count(), window_days)
    return grouped
