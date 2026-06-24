"""用户交互历史(按时间排序的行为序列)

产出 user_interaction_history:
- user_id
- sequence: array<struct<item_id, action, timestamp, store_id?, amount?>> 按 timestamp asc 排序
- seq_length
"""

import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window


logger = logging.getLogger(__name__)


def build_user_interaction_history(
    interactions_df: DataFrame,
    max_seq_length: int = 200,
) -> DataFrame:
    """按 user 聚合,按 timestamp 升序,截断到 max_seq_length"""
    # 选定要打包进 struct 的列(动态取交集)
    candidate_cols = ["item_id", "action", "timestamp", "store_id", "merchant_id", "amount"]
    cols = [c for c in candidate_cols if c in interactions_df.columns]
    struct_col = F.struct(*[F.col(c) for c in cols]).alias("entry")

    w = Window.partitionBy("user_id").orderBy("timestamp")
    ranked = interactions_df.withColumn("rk", F.row_number().over(w))
    truncated = ranked.filter(F.col("rk") <= max_seq_length)
    grouped = truncated.groupBy("user_id").agg(
        F.collect_list("entry").alias("sequence"),
        F.count("*").alias("seq_length"),
    )
    logger.info("用户交互历史产出: %d 行 (max_seq_length=%d)", grouped.count(), max_seq_length)
    return grouped
