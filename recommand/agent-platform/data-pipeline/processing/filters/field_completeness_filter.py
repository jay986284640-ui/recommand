"""字段完整性过滤器"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, FloatType, DoubleType, LongType
from .base_filter import BaseFilter


class FieldCompletenessFilter(BaseFilter):
    """
    字段完整性过滤 - 关键字段非空

    过滤掉指定必填字段为空的记录
    """

    def __init__(self, required_fields: list = None, enabled: bool = True):
        """
        初始化字段完整性过滤器

        Args:
            required_fields: 必填字段列表，默认为 ["user_id", "item_id", "timestamp"]
            enabled: 是否启用
        """
        super().__init__("字段完整性过滤", enabled)
        self.required_fields = required_fields or ["user_id", "item_id", "timestamp"]

    def filter(self, df: DataFrame) -> DataFrame:
        """过滤关键字段为空的记录"""
        condition = F.lit(True)

        for field in self.required_fields:
            if field in df.columns:
                field_type = df.schema[field].dataType
                if isinstance(field_type, (IntegerType,LongType, FloatType, DoubleType)):
                    condition = condition & F.col(field).isNotNull()
                else:
                    condition = condition & (
                        F.col(field).isNotNull() &
                        (F.col(field) != "")
                    )

        return df.filter(condition)
