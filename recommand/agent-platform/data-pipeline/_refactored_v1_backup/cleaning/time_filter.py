"""时间过滤器"""

import logging
from datetime import datetime, timedelta
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class TimeFilter(BaseFilter):
    """只保留最近 N 年的数据"""

    def __init__(self, years: int = 10, enabled: bool = True):
        super().__init__(f"时间过滤 (最近 {years} 年)", enabled)
        self.years = years
        self.cutoff_timestamp = int((datetime.now() - timedelta(days=365 * years)).timestamp())

    def filter(self, df: DataFrame) -> DataFrame:
        if "timestamp" not in df.columns:
            logger.warning("timestamp 列不存在,跳过时间过滤")
            return df
        return df.filter(F.col("timestamp") >= self.cutoff_timestamp)
