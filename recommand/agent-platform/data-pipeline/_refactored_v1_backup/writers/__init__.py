"""通用 writer

feature_extraction/ 内部已经自带 _write 方法。本模块保留作未来扩展
(例如:写 OLAP / 写 Redis / 推 Kafka)。
"""

from .feature_writer import write_dataframe

__all__ = ["write_dataframe"]
