"""audit Pipeline + 报告写出测试"""

import json
import os
import tempfile
from pyspark.sql.types import StructType, StructField, StringType, LongType

from common.config_loader import Config
from audit import AuditPipeline


def _df(spark):
    schema = StructType([
        StructField("user_id", StringType()),
        StructField("item_id", StringType()),
        StructField("timestamp", LongType()),
    ])
    return (
        spark.createDataFrame(
            [("u1", "i1", 1000), ("u2", "i1", 2000), ("u1", "i2", 3000)],
            schema,
        ),
        spark.createDataFrame(
            [("i1", "Product A"), ("i2", "Product B")],
            "item_id STRING, item_title STRING",
        ),
        spark.createDataFrame(
            [("u1", "i1", 1000), ("u1", "i1", 1000), ("u2", "i1", 2000), ("u1", "i2", 3000)],
            schema,
        ),
    )


def test_audit_pipeline_writes_report(spark):
    with tempfile.TemporaryDirectory() as tmpdir:
        config = Config()
        config.audit.output_dir = tmpdir
        users, items, inters = _df(spark)
        report = AuditPipeline(config).run(users, items, inters)
        assert "interactions" in report
        assert report["interactions"]["row_count"]["row_count"] == 4
        # 报告应已写到 tmpdir/audit_report.json
        path = os.path.join(tmpdir, "audit_report.json")
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert "generated_at" in data
        assert data["interactions"]["row_count"]["row_count"] == 4


def test_audit_pipeline_disabled(spark):
    config = Config()
    config.audit.enabled = False
    users, items, inters = _df(spark)
    report = AuditPipeline(config).run(users, items, inters)
    assert report == {"enabled": False}
