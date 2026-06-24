"""去重过滤器"""

import logging
from pyspark.sql import DataFrame
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class DeduplicateFilter(BaseFilter):
    """
    去重过滤 - 根据指定字段去重

    去除指定字段值完全一致的记录，只保留一条
    """

    def __init__(self, key_column: str = None, enabled: bool = True):
        """
        初始化去重过滤器

        Args:
            key_column: 去重字段，如果为 None 则根据所有列去重
            enabled: 是否启用
        """
        super().__init__("去重过滤", enabled)
        self.key_column = key_column

    def filter(self, df: DataFrame) -> DataFrame:
        """去重"""
        if self.key_column:
            if self.key_column in df.columns:
                return df.dropDuplicates([self.key_column])
            else:
                logger.warning("列 '%s' 不存在，跳过去重", self.key_column)
                return df
        return df.dropDuplicates()