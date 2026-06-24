"""文本长度过滤器"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base_filter import BaseFilter


class TextLengthFilter(BaseFilter):
    """文本长度过滤"""

    def __init__(self, max_length: int = 700):
        super().__init__("文本长度过滤 (<= {})".format(max_length))
        self.max_length = max_length

    def filter(self, df: DataFrame) -> DataFrame:
        """过滤超过最大长度的文本"""
        return df.filter(F.length(F.col("review_text")) <= self.max_length)
