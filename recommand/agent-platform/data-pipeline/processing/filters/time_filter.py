"""时间过滤器"""

import logging
from datetime import datetime, timedelta
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from .base_filter import BaseFilter


logger = logging.getLogger(__name__)


class TimeFilter(BaseFilter):
    """
    时间过滤 - 只保留最近 N 年的数据

    过滤掉 timestamp 早于指定 cutoff 时间的记录
    """

    def __init__(self, years: int = 10, enabled: bool = True):
        """
        初始化时间过滤器

        Args:
            years: 保留最近 N 年的数据
            enabled: 是否启用
        """
        super().__init__("时间过滤 (最近 {} 年)".format(years), enabled)
        self.years = years
        self.cutoff_timestamp = int((datetime.now() - timedelta(days=365 * years)).timestamp())

    def filter(self, df: DataFrame) -> DataFrame:
        """过滤超过指定年份的记录"""
        if "timestamp" not in df.columns:
            logger.warning("timestamp 列不存在，跳过时间过滤")
            return df

        return df.filter(F.col("timestamp") >= self.cutoff_timestamp)
