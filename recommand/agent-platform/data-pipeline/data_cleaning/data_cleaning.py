#!/usr/bin/env python3
"""
亚马逊数据集数据清洗 - 主入口

功能：
1. 字段完整性过滤：关键字段非空
2. 异常值过滤：评分异常、时间戳异常
3. 数据质量过滤：空值、过短文本
4. 垃圾数据过滤：检测垃圾评论
5. 时间过滤：只保留最近 N 年以内的评论
6. 文本长度过滤：reviewText 长度 <= 700
7. 去重：reviewText 完全一致的记录去重，只保留一条
8. K-core 过滤：用户和商品至少包含 5 条记录
9. 突发评论过滤：10分钟内发布50条以上评论的用户记录清理
10. 同步清洗 meta 数据：只保留清洗后评论中存在的商品

使用方法：
    # 使用命令行参数
    python data_cleaning.py -ri /path/to/reviews.json -mi /path/to/meta.json -o /path/to/output

    # 使用配置文件
    python data_cleaning.py --config /path/to/config.yaml

    # 配置文件 + 命令行参数（命令行优先级更高）
    python data_cleaning.py --config /path/to/config.yaml -o /path/to/output
"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

import os
import sys

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from spark_manager import SparkManager
from data_loader import DataLoader
from pipeline import CleaningPipeline
from meta_cleaner import MetaCleaner
from data_saver import DataSaver
from summary import SummaryGenerator
from config_loader import Config, merge_args_with_config
from filters import (
    FieldCompletenessFilter,
    OutlierFilter,
    QualityFilter,
    SpamFilter,
    TimeFilter,
    TextLengthFilter,
    DeduplicateFilter,
    UserProductDeduplicateFilter,
    KCoreFilter,
    BurstReviewFilter,
)


def build_pipeline_from_config(cleaning_config: dict) -> CleaningPipeline:
    """根据配置构建清洗流程"""
    pipeline = CleaningPipeline()

    # 步骤1: 字段完整性过滤
    if cleaning_config.get('field_completeness', {}).get('enabled', True):
        cfg = cleaning_config['field_completeness']
        pipeline.add_filter(FieldCompletenessFilter(
            required_fields=cfg.get('required_fields', ['user_id', 'product_id', 'review_text', 'timestamp'])
        ))

    # 步骤2: 异常值过滤
    if cleaning_config.get('outlier', {}).get('enabled', True):
        cfg = cleaning_config['outlier']
        pipeline.add_filter(OutlierFilter(
            min_rating=cfg.get('min_rating', 1.0),
            max_rating=cfg.get('max_rating', 5.0),
            min_year=cfg.get('min_year', 1990)
        ))

    # 步骤3: 数据质量过滤
    if cleaning_config.get('quality', {}).get('enabled', True):
        cfg = cleaning_config['quality']
        pipeline.add_filter(QualityFilter(
            min_text_length=cfg.get('min_text_length', 10)
        ))

    # 步骤4: 垃圾数据过滤
    if cleaning_config.get('spam', {}).get('enabled', True):
        cfg = cleaning_config['spam']
        pipeline.add_filter(SpamFilter(
            custom_patterns=cfg.get('custom_patterns', [])
        ))

    # 步骤5: 时间过滤
    if cleaning_config.get('time', {}).get('enabled', True):
        cfg = cleaning_config['time']
        pipeline.add_filter(TimeFilter(
            years=cfg.get('years', 10)
        ))

    # 步骤6: 文本长度过滤
    if cleaning_config.get('text_length', {}).get('enabled', True):
        cfg = cleaning_config['text_length']
        pipeline.add_filter(TextLengthFilter(
            max_length=cfg.get('max_length', 700)
        ))

    # 步骤7: 去重
    if cleaning_config.get('deduplicate', {}).get('enabled', True):
        cfg = cleaning_config['deduplicate']
        pipeline.add_filter(DeduplicateFilter(
            key_column=cfg.get('key_column', 'review_text')
        ))

    # 步骤8: 突发评论过滤（短时间内评论次数过多）
    if cleaning_config.get('burst_review', {}).get('enabled', True):
        cfg = cleaning_config['burst_review']
        pipeline.add_filter(BurstReviewFilter(
            time_window_minutes=cfg.get('time_window_minutes', 10),
            max_reviews=cfg.get('max_reviews', 50)
        ))

    # 步骤9: 用户-商品连续去重（同一用户对同一商品的连续评论只保留一条，在K-core之前）
    if cleaning_config.get('user_product_dedup', {}).get('enabled', True):
        pipeline.add_filter(UserProductDeduplicateFilter())

    # 步骤10: K-core过滤
    if cleaning_config.get('kcore', {}).get('enabled', True):
        cfg = cleaning_config['kcore']
        pipeline.add_filter(KCoreFilter(k=cfg.get('k', 5), checkpoint_dir=cfg.get('checkpoint_dir')))

    return pipeline


def main():
    import argparse

    parser = argparse.ArgumentParser(description="亚马逊数据集数据清洗")

    # 配置文件
    parser.add_argument("--config", "-c", type=str, default=None,
                        help="配置文件路径 (YAML格式)")

    # 数据源（命令行必填，但配置文件可覆盖）
    parser.add_argument("--review-input", "-ri", type=str, default="",
                        help="评论数据输入路径")
    parser.add_argument("--meta-input", "-mi", type=str, default="",
                        help="元数据输入路径")
    parser.add_argument("--output", "-o", type=str, default="",
                        help="输出目录")
    parser.add_argument("--source-type", "-s", type=str, default="",
                        choices=["amazon_new", "amazon_old"], help="数据源类型")

    # 清洗参数
    parser.add_argument("--max-length", "-l", type=int, default=None, help="评论文本最大长度")
    parser.add_argument("--min-length", type=int, default=None, help="评论文本最小长度")
    parser.add_argument("--years", "-y", type=int, default=None, help="保留最近 N 年")
    parser.add_argument("--k-core", "-k", type=int, default=None, help="K-core 阈值")
    parser.add_argument("--min-rating", type=float, default=None, help="最小评分")
    parser.add_argument("--max-rating", type=float, default=None, help="最大评分")

    # 输出配置
    parser.add_argument("--format", "-f", type=str, default=None,
                        choices=["json", "parquet", "csv"], help="输出格式")

    # Spark配置
    parser.add_argument("--master", type=str, default="",
                        help="Spark master URL (如 local[*] 或 spark://host:7077)")
    parser.add_argument("--driver-memory", type=str, default="",
                        help="Driver 内存 (如 4g, 8g)")
    parser.add_argument("--driver-cores", type=int, default=None,
                        help="Driver CPU 核心数")
    parser.add_argument("--executor-cores", type=int, default=None,
                        help="Executor CPU 核心数")
    parser.add_argument("--executor-memory", type=str, default="",
                        help="Executor 内存 (如 4g, 8g)")
    parser.add_argument("--executor-numbers", type=int, default=None,
                        help="Executor 数量")
    parser.add_argument("--partitions", type=int, default=None,
                        help="Shuffle 分区数")

    args = parser.parse_args()

    # 加载配置文件
    config = None
    if args.config:
        if not os.path.exists(args.config):
            print(f"错误: 配置文件不存在: {args.config}")
            sys.exit(1)
        config = Config(args.config)
        print(f"已加载配置文件: {args.config}")
    else:
        # 使用默认配置文件
        default_config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
        if os.path.exists(default_config_path):
            config = Config(default_config_path)
            print(f"已加载默认配置文件: {default_config_path}")

    # 合并配置（命令行优先级高于配置文件）
    merged_config = merge_args_with_config(args, config) if config else {
        'review_input': args.review_input,
        'meta_input': args.meta_input,
        'output': args.output,
        'source_type': args.source_type,
        'output_format': args.format or 'json',
        'spark': {
            'master': args.master or 'local[*]',
            'memory': args.driver_memory or '4g',
            'driver_cores': args.driver_cores or 2,
            'executor_cores': args.executor_cores or 2,
            'executor_memory': args.executor_memory or '4g',
            'executor_numbers': args.executor_numbers or 1,
            'partitions': args.partitions or 8
        }
    }

    # 验证必填参数
    if not merged_config.get('review_input'):
        parser.error("--review-input 或 config.data.review_input 必须指定")
    if not merged_config.get('meta_input'):
        parser.error("--meta-input 或 config.data.meta_input 必须指定")
    if not merged_config.get('output'):
        parser.error("--output 或 config.data.output 必须指定")

    # 打印配置信息
    print("=" * 60)
    print("亚马逊数据集数据清洗")
    print("=" * 60)
    print(f"评论输入: {merged_config['review_input']}")
    print(f"元数据输入: {merged_config['meta_input']}")
    print(f"输出目录: {merged_config['output']}")
    print(f"数据源: {merged_config['source_type']}")

    # 初始化Spark
    spark_config = merged_config.get('spark', {'memory': '4g', 'partitions': 8})
    spark_manager = SparkManager(
        memory=spark_config.get('memory', '4g'),
        partitions=spark_config.get('partitions', 8),
        driver_cores=spark_config.get('driver_cores', 2),
        executor_cores=spark_config.get('executor_cores', 2),
        executor_memory=spark_config.get('executor_memory', '4g'),
        executor_numbers=spark_config.get('executor_numbers', 1),
        master=spark_config.get('master', 'local[*]'),
        local_dir=spark_config.get('local_dir', '/tmp/spark-tmp')
    )
    spark = spark_manager.get_session()

    # 加载数据
    print("\n加载数据...")
    loader = DataLoader(spark)
    reviews_df = loader.load_review_data(merged_config['review_input'], merged_config['source_type'])
    meta_df = loader.load_meta_data(merged_config['meta_input'])

    original_review_count = reviews_df.count()
    original_meta_count = meta_df.count()

    print(f"   评论: {original_review_count:,} 条")
    print(f"   元数据: {original_meta_count:,} 条")

    # 构建清洗流程
    pipeline = build_pipeline_from_config(merged_config['cleaning'])

    # 执行清洗流程
    print(f"\n共 {len(pipeline.filters)} 个过滤步骤")
    cleaned_reviews_df = pipeline.run(reviews_df)
    pipeline_stats = pipeline.get_stats()

    # 清洗元数据
    meta_cleaner = MetaCleaner()
    meta_cleaned = meta_cleaner.clean(meta_df, cleaned_reviews_df)

    # 打印汇总并保存报告
    summary_gen = SummaryGenerator()
    summary_gen.generate(
        cleaned_reviews_df, meta_cleaned,
        original_review_count, original_meta_count,
        pipeline_stats,
        output_path=merged_config['output']
    )

    # 保存结果
    saver = DataSaver(merged_config['output'], merged_config['output_format'])
    saver.save(cleaned_reviews_df, meta_cleaned)

    # 停止Spark
    spark_manager.stop()

    print("\n" + "=" * 60)
    print("数据清洗完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
