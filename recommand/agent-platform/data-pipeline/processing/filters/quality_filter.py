"""数据质量过滤器"""

import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class QualityFilter(BaseFilter):
    """
    数据质量过滤 - 过滤空值和过短文本

    过滤掉指定文本字段为空或长度过短的记录
    """

    def __init__(self, text_column: str = "review_text", min_text_length: int = 10, enabled: bool = True):
        """
        初始化质量过滤器

        Args:
            text_column: 文本字段名
            min_text_length: 最小文本长度
            enabled: 是否启用
        """
        super().__init__("数据质量过滤 (最小长度={})".format(min_text_length), enabled)
        self.text_column = text_column
        self.min_text_length = min_text_length

    def filter(self, df: DataFrame) -> DataFrame:
        """过滤空值和过短文本"""
        if self.text_column not in df.columns:
            logger.warning("列 '%s' 不存在，跳过质量过滤", self.text_column)
            return df

        # 过滤空值和长度过短的文本
        condition = (
            F.col(self.text_column).isNotNull() &
            (F.length(F.col(self.text_column)) >= self.min_text_length)
        )

        return df.filter(condition)