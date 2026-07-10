"""运营行为清洗过滤器

消费 campaign_scorer 产出的 item_flags / user_flags,按策略从交互中剔除或降采样
运营行为记录,产出更干净的训练交互。

策略(policy):
- drop_campaign_items : 剔除命中运营商品的全部交互
- drop_abnormal_users : 剔除异常用户的全部交互
- downsample_campaign_items : 命中运营商品仅保留每商品最多 cap_per_item 条

继承 BaseFilter,复用管线的 _log_step 日志;flag 表通过构造函数注入。
"""

import logging
from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from processing.filters.base_filter import BaseFilter


logger = logging.getLogger(__name__)


class CampaignFilter(BaseFilter):
    """运营行为清洗过滤器"""

    def __init__(
        self,
        item_flags: Optional[DataFrame] = None,
        user_flags: Optional[DataFrame] = None,
        drop_campaign_items: bool = True,
        drop_abnormal_users: bool = True,
        downsample_campaign_items: bool = False,
        cap_per_item: int = 500,
        enabled: bool = True,
    ):
        super().__init__("运营行为清洗", enabled)
        self.item_flags = item_flags
        self.user_flags = user_flags
        self.drop_campaign_items = drop_campaign_items
        self.drop_abnormal_users = drop_abnormal_users
        self.downsample_campaign_items = downsample_campaign_items
        self.cap_per_item = cap_per_item

    def filter(self, df: DataFrame) -> DataFrame:
        result = df

        # 命中运营商品 id 集合
        campaign_items = None
        if self.item_flags is not None and "is_campaign_item" in self.item_flags.columns:
            campaign_items = self.item_flags.filter(
                F.col("is_campaign_item") == True  # noqa: E712
            ).select("item_id").dropDuplicates(["item_id"])

        # 1) 剔除异常用户
        if self.drop_abnormal_users and self.user_flags is not None \
                and "is_abnormal_user" in self.user_flags.columns:
            bad_users = self.user_flags.filter(
                F.col("is_abnormal_user") == True  # noqa: E712
            ).select("user_id").dropDuplicates(["user_id"])
            result = result.join(F.broadcast(bad_users), "user_id", "left_anti")

        # 2) 运营商品:整体剔除 或 降采样(二选一,drop 优先)
        if campaign_items is not None:
            if self.drop_campaign_items:
                result = result.join(
                    F.broadcast(campaign_items), "item_id", "left_anti"
                )
            elif self.downsample_campaign_items:
                flagged = result.join(F.broadcast(campaign_items), "item_id", "left_semi")
                normal = result.join(F.broadcast(campaign_items), "item_id", "left_anti")
                w = Window.partitionBy("item_id").orderBy(F.col("timestamp").asc())
                capped = (
                    flagged.withColumn("_rn", F.row_number().over(w))
                    .filter(F.col("_rn") <= F.lit(self.cap_per_item))
                    .drop("_rn")
                )
                result = normal.unionByName(capped)

        return result
