"""空格规范化器 - 去除多余空格，去除首尾空白"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType
from .base_normalizer import BaseTextNormalizer


class WhitespaceNormalizer(BaseTextNormalizer):
    """空格规范化器 - 去除多余空格，去除首尾空白"""

    def __init__(self):
        super().__init__("空格规范化")
        self.supported_types = [StringType]

    def process(self, df: DataFrame, text_column: str = "text") -> DataFrame:
        if text_column not in df.columns:
            return df

        # 多个空格 -> 单个空格
        df = df.withColumn(
            text_column,
            F.regexp_replace(F.col(text_column), r'\s+', ' ')
        )

        # 去除首尾空白
        return df.withColumn(text_column, F.trim(F.col(text_column)))