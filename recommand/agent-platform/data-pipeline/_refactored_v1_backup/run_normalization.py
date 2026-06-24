#!/usr/bin/env python3
"""步骤 3: 数据标准化

读清洗后数据 → 按配置应用 normalizer → 写出标准化数据
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import SparkManager, load_config, setup_logging
from normalization import NormalizationPipeline
from writers import write_dataframe


def get_args():
    p = argparse.ArgumentParser(description="数据标准化")
    p.add_argument("--config", "-c", type=str, default="configs/datasets/amazon.yaml")
    p.add_argument("--input", "-i", type=str, default="./cleaned", help="清洗后数据目录")
    p.add_argument("--output", "-o", type=str, default="./normalized")
    p.add_argument("--master", type=str, default="")
    p.add_argument("--driver-memory", type=str, default="")
    p.add_argument("--partitions", type=int, default=None)
    return p.parse_args()


def main():
    args = get_args()
    setup_logging()
    logger = logging.getLogger("run_normalization")

    config = load_config(args.config)
    if args.master:
        config.spark.master = args.master
    if args.driver_memory:
        config.spark.memory = args.driver_memory
    if args.partitions:
        config.spark.partitions = args.partitions

    spark_manager = SparkManager(app_name="DataNormalization", **{
        "memory": config.spark.memory,
        "partitions": config.spark.partitions,
        "master": config.spark.master,
    })
    spark = spark_manager.get_session()
    try:
        users_df = spark.read.parquet(os.path.join(args.input, "users.parquet"))
        items_df = spark.read.parquet(os.path.join(args.input, "items.parquet"))
        interactions_df = spark.read.parquet(os.path.join(args.input, "interactions.parquet"))

        results = NormalizationPipeline(config).run(users_df, items_df, interactions_df)
        write_dataframe(results["users"], args.output, "users")
        write_dataframe(results["items"], args.output, "items")
        write_dataframe(results["interactions"], args.output, "interactions")
        logger.info("标准化完成; 输出目录: %s", args.output)
    finally:
        spark_manager.stop()


if __name__ == "__main__":
    main()
