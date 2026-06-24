"""数据质量稽核(步骤 1)

只读不写,产出 audit_report.json 描述数据健康度。
不阻塞主流程;异常由人工 / 下游消费方决定如何处理。
"""

from .metrics import (
    row_count,
    field_completeness,
    primary_key_uniqueness,
    time_range,
    outlier_check,
)
from .reporter import AuditReporter
from .pipeline import AuditPipeline

__all__ = [
    "row_count",
    "field_completeness",
    "primary_key_uniqueness",
    "time_range",
    "outlier_check",
    "AuditReporter",
    "AuditPipeline",
]
