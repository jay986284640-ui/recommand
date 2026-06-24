"""大小写规范化器 - 统一转换为小写"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType
from .base_normalizer import BaseTextNormalizer


class LowercaseNormalizer(BaseTextNormalizer):
    """大小写规范化器 - 统一转换为小写"""

    def __init__(self):
        super().__init__("小写转换")
        self.supported_types = [StringType]

    def process(self, df: DataFrame, text_column: str = "text") -> DataFrame:
        if text_column not in df.columns:
            return df

        return df.withColumn(text_column, F.lower(F.col(text_column)))