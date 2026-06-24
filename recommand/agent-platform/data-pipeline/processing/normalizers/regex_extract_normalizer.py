"""可配置的通用正则提取规范化器"""

from typing import Optional

import re
import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType
from .base_normalizer import BaseTextNormalizer


logger = logging.getLogger(__name__)


class RegexExtractNormalizer(BaseTextNormalizer):
    r"""
    正则提取规范化器 - 通过正则表达式提取字符串

    支持为不同列配置不同的正则规则：

    配置示例:
    ```yaml
    normalizers:
      - normalizer: regex_extract
        columns:
          price:
            pattern: '(\$|€|EUR)\s*([\d,]+\.?\d*)'
            group: 2
            remove: ','
          rating:
            pattern: '([\d.]+)/5'
            group: 1
            default: '0'
    ```
    """

    def __init__(self, columns: Optional[dict] = None):
        super().__init__("正则提取")
        self.supported_types = [StringType]
        self.columns: dict = columns or {}  # 列名 -> 规则映射

    def add_column_rule(self, column: str, pattern: str, group: int = 1,
                        remove: str = "", default: str = ""):
        """添加列规则"""
        try:
            re.compile(pattern)
            self.columns[column] = {
                "pattern": pattern,
                "group": group,
                "remove": remove,
                "default": default
            }
        except re.error as e:
            logger.warning("无效的正则表达式 '%s': %s", pattern, e)

    def process(self, df: DataFrame, text_column: Optional[str] = None) -> DataFrame:
        result = df

        if not self.columns:
            return result

        for col_name, rule in self.columns.items():
            if col_name not in df.columns:
                continue

            pattern = rule.get("pattern", "")
            if not pattern:
                continue

            group = rule.get("group", 1)
            remove_chars = rule.get("remove", "")
            default_value = rule.get("default", "")

            # 执行提取
            extracted = F.regexp_extract(F.col(col_name), pattern, group)

            # 移除字符
            for char in remove_chars:
                extracted = F.regexp_replace(extracted, re.escape(char), '')

            # 应用默认值
            if default_value:
                extracted = F.when(extracted != '', extracted).otherwise(F.lit(default_value))

            result = result.withColumn(col_name, extracted)

            logger.debug("应用正则提取规则到列 %s: %s -> group%d",
                         col_name, pattern, group)

        return result