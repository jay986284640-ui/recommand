"""曝光日志(stub)

待 LP 主流程的推荐结果落盘后再接入数据源;当前提供一个空 schema + 计数器
用于让 4 步管线跑通 + 让下游消费者知道字段约定。
"""

import logging
from typing import Optional
from pyspark.sql import DataFrame, SparkSession


logger = logging.getLogger(__name__)


IMPRESSION_SCHEMA = """
trace_id STRING,
user_id STRING,
session_id STRING,
item_id STRING,
content_type STRING,
position INT,
rank_method STRING,    -- llm_rank / hot_list / lsh / popularity / model
impression_ts LONG,
is_click BOOLEAN,
is_convert BOOLEAN
"""


def build_impression_log_stub(spark: SparkSession) -> DataFrame:
    """返回一个空 DataFrame(只是 schema 落定)

    TODO: 待 LP 主流程落盘 conversation_trace (FR-053) 后,改成本实现:
        1. 读 OLAP 的 conversation_trace 范围(最近 N 天)
        2. 解析 slot_extraction_trace / top_k_returned
        3. 关联 user_actions_trace 得到 is_click / is_convert
        4. 写出 impression_log
    """
    logger.warning(
        "曝光日志(stub)模式: 等待 LP 主流程落盘后接入;当前返回空 DataFrame,schema 落定"
    )
    return spark.createDataFrame([], IMPRESSION_SCHEMA)
