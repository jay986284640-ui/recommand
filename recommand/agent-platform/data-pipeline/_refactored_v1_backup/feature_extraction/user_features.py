"""用户特征提取

产出 user_features:
- user_id
- 静态画像(若 items / interactions 中有 lat / lng / age ...)
- interaction_count(交互总数)
- item_count(交互过的去重 item 数)
- category_pref(偏好品类 Top-3,逗号分隔)
- content_type_pref(偏好 content_type Top-2)
- active_days(交互时间跨度的天数)
- is_new_user(交互数 < new_user_threshold)
- first_seen_ts / last_seen_ts
"""

import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window


logger = logging.getLogger(__name__)


def extract_user_features(
    users_df: DataFrame,
    interactions_df: DataFrame,
    items_df: DataFrame,
    new_user_threshold: int = 3,
    top_category_n: int = 3,
) -> DataFrame:
    inter_with_item = interactions_df.join(items_df.select("item_id", "category", "content_type"), on="item_id", how="left")

    user_agg = inter_with_item.groupBy("user_id").agg(
        F.count("*").alias("interaction_count"),
        F.countDistinct("item_id").alias("item_count"),
        F.min("timestamp").alias("first_seen_ts"),
        F.max("timestamp").alias("last_seen_ts"),
    )
    user_agg = user_agg.withColumn(
        "active_days",
        F.round((F.col("last_seen_ts") - F.col("first_seen_ts")) / 86400.0, 2),
    )
    user_agg = user_agg.withColumn(
        "is_new_user",
        F.col("interaction_count") < new_user_threshold,
    )

    # Top-N 偏好 category(每个 user 取出现次数最高的 N 个 category)
    cat_count = inter_with_item.groupBy("user_id", "category").agg(F.count("*").alias("c"))
    w = Window.partitionBy("user_id").orderBy(F.desc("c"))
    cat_ranked = cat_count.withColumn("rk", F.row_number().over(w)).filter(F.col("rk") <= top_category_n)
    cat_pref = cat_ranked.groupBy("user_id").agg(
        F.concat_ws(",", F.collect_list(F.col("category"))).alias("category_pref")
    )

    # Top-2 偏好 content_type
    ct_count = inter_with_item.groupBy("user_id", "content_type").agg(F.count("*").alias("c"))
    w2 = Window.partitionBy("user_id").orderBy(F.desc("c"))
    ct_ranked = ct_count.withColumn("rk", F.row_number().over(w2)).filter(F.col("rk") <= 2)
    ct_pref = ct_ranked.groupBy("user_id").agg(
        F.concat_ws(",", F.collect_list(F.col("content_type"))).alias("content_type_pref")
    )

    features = (
        users_df
        .join(user_agg, on="user_id", how="left")
        .join(cat_pref, on="user_id", how="left")
        .join(ct_pref, on="user_id", how="left")
    )
    features = features.na.fill({"interaction_count": 0, "item_count": 0, "is_new_user": True})
    logger.info("用户特征产出: %d 行", features.count())
    return features
