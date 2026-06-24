"""HTML规范化器 - 移除HTML标签和解码HTML实体"""

import re
import html
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, ArrayType
from .base_normalizer import BaseTextNormalizer


def clean_description_item(item):
    """处理单个description元素"""
    if item is None:
        return None
    s = str(item)
    # 移除HTML标签
    s = re.sub(r'<[^>]+>', '', s)
    # HTML实体解码
    s = s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    s = s.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    # 去除多余空格
    s = re.sub(r'\s+', ' ', s).strip()
    return s if s else None


def process_description_list(desc_list):
    """处理整个description列表"""
    if desc_list is None:
        return None
    result = []
    for item in desc_list:
        cleaned = clean_description_item(item)
        if cleaned:
            result.append(cleaned)
    return result if result else []

class HtmlNormalizer(BaseTextNormalizer):
    """HTML规范化器 - 移除HTML标签"""

    def __init__(self):
        super().__init__("HTML规范化")
        # 支持 StringType 和 ArrayType
        self.supported_types = [StringType, ArrayType]
        # 为 ArrayType 预创建 UDF
        self._process_desc_udf = F.udf(process_description_list, ArrayType(StringType()))

    def process(self, df: DataFrame, text_column: str = "text") -> DataFrame:
        if text_column not in df.columns:
            return df

        field_type = df.schema[text_column].dataType

        # 处理 ArrayType
        if isinstance(field_type, ArrayType):
            return df.withColumn(
                text_column,
                F.when(
                    F.col(text_column).isNotNull(),
                    self._process_desc_udf(F.col(text_column))
                ).otherwise(F.lit(None))
            )

        # 处理 StringType - 解码HTML实体
        df = df.withColumn(
            text_column,
            F.udf(lambda x: html.unescape(x) if x else x)(F.col(text_column))
        )

        # 移除HTML标签
        return df.withColumn(
            text_column,
            F.regexp_replace(F.col(text_column), r'<[^>]+>', '')
        )
