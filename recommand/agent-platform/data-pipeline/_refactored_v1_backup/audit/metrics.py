"""稽核指标(纯函数,无 IO)

每个函数返回 dict(指标名 -> 指标值),最终汇总到 audit_report.json。
"""

import logging
from typing import Any, Dict, List
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


logger = logging.getLogger(__name__)


def row_count(df: DataFrame) -> Dict[str, Any]:
    """总行数 + 字段数"""
    return {
        "row_count": df.count(),
        "column_count": len(df.columns),
        "columns": df.columns,
    }


def field_completeness(df: DataFrame, fields: List[str] = None) -> Dict[str, Any]:
    """指定字段的非空率(%)"""
    fields = fields or df.columns
    total = df.count()
    out: Dict[str, Any] = {}
    for f in fields:
        if f not in df.columns:
            out[f] = {"present": False}
            continue
        non_null = df.filter(F.col(f).isNotNull() & (F.col(f) != "")).count()
        rate = non_null / total * 100 if total > 0 else 0.0
        out[f] = {"non_null_count": non_null, "non_null_rate_pct": round(rate, 4)}
    return out


def primary_key_uniqueness(df: DataFrame, keys: List[str]) -> Dict[str, Any]:
    """主键唯一性稽核"""
    out: Dict[str, Any] = {}
    for k in keys:
        if k not in df.columns:
            out[k] = {"present": False}
            continue
        total = df.count()
        distinct = df.select(k).distinct().count()
        dup = total - distinct
        rate = dup / total * 100 if total > 0 else 0.0
        out[k] = {
            "total": total,
            "distinct": distinct,
            "duplicates": dup,
            "duplicate_rate_pct": round(rate, 4),
        }
    return out


def time_range(df: DataFrame, time_col: str = "timestamp") -> Dict[str, Any]:
    """时间跨度"""
    if time_col not in df.columns:
        return {"present": False}
    row = df.agg(F.min(time_col).alias("min_ts"), F.max(time_col).alias("max_ts")).first()
    if row is None or row["min_ts"] is None:
        return {"present": True, "empty": True}
    span_seconds = row["max_ts"] - row["min_ts"]
    return {
        "min_timestamp": int(row["min_ts"]),
        "max_timestamp": int(row["max_ts"]),
        "span_seconds": int(span_seconds),
        "span_days": round(span_seconds / 86400, 2),
    }


def outlier_check(df: DataFrame, rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """异常值稽核(按用户配置的 {field, min, max} 规则)"""
    out: Dict[str, Any] = {}
    for rule in rules:
        field = rule.get("field")
        mn = rule.get("min")
        mx = rule.get("max")
        if not field or field not in df.columns:
            out[field or "?"] = {"present": False}
            continue
        total = df.count()
        cond = F.lit(True)
        if mn is not None:
            cond = cond & (F.col(field) < mn)
        if mx is not None:
            cond = cond & (F.col(field) > mx)
        outlier_count = df.filter(cond).count()
        rate = outlier_count / total * 100 if total > 0 else 0.0
        out[field] = {
            "min": mn,
            "max": mx,
            "outlier_count": outlier_count,
            "outlier_rate_pct": round(rate, 4),
        }
    return out
