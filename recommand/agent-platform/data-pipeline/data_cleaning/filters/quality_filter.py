"""数据质量过滤器"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base_filter import BaseFilter


class QualityFilter(BaseFilter):
    """数据质量过滤 - 空值、过短文本"""

    def __init__(self, min_text_length: int = 10):
        super().__init__("数据质量过滤 (最小文本长度: {})".format(min_text_length))
        self.min_text_length = min_text_length

    def filter(self, df: DataFrame) -> DataFrame:
        """过滤过短文本和纯空白文本"""
        return df.filter(
            F.length(F.trim(F.col("review_text"))) >= self.min_text_length
        )
