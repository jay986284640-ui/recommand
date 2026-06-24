"""字段完整性过滤器"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, FloatType

from .base_filter import BaseFilter


class FieldCompletenessFilter(BaseFilter):
    """字段完整性过滤 - 关键字段非空"""

    def __init__(self, required_fields: list = None):
        super().__init__("字段完整性过滤")
        self.required_fields = required_fields or ["user_id", "product_id", "review_text", "timestamp"]

    def filter(self, df: DataFrame) -> DataFrame:
        """过滤关键字段为空的记录"""
        condition = F.lit(True)

        for field in self.required_fields:
            if field in df.columns:
                # 获取字段类型
                field_type = df.schema[field].dataType
                # 数值类型只检查 isNotNull，字符串类型检查非空
                if isinstance(field_type, (IntegerType, FloatType)):
                    condition = condition & F.col(field).isNotNull()
                else:
                    condition = condition & (
                            F.col(field).isNotNull() &
                            (F.col(field) != "")
                    )

        return df.filter(condition)
