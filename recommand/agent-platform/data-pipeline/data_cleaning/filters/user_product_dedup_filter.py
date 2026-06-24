"""用户-商品去重过滤器"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from .base_filter import BaseFilter


class UserProductDeduplicateFilter(BaseFilter):
    """用户-商品去重 - 按时间排序后，相邻的同一用户对同一商品的记录只保留一条

    连续定义：按时间排序后，相邻两条记录如果是同一用户对同一商品，则视为连续重复，去重
    """

    def __init__(self, keep: str = "first"):
        """
        Args:
            keep: 保留策略，"first" 保留最早一条，"last" 保留最新一条
        """
        super().__init__("用户-商品连续去重")
        self.keep = keep

    def filter(self, df: DataFrame) -> DataFrame:
        """去重：按时间排序后，相邻的同一用户-商品记录只保留一条"""
        # 获取时间字段
        if "review_date" in df.columns:
            time_col = "review_date"
        elif "timestamp" in df.columns:
            time_col = "timestamp"
        else:
            # 没有时间字段，无法排序，直接返回
            return df

        # 按 user_id, product_id 分区，按时间排序
        window = Window.partitionBy("user_id", "product_id").orderBy(time_col)

        # 为每条记录分配序号
        df_ranked = df.withColumn("row_num", F.row_number().over(window))

        # 获取同一分区内相邻记录的用户和商品
        df_ranked = df_ranked.withColumn("prev_user_id", F.lag("user_id", 1).over(window))
        df_ranked = df_ranked.withColumn("prev_product_id", F.lag("product_id", 1).over(window))

        # 标记：当前记录的 user_id+product_id 是否与上一条相同
        df_ranked = df_ranked.withColumn(
            "is_duplicate",
            (F.col("user_id") == F.col("prev_user_id")) &
            (F.col("product_id") == F.col("prev_product_id"))
        )

        # 只保留非连续重复的记录（即第一块连续记录的第一条）
        # 实际上就是：保留 row_num=1 或者 is_duplicate=False 的记录
        result = df_ranked.filter(
            (F.col("row_num") == 1) | (~F.col("is_duplicate"))
        ).drop("row_num", "prev_user_id", "prev_product_id", "is_duplicate")

        return result
