"""稽核报告输出器"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict


logger = logging.getLogger(__name__)


class AuditReporter:
    """把指标字典写入 audit_report.json"""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def write(self, report: Dict[str, Any], filename: str = "audit_report.json") -> str:
        report = dict(report)
        report.setdefault("generated_at", datetime.utcnow().isoformat() + "Z")
        path = os.path.join(self.output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("稽核报告已写入: %s", path)
        return path
