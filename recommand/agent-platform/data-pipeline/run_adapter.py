#!/usr/bin/env python3
"""
数据适配器脚本 - 将异构数据转换为标准中间格式

功能：
1. 通过 Adapter 将原始数据转换为标准中间格式
2. 保存到指定目录供后续处理使用

使用方法：
    python run_adapter.py --config config/datasets/amazon.yaml --output ./intermediate

    # 指定数据路径
    python run_adapter.py --config config/datasets/amazon.yaml \
        --review-input /path/to/reviews.json \
        --meta-input /path/to/meta.json \
        --output ./intermediate
"""

import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
from processing import load_config, SparkManager, Config
from adapters import AdapterFactory
from processing.writers import DataWriter
from pyspark.sql import SparkSession


# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def _merge_config(config: Config, args):
    # 命令行参数覆盖
    if args.adapter:
        config.data.adapter = args.adapter
    if args.output:
        config.output.dir = args.output
    if args.format:
        config.output.format = args.format
    if args.master:
        config.spark.master = args.master
    if args.driver_memory:
        config.spark.memory = args.driver_memory
    if args.partitions:
        config.spark.partitions = args.partitions
    return config

def get_config() -> Config:
    parser = argparse.ArgumentParser(description="数据适配器 - 转换异构数据为标准中间格式")
    parser.add_argument("--config", "-c", type=str, default="",
                        help="配置文件路径 (YAML格式)")
    parser.add_argument("--adapter", "-a", type=str, default="",
                        help="适配器名称 (如 amazon, amazon_old, tiktok)")
    parser.add_argument("--review-input", "-ri", type=str, default="",
                        help="评论/交互数据输入路径")
    parser.add_argument("--meta-input", "-mi", type=str, default="",
                        help="元数据/物品数据输入路径")
    parser.add_argument("--co-occurrence-input", "-ci", type=str, default="",
                        help="共现数据输入路径 (可选)")
    parser.add_argument("--output", "-o", type=str, default="",
                        help="输出目录（中间格式）")
    parser.add_argument("--format", "-f", type=str, default="json",
                        choices=["json", "parquet", "csv"], help="输出格式")
    parser.add_argument("--master", type=str, default="", help="Spark master URL")
    parser.add_argument("--driver-memory", type=str, default="", help="Driver 内存")
    parser.add_argument("--partitions", type=int, default=None, help="Shuffle 分区数")

    args = parser.parse_args()

    # 加载配置
    config = None
    if args.config:
        if not os.path.exists(args.config):
            logger.error("配置文件不存在: %s", args.config)
            sys.exit(1)
        config = load_config(args.config)
        logger.info("已加载配置文件: %s", args.config)
    else:
        config = Config()
        logger.info("使用默认配置")

    config = _merge_config(config, args)

    # 验证必填参数
    if not config.output.dir:
        parser.error("--output 或 config.output.dir 必须指定")

    return config


def log_base_info(config: Config) -> None:
    # 打印配置
    logger.info("数据适配器 - 异构数据转换为标准中间格式")
    logger.info("适配器: %s", config.data.adapter)
    logger.info("适配器配置: %s", config.data.adapter_config)
    logger.info("输出目录: %s", config.output.dir)
    logger.info("输出格式: %s", config.output.format)


def run_adapter(config: Config, spark: SparkSession) -> None:
    # 创建适配器
    logger.info("创建数据适配器...")
    # 所有配置都通过 adapter_config 传递
    adapter_config = dict(config.data.adapter_config)
    adapter = AdapterFactory.create(config.data.adapter, spark, adapter_config)

    # 验证适配器配置
    adapter.validate_config()

    # 打印适配器 Schema 信息
    logger.info("适配器输出 Schema 信息:")
    schema_info = adapter.get_schema_info()
    for key, fields in schema_info.items():
        if fields:
            logger.info("  %s: %s", key, fields)

    # 加载数据
    logger.info("加载数据...")
    users_df = adapter.get_users()
    items_df = adapter.get_items()
    interactions_df = adapter.get_interactions()
    co_occurrence_df = adapter.get_co_occurrence()

    logger.info("用户数: %d", users_df.count())
    logger.info("物品数: %d", items_df.count())
    logger.info("交互数: %d", interactions_df.count())
    if co_occurrence_df:
        logger.info("共现数: %d", co_occurrence_df.count())

    # 保存中间格式
    logger.info("保存标准中间格式...")
    writer = DataWriter(config.output.dir, config.output.format)
    writer.write_users(users_df)
    writer.write_items(items_df)
    writer.write_interactions(interactions_df)
    if co_occurrence_df is not None:
        writer.write_co_occurrence(co_occurrence_df)

    logger.info("适配器处理完成! 标准中间格式已保存。后续可使用 run_pipeline.py 进行数据清洗和标准化处理")
    logger.info("中间格式数据位置: %s", config.output.dir)


def main():
    # 获取配置参数
    config = get_config()
    log_base_info(config)

    # 获取标准化数据
    try:
        # 初始化 Spark
        logger.info("初始化 Spark...")
        spark_manager = SparkManager(
            app_name="DataAdapter",
            memory=config.spark.memory,
            partitions=config.spark.partitions,
            driver_cores=config.spark.driver_cores,
            master=config.spark.master,
            local_dir=config.spark.local_dir,
        )
        spark = spark_manager.get_session()
        run_adapter(config, spark)
    except Exception as e:
        logger.error("适配器处理失败: %s", str(e))
    finally:
        # 停止 Spark
        spark_manager.stop()


if __name__ == "__main__":
    main()