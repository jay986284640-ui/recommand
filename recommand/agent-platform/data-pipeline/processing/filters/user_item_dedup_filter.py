"""用户-物品去重过滤器"""

import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)



class UserItemDeduplicateFilter(BaseFilter):
    """
    用户-物品去重 - 按时间排序后，相邻的同一用户对同一物品的记录只保留一条

    连续定义：按时间排序后，相邻两条记录如果是同一用户对同一物品，则视为连续重复，去重
    """

    def __init__(self, keep: str = "first", enabled: bool = True):
        """
        初始化用户-物品去重过滤器

        Args:
            keep: 保留策略，"first" 保留最早一条，"last" 保留最新一条
            enabled: 是否启用
        """
        super().__init__("用户-物品连续去重", enabled)
        self.keep = keep

    def filter(self, df: DataFrame) -> DataFrame:
        """去重：按时间排序后，相邻的同一用户-物品记录只保留一条"""
        if "user_id" not in df.columns or "item_id" not in df.columns:
            logger.warning("user_id 或 item_id 列不存在，跳过用户-物品去重")
            return df

        # 确定时间字段
        time_col = None
        for col_name in ["timestamp", "review_time", "time"]:
            if col_name in df.columns:
                time_col = F.col(col_name)
                break

        if time_col is None:
            logger.warning("没有时间字段，无法排序，直接返回")
            return df

        # 按 user_id, item_id 分区，按时间排序
        if self.keep == "last":
            window = Window.partitionBy("user_id").orderBy(time_col.desc())
        else:
            window = Window.partitionBy("user_id").orderBy(time_col.asc())

        # 为每条记录分配序号
        df_ranked = df.withColumn("row_num", F.row_number().over(window))

        # 获取同一分区内相邻记录的用户和物品
        df_ranked = df_ranked.withColumn("prev_user_id", F.lag("user_id", 1).over(window))
        df_ranked = df_ranked.withColumn("prev_item_id", F.lag("item_id", 1).over(window))

        # 标记：当前记录的 user_id+item_id 是否与上一条相同
        df_ranked = df_ranked.withColumn(
            "is_duplicate",
            (F.col("user_id") == F.col("prev_user_id")) &
            (F.col("item_id") == F.col("prev_item_id"))
        )

        # 只保留非连续重复的记录
        result = df_ranked.filter(
            (F.col("row_num") == 1) | (~F.col("is_duplicate"))
        ).drop("row_num", "prev_user_id", "prev_item_id", "is_duplicate")

        return result