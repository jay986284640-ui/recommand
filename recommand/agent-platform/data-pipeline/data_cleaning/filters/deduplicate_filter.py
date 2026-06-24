"""去重过滤器"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from pyspark.sql import DataFrame

from .base_filter import BaseFilter


class DeduplicateFilter(BaseFilter):
    """去重过滤 - reviewText完全一致的记录去重"""

    def __init__(self, key_column: str = "review_text"):
        super().__init__("去重过滤")
        self.key_column = key_column

    def filter(self, df: DataFrame) -> DataFrame:
        """去重"""
        return df.dropDuplicates([self.key_column])
