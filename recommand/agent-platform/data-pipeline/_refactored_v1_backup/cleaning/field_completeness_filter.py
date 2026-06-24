"""字段完整性过滤器"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, FloatType, DoubleType, LongType
from .base_filter import BaseFilter


class FieldCompletenessFilter(BaseFilter):
    """过滤掉关键字段为空的记录"""

    def __init__(self, required_fields: list = None, enabled: bool = True):
        super().__init__("字段完整性过滤", enabled)
        self.required_fields = required_fields or ["user_id", "item_id", "timestamp"]

    def filter(self, df: DataFrame) -> DataFrame:
        condition = F.lit(True)
        for field in self.required_fields:
            if field in df.columns:
                field_type = df.schema[field].dataType
                if isinstance(field_type, (IntegerType, LongType, FloatType, DoubleType)):
                    condition = condition & F.col(field).isNotNull()
                else:
                    condition = condition & (
                        F.col(field).isNotNull() & (F.col(field) != "")
                    )
        return df.filter(condition)
