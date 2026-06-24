"""商品存在性过滤器"""

import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class ProductExistsFilter(BaseFilter):
    """过滤掉 item_id 不在物品表中的交互记录"""

    def __init__(self, items_df: DataFrame = None, item_id_column: str = "item_id", enabled: bool = True):
        super().__init__("商品存在性过滤", enabled)
        self.items_df = items_df
        self.item_id_column = item_id_column

    def filter(self, df: DataFrame) -> DataFrame:
        if self.items_df is None:
            logger.warning("物品数据未提供,跳过商品存在性过滤")
            return df
        if "item_id" not in df.columns:
            logger.warning("交互数据中没有 item_id 列,跳过商品存在性过滤")
            return df
        valid_items = self.items_df.select(self.item_id_column).distinct()
        return df.join(valid_items, df["item_id"] == valid_items[self.item_id_column], "left_semi")
