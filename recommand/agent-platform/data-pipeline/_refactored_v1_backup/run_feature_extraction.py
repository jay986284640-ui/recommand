#!/usr/bin/env python3
"""步骤 4: 特征提取

读标准化后数据 → 5 类特征 → 写出
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import SparkManager, load_config, setup_logging
from feature_extraction import FeatureExtractionPipeline


def get_args():
    p = argparse.ArgumentParser(description="特征提取")
    p.add_argument("--config", "-c", type=str, default="configs/datasets/amazon.yaml")
    p.add_argument("--input", "-i", type=str, default="./normalized", help="标准化后数据目录")
    p.add_argument("--master", type=str, default="")
    p.add_argument("--driver-memory", type=str, default="")
    p.add_argument("--partitions", type=int, default=None)
    return p.parse_args()


def main():
    args = get_args()
    setup_logging()
    logger = logging.getLogger("run_feature_extraction")

    config = load_config(args.config)
    if args.master:
        config.spark.master = args.master
    if args.driver_memory:
        config.spark.memory = args.driver_memory
    if args.partitions:
        config.spark.partitions = args.partitions

    spark_manager = SparkManager(app_name="FeatureExtraction", **{
        "memory": config.spark.memory,
        "partitions": config.spark.partitions,
        "master": config.spark.master,
    })
    spark = spark_manager.get_session()
    try:
        users_df = spark.read.parquet(os.path.join(args.input, "users.parquet"))
        items_df = spark.read.parquet(os.path.join(args.input, "items.parquet"))
        interactions_df = spark.read.parquet(os.path.join(args.input, "interactions.parquet"))

        outputs = FeatureExtractionPipeline(config, spark).run(users_df, items_df, interactions_df)
        logger.info("特征提取完成; 输出: %s", outputs)
    finally:
        spark_manager.stop()


if __name__ == "__main__":
    main()
