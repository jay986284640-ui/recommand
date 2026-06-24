"""去重过滤器"""

import logging
from pyspark.sql import DataFrame
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class DeduplicateFilter(BaseFilter):
    """根据指定字段去重(整行去重或单字段去重)"""

    def __init__(self, key_column: str = None, enabled: bool = True):
        super().__init__("去重过滤", enabled)
        self.key_column = key_column

    def filter(self, df: DataFrame) -> DataFrame:
        if self.key_column:
            if self.key_column in df.columns:
                return df.dropDuplicates([self.key_column])
            logger.warning("列 '%s' 不存在,跳过去重", self.key_column)
            return df
        return df.dropDuplicates()
