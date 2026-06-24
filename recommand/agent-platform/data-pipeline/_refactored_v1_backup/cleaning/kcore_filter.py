"""K-core 过滤器"""

import logging
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class KCoreFilter(BaseFilter):
    """迭代过滤,直到每个用户和每个物品都至少 k 条交互"""

    def __init__(self, k: int = 5, checkpoint_dir: str = None, enabled: bool = True):
        super().__init__(f"K-core 过滤 (k={k})", enabled)
        self.k = k
        self.checkpoint_dir = checkpoint_dir
        self.CHECKPOINT_INTERVAL = 2

    def filter(self, df: DataFrame) -> DataFrame:
        if "user_id" not in df.columns or "item_id" not in df.columns:
            logger.warning("user_id 或 item_id 列不存在,跳过 K-core 过滤")
            return df

        if self.checkpoint_dir:
            spark = SparkSession.builder.getOrCreate()
            spark.sparkContext.setCheckpointDir(self.checkpoint_dir)
            logger.info("Checkpoint 目录: %s", self.checkpoint_dir)

        current_df = df.cache()
        prev_count = current_df.count()
        iteration = 0

        while True:
            iteration += 1
            user_counts = current_df.groupBy("user_id").agg(F.count("*").alias("user_cnt"))
            item_counts = current_df.groupBy("item_id").agg(F.count("*").alias("item_cnt"))
            valid_users = user_counts.filter(F.col("user_cnt") >= self.k).select("user_id")
            valid_items = item_counts.filter(F.col("item_cnt") >= self.k).select("item_id")
            next_df = current_df.join(valid_users, "user_id", "left_semi").join(
                valid_items, "item_id", "left_semi"
            )
            if self.checkpoint_dir and iteration % self.CHECKPOINT_INTERVAL == 0:
                next_df = next_df.localCheckpoint(eager=True)
            next_df = next_df.cache()
            curr_count = next_df.count()
            current_df.unpersist()
            removed = prev_count - curr_count
            logger.info("K-core 迭代 %d: %d -> %d (移除 %d)", iteration, prev_count, curr_count, removed)

            if curr_count == 0:
                current_df.unpersist()
                return df.filter(F.lit(False))
            if removed == 0:
                current_df.unpersist()
                return next_df
            current_df = next_df
            prev_count = curr_count
