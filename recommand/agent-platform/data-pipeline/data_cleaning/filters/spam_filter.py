"""垃圾数据过滤器"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base_filter import BaseFilter


class SpamFilter(BaseFilter):
    """垃圾数据过滤 - 检测垃圾评论"""

    # 垃圾评论模式
    SPAM_PATTERNS = [
        # 诱惑性文字
        r"click\s*here",
        r"buy\s*now",
        r"limited\s*time",
        r"act\s*now",
        r"order\s*now",
        r"free\s*gift",
        r"special\s*offer",
        r"don'?t\s*miss",
        # 垃圾广告
        r"weight\s*loss",
        r"male\s*enhancement",
        r"casino",
        r"bitcoin",
        r"cryptocurrency",
        r"make\s*money\s*fast",
        r"work\s*from\s*home",
        # 可疑链接
        r"http[s]?://",
        r"www\.",
        r"\.com\s*$",
        r"\.net\s*$",
        r"\.org\s*$",
    ]

    def __init__(self, custom_patterns: list = None):
        super().__init__("垃圾数据过滤")
        self.patterns = custom_patterns or self.SPAM_PATTERNS

    def filter(self, df: DataFrame) -> DataFrame:
        """过滤垃圾评论"""
        # 构建正则表达式过滤条件
        spam_condition = F.lit(False)
        for pattern in self.patterns:
            spam_condition = spam_condition | F.lower(F.col("review_text")).rlike(pattern)

        # 也检查title字段中的垃圾内容
        title_spam_condition = F.lit(False)
        if "review_title" in df.columns:
            for pattern in self.patterns:
                title_spam_condition = title_spam_condition | F.lower(F.col("review_title")).rlike(pattern)

            return df.filter(~spam_condition & ~title_spam_condition)
        else:
            return df.filter(~spam_condition)
