#!/usr/bin/env python3
"""步骤 1: 数据质量稽核

读中间格式 / 适配器 → 跑稽核指标 → 写 audit_report.json
不改输入数据。
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import SparkManager, load_config, setup_logging
from adapters import AdapterFactory
from audit import AuditPipeline


def get_args():
    p = argparse.ArgumentParser(description="数据质量稽核")
    p.add_argument("--config", "-c", type=str, default="configs/datasets/amazon.yaml")
    p.add_argument("--input", "-i", type=str, default=None,
                   help="中间格式数据目录(可选;不传则用适配器)")
    p.add_argument("--master", type=str, default="")
    p.add_argument("--driver-memory", type=str, default="")
    p.add_argument("--partitions", type=int, default=None)
    return p.parse_args()


def main():
    args = get_args()
    setup_logging()
    logger = logging.getLogger("run_audit")

    config = load_config(args.config)
    if args.master:
        config.spark.master = args.master
    if args.driver_memory:
        config.spark.memory = args.driver_memory
    if args.partitions:
        config.spark.partitions = args.partitions

    spark_manager = SparkManager(app_name="DataAudit", **{
        "memory": config.spark.memory,
        "partitions": config.spark.partitions,
        "master": config.spark.master,
    })
    spark = spark_manager.get_session()
    try:
        if args.input:
            users_df = spark.read.parquet(os.path.join(args.input, "users.parquet"))
            items_df = spark.read.parquet(os.path.join(args.input, "items.parquet"))
            interactions_df = spark.read.parquet(os.path.join(args.input, "interactions.parquet"))
        else:
            adapter = AdapterFactory.create(config.data.adapter, spark, config.data.adapter_config)
            users_df = adapter.get_users()
            items_df = adapter.get_items()
            interactions_df = adapter.get_interactions()
        report = AuditPipeline(config).run(users_df, items_df, interactions_df)
        logger.info("稽核完成; 报告路径: %s", config.audit.output_dir)
    finally:
        spark_manager.stop()


if __name__ == "__main__":
    main()
