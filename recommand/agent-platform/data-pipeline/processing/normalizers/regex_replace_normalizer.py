"""正则替换规范化器 - 通过正则表达式替换字符串"""

import re
import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import StringType
from .base_normalizer import BaseTextNormalizer


logger = logging.getLogger(__name__)


class RegexReplaceNormalizer(BaseTextNormalizer):
    """
    正则替换规范化器 - 通过正则表达式替换字符串

    支持配置多个正则规则，每个规则包含：
    - pattern: 正则表达式
    - replacement: 替换字符串
    """

    def __init__(self, rules=None):
        """
        初始化正则替换规范化器

        Args:
            rules: 正则规则列表，格式:
                [
                    {"pattern": r"正则表达式", "replacement": "替换字符串"},
                    ...
                ]
        """
        super().__init__("正则替换")
        self.supported_types = [StringType]
        self.rules = rules or []

    def add_rule(self, pattern: str, replacement: str):
        """添加一条正则规则"""
        try:
            self.rules.append({"pattern": pattern, "replacement": replacement})
        except re.error as e:
            logger.warning("无效的正则表达式 '%s': %s", pattern, e)

    def process(self, df: DataFrame, text_column: str = "text") -> DataFrame:
        if text_column not in df.columns:
            return df

        if not self.rules:
            return df

        result = df

        for rule in self.rules:
            pattern = rule["pattern"]
            replacement = rule["replacement"]

            # 使用 Spark 内置的 regexp_replace
            result = result.withColumn(
                text_column,
                F.regexp_replace(F.col(text_column), pattern, replacement)
            )

            logger.debug("应用正则替换: %s -> %s", pattern, replacement)

        return result