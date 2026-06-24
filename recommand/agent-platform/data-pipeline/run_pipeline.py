#!/usr/bin/env python3
"""
数据处理流程脚本 - 对标准中间格式数据进行清洗、标准化和序列构建

功能：
1. 读取标准中间格式数据
2. 数据清洗（字段完整性、时间、K-core、去重等）
3. 文本标准化
4. 用户行为序列构建
5. 按实体类型输出标准格式数据

使用方法：
    # 读取中间格式数据进行处理
    python run_pipeline.py --input ./intermediate --output ./output

    # 使用配置文件
    python run_pipeline.py --config config/datasets/amazon.yaml
"""
import time
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
from processing import load_config, SparkManager, UnifiedPipeline, Config
from processing.writers import DataWriter


# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def load_intermediate_data(spark, input_dir: str, format: str = "json"):
    """
    加载标准中间格式数据

    Args:
        spark: SparkSession
        input_dir: 中间格式数据目录
        format: 数据格式

    Returns:
        (users_df, items_df, interactions_df, co_occurrence_df)
    """
    from pyspark.sql import DataFrame

    users_path = os.path.join(input_dir, f"users.{format}")
    items_path = os.path.join(input_dir, f"items.{format}")
    interactions_path = os.path.join(input_dir, f"interactions.{format}")
    co_occurrence_path = os.path.join(input_dir, f"co_occurrence.{format}")

    logger.info("加载用户数据: %s", users_path)
    users_df = spark.read.format(format).load(users_path) if os.path.exists(users_path) else None

    logger.info("加载物品数据: %s", items_path)
    items_df = spark.read.format(format).load(items_path) if os.path.exists(items_path) else None

    logger.info("加载交互数据: %s", interactions_path)
    interactions_df = spark.read.format(format).load(interactions_path) if os.path.exists(interactions_path) else None

    logger.info("加载共现数据: %s", co_occurrence_path)
    co_occurrence_df = spark.read.format(format).load(co_occurrence_path) if os.path.exists(co_occurrence_path) else None

    # 如果不存在用户表，从交互数据提取
    if users_df is None and interactions_df is not None:
        logger.info("用户表不存在，从交互数据提取...")
        from pyspark.sql import functions as F
        users_df = interactions_df.select("user_id").distinct()
        # 添加默认列
        users_df = users_df.withColumn("interaction_count", F.lit(0))

    # 如果不存在物品表，从交互数据提取
    if items_df is None and interactions_df is not None:
        logger.info("物品表不存在，从交互数据提取...")
        from pyspark.sql import functions as F
        items_df = interactions_df.select("item_id").distinct()
        # 添加默认列
        items_df = items_df.withColumn("item_title", F.lit(None))

    return users_df, items_df, interactions_df, co_occurrence_df


def load_data(config, intermediate_input, spark):
    logger.info("加载数据...")
    if intermediate_input:
        # 从中间格式加载
        users_df, items_df, interactions_df, co_occurrence_df = load_intermediate_data(
            spark, intermediate_input, config.output.format
        )
    else:
        # 通过适配器加载
        from adapters import AdapterFactory
        adapter_config = {
            "review_input": config.data.review_input,
            "meta_input": config.data.meta_input,
            "co_occurrence_input": config.data.co_occurrence_input,
        }
        adapter = AdapterFactory.create(config.data.adapter, spark, adapter_config)
        users_df = adapter.get_users()
        items_df = adapter.get_items()
        interactions_df = adapter.get_interactions()
        co_occurrence_df = adapter.get_co_occurrence()
    
    logger.info("用户数: %d", users_df.count())
    logger.info("物品数: %d", items_df.count())
    logger.info("交互数: %d", interactions_df.count())
    if co_occurrence_df:
        logger.info("共现数: %d", co_occurrence_df.count())
    return users_df,items_df,interactions_df,co_occurrence_df


