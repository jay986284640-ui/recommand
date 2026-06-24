"""文本规范化器基类"""

from abc import ABC, abstractmethod
from typing import List, Type
from pyspark.sql import DataFrame
from pyspark.sql.types import DataType


class BaseTextNormalizer(ABC):
    """
    文本规范化器基类

    所有文本规范化器必须继承此类
    """

    def __init__(self, name: str):
        self.name = name
        # 支持的数据类型列表，None 表示不限制
        self.supported_types: List[Type[DataType]] = []

    @abstractmethod
    def process(self, df: DataFrame, text_column: str = "text") -> DataFrame:
        """
        处理文本数据

        Args:
            df: 输入 DataFrame
            text_column: 要处理的文本列名

        Returns:
            处理后的 DataFrame
        """
        pass

    def is_column_supported(self, df: DataFrame, text_column: str) -> bool:
        """
        检查列类型是否支持

        Args:
            df: DataFrame
            text_column: 列名

        Returns:
            是否支持处理
        """
        if text_column not in df.columns:
            return False

        if not self.supported_types:
            return True  # 不限制类型

        column_type = df.schema[text_column].dataType
        return any(isinstance(column_type, t) for t in self.supported_types)

    def __repr__(self):
        return f"{self.__class__.__name__}()"