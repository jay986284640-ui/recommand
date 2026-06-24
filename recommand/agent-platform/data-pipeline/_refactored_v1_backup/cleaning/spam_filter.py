"""垃圾数据过滤器(基于正则的 spam pattern 匹配)"""

import logging
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class SpamFilter(BaseFilter):
    """检测并过滤垃圾评论 / 营销引流"""

    SPAM_PATTERNS = [
        r"click\s*here",
        r"buy\s*now",
        r"limited\s*time",
        r"act\s*now",
        r"order\s*now",
        r"free\s*trial",
        r"100%\s*free",
        r"make\s*money",
        r"earn\s*cash",
        r"work\s*from\s*home",
        r"viagra",
        r"casino",
        r"crypto\s*giveaway",
        r"telegram\s*@\w+",
        r"whatsapp\s*+\d+",
    ]

    def __init__(self, text_column: str = "review_text", extra_patterns: list = None, enabled: bool = True):
        super().__init__("垃圾数据过滤", enabled)
        self.text_column = text_column
        patterns = list(self.SPAM_PATTERNS)
        if extra_patterns:
            patterns.extend(extra_patterns)
        self.combined_pattern = "|".join(f"({p})" for p in patterns)

    def filter(self, df: DataFrame) -> DataFrame:
        if self.text_column not in df.columns:
            logger.warning("列 '%s' 不存在,跳过垃圾数据过滤", self.text_column)
            return df
        return df.filter(~F.col(self.text_column).rlike(self.combined_pattern))