def get_config():
    parser = argparse.ArgumentParser(
        description="数据处理流程 - 清洗、标准化、序列构建",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 从中间格式处理
  python run_pipeline.py --input ./intermediate --output ./output
  # 从配置文件处理（自动调用适配器）
  python run_pipeline.py --config config/datasets/amazon.yaml
        """
    )

    # 配置文件
    parser.add_argument("--config", "-c", type=str, default="config/datasets/amazon.yaml",
                        help="配置文件路径 (YAML格式)")

    # 中间格式数据路径
    parser.add_argument("--input", "-i", type=str, default="./intermediate",
                        help="中间格式数据目录")
    parser.add_argument("--output", "-o", type=str, default="./output",
                        help="输出目录")
    parser.add_argument("--format", "-f", type=str, default="json",
                        choices=["json", "parquet", "csv"], help="数据格式")

    # 清洗配置
    parser.add_argument("--k-core", "-k", type=int, default=None,
                        help="K-core 阈值")
    parser.add_argument("--min-text-length", type=int, default=None,
                        help="最小文本长度")
    parser.add_argument("--years", "-y", type=int, default=None,
                        help="保留最近 N 年")

    # Spark 配置
    parser.add_argument("--master", type=str, default="",
                        help="Spark master URL")
    parser.add_argument("--driver-memory", type=str, default="",
                        help="Driver 内存")
    parser.add_argument("--partitions", type=int, default=None,
                        help="Shuffle 分区数")

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

    # 命令行参数覆盖配置文件参数
    config = _merge_config(config, args)

    # 验证参数
    if not config.output.dir:
        parser.error("--output 或 config.output.dir 必须指定")
    return config


def _merge_config(config: Config, args):
    # 命令行参数覆盖
    if args.input:
        config.output.save_intermediate = True
        config.data.intermediate_input = args.input
    if args.output:
        config.output.dir = args.output
    if args.format:
        config.output.format = args.format
    if args.k_core:
        config.cleaning.kcore_k = args.k_core
    if args.min_text_length:
        config.cleaning.min_text_length = args.min_text_length
    if args.years:
        config.cleaning.years = args.years
    if args.master:
        config.spark.master = args.master
    if args.driver_memory:
        config.spark.memory = args.driver_memory
    if args.partitions:
        config.spark.partitions = args.partitions
    return config


def main():
    config = get_config()

    # 如果有中间格式数据路径，直接加载
    intermediate_input = getattr(config.data, 'intermediate_input', None)

    # 打印配置
    logger.info("数据处理流程 - 清洗、标准化、序列构建")

    if intermediate_input:
        logger.info("输入目录（中间格式）: %s", intermediate_input)
    else:
        logger.info("适配器: %s", config.data.adapter)
        logger.info("适配器配置: %s", config.data.adapter_config)

    logger.info("输出目录: %s", config.output.dir)
    logger.info("输出格式: %s", config.output.format)

    # 初始化 Spark
    logger.info("初始化 Spark...")
    spark_manager = SparkManager(
        app_name="DataPipeline",
        memory=config.spark.memory,
        partitions=config.spark.partitions,
        driver_cores=config.spark.driver_cores,
        master=config.spark.master,
        local_dir=config.spark.local_dir,
        checkpoint_dir=config.spark.checkpoint_dir
    )
    spark = spark_manager.get_session()

    # 加载数据
    users_df, items_df, interactions_df, co_occurrence_df = load_data(config, intermediate_input, spark)

    # 创建处理流程
    logger.info("创建处理流程...")
    pipeline = UnifiedPipeline(config, items_df=items_df)

    # 执行处理
    results = pipeline.process(
        users_df=users_df,
        items_df=items_df,
        interactions_df=interactions_df,
        co_occurrence_df=co_occurrence_df
    )

    # 保存结果
    pipeline.save_results(results)
    # 停止 Spark
    spark_manager.stop()

    logger.info("数据处理完成!")


if __name__ == "__main__":
    main()
