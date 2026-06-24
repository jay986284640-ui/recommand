"""商品特征提取

产出 item_features:
- item_id
- content_type(meituan_coupon / self_operated_coupon / local_payment / external_coupon / amazon / ...)
- 关联门店字段(category / lat / lng ...)
- interaction_count(被多少用户交互过)
- buyer_count(去重用户数)
- avg_rating(若有 rating 字段)
- first_seen_ts / last_seen_ts(首次/最后被交互)
- is_cold(交互数 < cold_threshold 视为冷启动)
"""

import logging
from typing import Optional
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


logger = logging.getLogger(__name__)


def extract_item_features(
    items_df: DataFrame,
    interactions_df: DataFrame,
    cold_threshold: int = 3,
) -> DataFrame:
    """从 items + interactions 聚合得到商品特征"""
    inter_agg = interactions_df.groupBy("item_id").agg(
        F.count("*").alias("interaction_count"),
        F.countDistinct("user_id").alias("buyer_count"),
        F.avg("rating").alias("avg_rating"),
        F.min("timestamp").alias("first_seen_ts"),
        F.max("timestamp").alias("last_seen_ts"),
    )
    if "rating" not in interactions_df.columns:
        inter_agg = inter_agg.drop("avg_rating")

    features = items_df.join(inter_agg, on="item_id", how="left").na.fill({
        "interaction_count": 0,
        "buyer_count": 0,
    })
    features = features.withColumn(
        "is_cold",
        (F.col("interaction_count") < cold_threshold) | F.col("interaction_count").isNull(),
    )
    logger.info("商品特征产出: %d 行", features.count())
    return features
