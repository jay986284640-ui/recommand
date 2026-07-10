#!/usr/bin/env python3
"""复合打分与打标

把各检测器(item / user 级)的输出 join 起来,按可疑维度计数打分,产出布尔标记表:
- item_flags: item_id, <各 flag>, campaign_score, is_campaign_item, reason
- user_flags: user_id, <各 flag>, is_abnormal_user, reason

设计为纯函数,便于单测;不依赖 BaseAnalyzer(输入是多张检测器结果表)。
"""

from typing import Dict, List, Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


# 各 item 级检测器输出中的 flag 列 → 归因原因名
ITEM_FLAG_COLUMNS = {
    "flag_popularity": "popularity",
    "flag_burst": "burst",
    "flag_funnel": "funnel",
    "flag_geo": "geo",
}


def _reason_expr(flag_to_reason: Dict[str, str], available: List[str]):
    """把命中的 flag 列拼成 reason 字符串(用 | 连接)。

    concat_ws 会自动跳过 null,故未命中项置 null 即可;不要用 array_remove(., None)
    (Spark 中 element 为 null 时 array_remove 整体返回 null,会把 reason 清空)。
    """
    parts = []
    for flag, reason in flag_to_reason.items():
        if flag in available:
            parts.append(
                F.when(F.col(flag) == True, F.lit(reason)).otherwise(F.lit(None))  # noqa: E712
            )
    if not parts:
        return F.lit("")
    return F.concat_ws("|", F.array(*parts))


def score_items(
    item_results: Dict[str, DataFrame],
    min_score: int = 1,
) -> Optional[DataFrame]:
    """合并 item 级检测器结果 → item_flags。

    Args:
        item_results: {detector_name: DataFrame(含 item_id + flag_*)}
        min_score:    命中多少个维度即判为运营商品(默认 1)
    """
    dfs = [df for df in item_results.values() if df is not None]
    if not dfs:
        return None

    merged: Optional[DataFrame] = None
    for df in dfs:
        flag_cols = [c for c in df.columns if c in ITEM_FLAG_COLUMNS]
        keep = ["item_id"] + flag_cols
        sub = df.select(*keep)
        merged = sub if merged is None else merged.join(sub, "item_id", "outer")

    # 缺失 flag 填 False
    available_flags = [c for c in merged.columns if c in ITEM_FLAG_COLUMNS]
    merged = merged.na.fill({c: False for c in available_flags})

    score_expr = F.lit(0)
    for c in available_flags:
        score_expr = score_expr + F.col(c).cast("int")
    merged = merged.withColumn("campaign_score", score_expr)
    merged = merged.withColumn(
        "is_campaign_item", F.col("campaign_score") >= F.lit(min_score)
    )
    merged = merged.withColumn(
        "reason", _reason_expr(ITEM_FLAG_COLUMNS, available_flags)
    )
    return merged.orderBy(F.desc("campaign_score"))


def score_users(user_result: Optional[DataFrame]) -> Optional[DataFrame]:
    """用户级标记:直接取 user_velocity 检测器的 flag。"""
    if user_result is None or "flag_user_velocity" not in user_result.columns:
        return None
    result = user_result.withColumn(
        "is_abnormal_user", F.col("flag_user_velocity")
    ).withColumn(
        "reason",
        F.when(F.col("flag_user_velocity") == True, F.lit("velocity")).otherwise(  # noqa: E712
            F.lit("")
        ),
    )
    return result
