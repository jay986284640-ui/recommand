"""K-core过滤器"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.storagelevel import StorageLevel

from .base_filter import BaseFilter


class KCoreFilter(BaseFilter):
    """K-core 过滤 - 用户和商品都至少包含N条评论 (修复迭代性能问题)"""

    def __init__(self, k: int = 5, checkpoint_dir: str = None):
        super().__init__("K-core 过滤 (k={})".format(k))
        self.k = k
        self.checkpoint_dir = checkpoint_dir
        self.CHECKPOINT_INTERVAL = 3

    def filter(self, df: DataFrame) -> DataFrame:
        """执行K-core过滤 - 修复迭代性能衰减问题"""

        current_df = df  # 不再手动 persist
        before_count = current_df.count()  # 触发初始计算

        # 设置 checkpoint 目录
        if self.checkpoint_dir:
            spark = SparkSession.builder.getOrCreate()
            spark.sparkContext.setCheckpointDir(self.checkpoint_dir)
            print(f"    Checkpoint 目录: {self.checkpoint_dir}")

        iteration = 0

        while True:
            iteration += 1
            print(f"\n   迭代 {iteration}:")

            user_counts = current_df.groupBy("user_id").agg(F.count("*").alias("user_cnt"))
            product_counts = current_df.groupBy("product_id").agg(F.count("*").alias("product_cnt"))

            valid_users = user_counts.filter(F.col("user_cnt") >= self.k).select("user_id")
            valid_products = product_counts.filter(F.col("product_cnt") >= self.k).select("product_id")

            # 统计有效用户/商品数（小表，无需 persist）
            valid_users_count = valid_users.count()
            valid_products_count = valid_products.count()

            print(f"      有效用户: {valid_users_count:,}, 有效商品: {valid_products_count:,}")

            if valid_users_count == 0 or valid_products_count == 0:
                print(f"\n   K-core 过滤完成! 无有效数据")
                return df.filter(F.lit(False))

            next_df = current_df.join(valid_users, "user_id") \
                .join(valid_products, "product_id")

            # 定期 checkpoint 切断血缘链（核心修复！）
            if self.checkpoint_dir and iteration % self.CHECKPOINT_INTERVAL == 0:
                print(f"    执行 checkpoint 重置血缘链 (迭代 {iteration})")
                next_df = next_df.checkpoint(eager=True)  # 自动持久化+切断血缘

            # 计数
            after_count = next_df.count()
            removed_count = before_count - after_count

            print(f"      过滤前: {before_count:,}")
            print(f"      过滤后: {after_count:,}")
            print(f"      移除: {removed_count:,}")

            if after_count == 0:
                print(f"\n   K-core 过滤完成! 无有效数据（用户-商品无交集）")
                return df.filter(F.lit(False))

            if removed_count == 0:
                print(f"\n   K-core 过滤完成! 已收敛")
                return next_df

            # 更新当前数据为过滤后的结果
            current_df = next_df
            before_count = after_count
