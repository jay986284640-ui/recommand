"""文本长度过滤器"""

import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class TextLengthFilter(BaseFilter):
    """过滤过短 / 纯空白文本"""

    def __init__(self, text_column: str = "review_text", min_length: int = 5, enabled: bool = True):
        super().__init__(f"文本长度过滤 (最小 {min_length})", enabled)
        self.text_column = text_column
        self.min_length = min_length

    def filter(self, df: DataFrame) -> DataFrame:
        if self.text_column not in df.columns:
            logger.warning("列 '%s' 不存在,跳过文本长度过滤", self.text_column)
            return df
        return df.filter(F.length(F.trim(F.col(self.text_column))) >= self.min_length)
