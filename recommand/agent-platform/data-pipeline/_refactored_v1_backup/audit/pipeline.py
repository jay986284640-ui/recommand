"""稽核步骤 Pipeline

依次跑指标 + 写报告;不修改输入数据。
"""

import logging
from typing import Any, Dict
from pyspark.sql import DataFrame

from . import metrics
from .reporter import AuditReporter


logger = logging.getLogger(__name__)


class AuditPipeline:
    """数据质量稽核 Pipeline"""

    def __init__(self, config):
        self.config = config
        self.reporter = AuditReporter(config.audit.output_dir)

    def run(self, users_df: DataFrame, items_df: DataFrame, interactions_df: DataFrame) -> Dict[str, Any]:
        if not self.config.audit.enabled:
            logger.info("稽核步骤被禁用,跳过")
            return {"enabled": False}

        logger.info("====== 开始稽核步骤 ======")
        report: Dict[str, Any] = {
            "users": {},
            "items": {},
            "interactions": {},
        }

        # --- users ---
        if self.config.audit.metrics_row_count:
            report["users"]["row_count"] = metrics.row_count(users_df)
        if self.config.audit.metrics_field_completeness:
            report["users"]["field_completeness"] = metrics.field_completeness(users_df, ["user_id"])
        if self.config.audit.metrics_primary_key_uniqueness:
            report["users"]["primary_key_uniqueness"] = metrics.primary_key_uniqueness(users_df, ["user_id"])

        # --- items ---
        if self.config.audit.metrics_row_count:
            report["items"]["row_count"] = metrics.row_count(items_df)
        if self.config.audit.metrics_field_completeness:
            report["items"]["field_completeness"] = metrics.field_completeness(items_df, ["item_id"])
        if self.config.audit.metrics_primary_key_uniqueness:
            report["items"]["primary_key_uniqueness"] = metrics.primary_key_uniqueness(items_df, ["item_id"])

        # --- interactions ---
        if self.config.audit.metrics_row_count:
            report["interactions"]["row_count"] = metrics.row_count(interactions_df)
        if self.config.audit.metrics_field_completeness:
            report["interactions"]["field_completeness"] = metrics.field_completeness(
                interactions_df, self.config.cleaning.required_fields
            )
        if self.config.audit.metrics_primary_key_uniqueness:
            report["interactions"]["primary_key_uniqueness"] = metrics.primary_key_uniqueness(
                interactions_df, ["user_id", "item_id", "timestamp"]
            )
        if self.config.audit.metrics_time_range:
            report["interactions"]["time_range"] = metrics.time_range(interactions_df, "timestamp")
        if self.config.audit.metrics_outlier_check and self.config.audit.outlier_rules:
            report["interactions"]["outlier_check"] = metrics.outlier_check(
                interactions_df, self.config.audit.outlier_rules
            )

        self.reporter.write(report)
        return report
