#!/usr/bin/env python3
"""一键跑完 4 步管线

audit → cleaning → normalization → feature_extraction
所有步骤共享同一个 SparkSession。
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import SparkManager, load_config, setup_logging
from adapters import AdapterFactory
from audit import AuditPipeline
from cleaning import CleaningPipeline
from normalization import NormalizationPipeline
from feature_extraction import FeatureExtractionPipeline
from writers import write_dataframe


def get_args():
    p = argparse.ArgumentParser(description="一键跑 4 步数据处理管线")
    p.add_argument("--config", "-c", type=str, default="configs/datasets/amazon.yaml")
    p.add_argument("--input", "-i", type=str, default=None,
                   help="中间格式数据目录(可选;不传则用适配器)")
    p.add_argument("--output-dir", "-o", type=str, default="./pipeline_output",
                   help="输出根目录,会建立 cleaned/ normalized/ features/ 子目录")
    p.add_argument("--skip-audit", action="store_true")
    p.add_argument("--skip-cleaning", action="store_true")
    p.add_argument("--skip-normalization", action="store_true")
    p.add_argument("--skip-feature-extraction", action="store_true")
    p.add_argument("--master", type=str, default="")
    p.add_argument("--driver-memory", type=str, default="")
    p.add_argument("--partitions", type=int, default=None)
    return p.parse_args()


def main():
    args = get_args()
    setup_logging()
    logger = logging.getLogger("run_pipeline")

    config = load_config(args.config)
    if args.master:
        config.spark.master = args.master
    if args.driver_memory:
        config.spark.memory = args.driver_memory
    if args.partitions:
        config.spark.partitions = args.partitions

    out = args.output_dir
    cleaned_dir = os.path.join(out, "cleaned")
    normalized_dir = os.path.join(out, "normalized")
    config.feature_extraction.output_dir = os.path.join(out, "features")
    config.audit.output_dir = os.path.join(out, "audit")
    for d in (cleaned_dir, normalized_dir, config.feature_extraction.output_dir, config.audit.output_dir):
        os.makedirs(d, exist_ok=True)

    spark_manager = SparkManager(app_name="DataPipelineAll", **{
        "memory": config.spark.memory,
        "partitions": config.spark.partitions,
        "master": config.spark.master,
    })
    spark = spark_manager.get_session()
    try:
        # 加载原始数据
        if args.input:
            users_df = spark.read.parquet(os.path.join(args.input, "users.parquet"))
            items_df = spark.read.parquet(os.path.join(args.input, "items.parquet"))
            interactions_df = spark.read.parquet(os.path.join(args.input, "interactions.parquet"))
        else:
            adapter = AdapterFactory.create(config.data.adapter, spark, config.data.adapter_config)
            users_df = adapter.get_users()
            items_df = adapter.get_items()
            interactions_df = adapter.get_interactions()
            co_occurrence_df = adapter.get_co_occurrence()
            # co_occurrence 进入清洗(此处简单丢弃,实际项目可并入 items)
            if co_occurrence_df is not None:
                logger.info("co_occurrence_df: %d 行 (本次不参与清洗)", co_occurrence_df.count())

        # 1) audit
        if not args.skip_audit:
            logger.info("=== 步骤 1/4: audit ===")
            AuditPipeline(config).run(users_df, items_df, interactions_df)

        # 2) cleaning
        if not args.skip_cleaning:
            logger.info("=== 步骤 2/4: cleaning ===")
            cleaned = CleaningPipeline(config).run(users_df, items_df, interactions_df)
            write_dataframe(cleaned["users"], cleaned_dir, "users")
            write_dataframe(cleaned["items"], cleaned_dir, "items")
            write_dataframe(cleaned["interactions"], cleaned_dir, "interactions")
            users_df, items_df, interactions_df = cleaned["users"], cleaned["items"], cleaned["interactions"]

        # 3) normalization
        if not args.skip_normalization:
            logger.info("=== 步骤 3/4: normalization ===")
            normalized = NormalizationPipeline(config).run(users_df, items_df, interactions_df)
            write_dataframe(normalized["users"], normalized_dir, "users")
            write_dataframe(normalized["items"], normalized_dir, "items")
            write_dataframe(normalized["interactions"], normalized_dir, "interactions")
            users_df, items_df, interactions_df = normalized["users"], normalized["items"], normalized["interactions"]

        # 4) feature_extraction
        if not args.skip_feature_extraction:
            logger.info("=== 步骤 4/4: feature_extraction ===")
            FeatureExtractionPipeline(config, spark).run(users_df, items_df, interactions_df)

        logger.info("4 步管线全部完成; 输出根目录: %s", out)
    finally:
        spark_manager.stop()


if __name__ == "__main__":
    main()
