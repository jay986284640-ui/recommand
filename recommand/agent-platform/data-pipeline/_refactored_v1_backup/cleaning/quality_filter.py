"""数据质量过滤器(空值 + 过短文本)"""

import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class QualityFilter(BaseFilter):
    def __init__(self, text_column: str = "review_text", min_text_length: int = 10, enabled: bool = True):
        super().__init__(f"数据质量过滤 (最小长度={min_text_length})", enabled)
        self.text_column = text_column
        self.min_text_length = min_text_length

    def filter(self, df: DataFrame) -> DataFrame:
        if self.text_column not in df.columns:
            logger.warning("列 '%s' 不存在,跳过质量过滤", self.text_column)
            return df
        condition = (
            F.col(self.text_column).isNotNull()
            & (F.length(F.col(self.text_column)) >= self.min_text_length)
        )
        return df.filter(condition)
