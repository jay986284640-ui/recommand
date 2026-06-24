"""Unicode规范化器 - 统一字符编码（NFC标准化）"""

import unicodedata
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType
from .base_normalizer import BaseTextNormalizer


class UnicodeNormalizer(BaseTextNormalizer):
    """Unicode规范化器 - 统一字符编码（NFC标准化）"""

    def __init__(self):
        super().__init__("Unicode规范化")
        self.supported_types = [StringType]
        # 预创建 UDF
        self._normalize_udf = F.udf(lambda x: unicodedata.normalize('NFC', x) if x else x)

    def process(self, df: DataFrame, text_column: str = "text") -> DataFrame:
        if text_column not in df.columns:
            return df

        return df.withColumn(
            text_column,
            self._normalize_udf(F.col(text_column))
        )