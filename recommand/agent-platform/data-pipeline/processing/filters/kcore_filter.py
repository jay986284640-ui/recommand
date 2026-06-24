"""K-core过滤器"""

import logging
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class KCoreFilter(BaseFilter):
    """
    K-core 过滤 - 用户和物品都至少包含 N 条交互记录

    通过迭代过滤，确保每个用户和每个物品都有至少 k 条交互记录
    """

    def __init__(self, k: int = 5, checkpoint_dir: str = None, enabled: bool = True):
        """
        初始化 K-core 过滤器

        Args:
            k: K-core 阈值，每个用户和物品至少要有 k 条交互
            checkpoint_dir: checkpoint 目录，用于切断血缘链
            enabled: 是否启用
        """
        super().__init__("K-core 过滤 (k={})".format(k), enabled)
        self.k = k
        self.checkpoint_dir = checkpoint_dir
        self.CHECKPOINT_INTERVAL = 2
    
    def filter(self, df: DataFrame) -> DataFrame:
        """执行 K-core 过滤"""
        if "user_id" not in df.columns or "item_id" not in df.columns:
            logger.warning("user_id 或 item_id 列不存在，跳过 K-core 过滤")
            return df

        if self.checkpoint_dir:
            spark = SparkSession.builder.getOrCreate()
            spark.sparkContext.setCheckpointDir(self.checkpoint_dir)
            logger.info("Checkpoint 目录: %s", self.checkpoint_dir)

        current_df = df
        # 初始计数 (Action 1)
        current_df = current_df.cache()
        prev_count = current_df.count()
        iteration = 0

        while True:
            iteration += 1
            logger.info("迭代 %d", iteration)

            # 统计每个用户和物品的交互数量 (Shuffle 操作， unavoidable)
            user_counts = current_df.groupBy("user_id").agg(F.count("*").alias("user_cnt"))
            item_counts = current_df.groupBy("item_id").agg(F.count("*").alias("item_cnt"))

            # 过滤出满足 k 要求的用户和物品
            valid_users = user_counts.filter(F.col("user_cnt") >= self.k).select("user_id")
            valid_items = item_counts.filter(F.col("item_cnt") >= self.k).select("item_id")

            # 高效过滤 (Semi Join)
            next_df = current_df.join(valid_users, "user_id", "left_semi") \
                                .join(valid_items, "item_id", "left_semi")

            # 定期 checkpoint 切断血缘链
            if self.checkpoint_dir and iteration % self.CHECKPOINT_INTERVAL == 0:
                logger.info("执行 checkpoint 重置血缘链 (迭代 %d)", iteration)
                next_df = next_df.localCheckpoint(eager=True)  # fixme: 集群模式下建议使用checkpoinit方法

            # 获取本轮结果数量 (Action 3)
            next_df = next_df.cache()
            curr_count = next_df.count()

            current_df.unpersist()

            removed = prev_count - curr_count

            logger.info("过滤前: %d, 过滤后: %d, 移除: %d",
                        prev_count, curr_count, removed)

            if curr_count == 0:
                logger.info("K-core 过滤完成! 无有效数据")
                current_df.unpersist()
                return df.filter(F.lit(False))

            if removed == 0:
                logger.info("K-core 过滤完成! 已收敛")
                current_df.unpersist()
                return next_df

            current_df = next_df
            prev_count = curr_count