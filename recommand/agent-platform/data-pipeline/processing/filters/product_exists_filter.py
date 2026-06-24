"""商品存在性过滤器"""

import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class ProductExistsFilter(BaseFilter):
    """
    商品存在性过滤 - 过滤掉 item_id 不在物品数据中的记录

    确保交互记录中的物品在物品表中存在
    """

    def __init__(self, items_df: DataFrame = None, item_id_column: str = "item_id", enabled: bool = True):
        """
        初始化商品存在性过滤器

        Args:
            items_df: 物品数据 DataFrame
            item_id_column: 物品表中 ID 列名
            enabled: 是否启用
        """
        super().__init__("商品存在性过滤", enabled)
        self.items_df = items_df
        self.item_id_column = item_id_column

    def filter(self, df: DataFrame) -> DataFrame:
        """过滤掉 item_id 不在物品数据中的记录"""
        if self.items_df is None:
            logger.warning("物品数据未提供，跳过商品存在性过滤")
            return df

        if "item_id" not in df.columns:
            logger.warning("交互数据中没有 item_id 列，跳过商品存在性过滤")
            return df

        # 从物品表获取有效的 item_id
        valid_items = self.items_df.select(self.item_id_column).distinct()
        valid_item_count = valid_items.count()
        logger.info("物品表中有效物品数: %d", valid_item_count)

        # 使用 left semi join 过滤：只保留在物品表中存在的记录
        result = df.join(valid_items, df["item_id"] == valid_items[self.item_id_column], "left_semi")

        logger.info("商品存在性过滤完成: %d -> %d", df.count(), result.count())
        return result