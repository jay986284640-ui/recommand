"""特殊符号规范化器 - 移除特殊符号，保留字母、数字、空格和基本标点"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType
from .base_normalizer import BaseTextNormalizer


class SpecialCharNormalizer(BaseTextNormalizer):
    """特殊符号规范化器"""

    def __init__(self):
        super().__init__("特殊符号规范化")
        self.supported_types = [StringType]

    def process(self, df: DataFrame, text_column: str = "text") -> DataFrame:
        if text_column not in df.columns:
            return df

        col = F.col(text_column)

        # 保留字母、数字、空格、常见标点
        return df.withColumn(
            text_column,
            F.regexp_replace(col, r'[^\w\s.,!?\'"-]', ' ')
        )