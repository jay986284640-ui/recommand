"""时间过滤器"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from datetime import datetime, timedelta

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base_filter import BaseFilter


class TimeFilter(BaseFilter):
    """时间过滤 - 只保留最近 N 年"""

    def __init__(self, years: int = 10):
        super().__init__("时间过滤 (最近 {} 年)".format(years))
        self.years = years
        self.cutoff_timestamp = int((datetime.now() - timedelta(days=365 * years)).timestamp())

    def filter(self, df: DataFrame) -> DataFrame:
        """过滤超过指定年份的记录"""
        return df.filter(F.col("timestamp") >= self.cutoff_timestamp)
