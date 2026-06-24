"""配置加载模块"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

import os
from typing import Any, Dict

import yaml


class Config:
    """配置管理类"""

    def __init__(self, config_path: str = None):
        self.config: Dict[str, Any] = {}
        if config_path and os.path.exists(config_path):
            self.load(config_path)

    def load(self, config_path: str):
        """从YAML文件加载配置"""
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点号访问，如 'data.review_input'"""
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    def get_section(self, section: str) -> Dict[str, Any]:
        """获取配置节"""
        return self.config.get(section, {})

    def is_enabled(self, section: str, key: str = "enabled") -> bool:
        """检查是否启用某个功能"""
        return self.get(f"{section}.{key}", True)

    def __repr__(self) -> str:
        return f"Config({self.config})"


def merge_args_with_config(args, config: Config) -> Dict[str, Any]:
    """
    合并命令行参数和配置文件
    命令行参数优先级高于配置文件
    """
    result = {}

    # 数据源配置
    result['review_input'] = args.review_input or config.get('data.review_input', '')
    result['meta_input'] = args.meta_input or config.get('data.meta_input', '')
    result['output'] = args.output or config.get('data.output', '')
    result['source_type'] = args.source_type or config.get('data.source_type', 'amazon_new')

    # 清洗参数
    cleaning = {}

    # 字段完整性过滤
    if config.is_enabled('cleaning.field_completeness'):
        field_cfg = config.get_section('cleaning.field_completeness')
        cleaning['field_completeness'] = {
            'enabled': True,
            'required_fields': field_cfg.get('required_fields', ['user_id', 'product_id', 'review_text', 'timestamp'])
        }

    # 异常值过滤
    if config.is_enabled('cleaning.outlier'):
        outlier_cfg = config.get_section('cleaning.outlier')
        cleaning['outlier'] = {
            'enabled': True,
            'min_rating': args.min_rating if hasattr(args, 'min_rating') and args.min_rating else outlier_cfg.get(
                'min_rating', 1.0),
            'max_rating': args.max_rating if hasattr(args, 'max_rating') and args.max_rating else outlier_cfg.get(
                'max_rating', 5.0),
            'min_year': outlier_cfg.get('min_year', 1990)
        }

    # 数据质量过滤
    if config.is_enabled('cleaning.quality'):
        quality_cfg = config.get_section('cleaning.quality')
        cleaning['quality'] = {
            'enabled': True,
            'min_text_length': args.min_length or quality_cfg.get('min_text_length', 10)
        }

    # 垃圾数据过滤
    if config.is_enabled('cleaning.spam'):
        spam_cfg = config.get_section('cleaning.spam')
        cleaning['spam'] = {
            'enabled': True,
            'custom_patterns': spam_cfg.get('custom_patterns', [])
        }

    # 时间过滤
    if config.is_enabled('cleaning.time'):
        time_cfg = config.get_section('cleaning.time')
        cleaning['time'] = {
            'enabled': True,
            'years': args.years or time_cfg.get('years', 10)
        }

    # 文本长度过滤
    if config.is_enabled('cleaning.text_length'):
        text_cfg = config.get_section('cleaning.text_length')
        cleaning['text_length'] = {
            'enabled': True,
            'max_length': args.max_length or text_cfg.get('max_length', 700)
        }

    # 去重
    if config.is_enabled('cleaning.deduplicate'):
        dedup_cfg = config.get_section('cleaning.deduplicate')
        cleaning['deduplicate'] = {
            'enabled': True,
            'key_column': dedup_cfg.get('key_column', 'review_text')
        }

    # 突发评论过滤
    if config.is_enabled('cleaning.burst_review'):
        burst_cfg = config.get_section('cleaning.burst_review')
        cleaning['burst_review'] = {
            'enabled': True,
            'time_window_minutes': burst_cfg.get('time_window_minutes', 10),
            'max_reviews': burst_cfg.get('max_reviews', 50)
        }

    # K-core过滤
    if config.is_enabled('cleaning.kcore'):
        kcore_cfg = config.get_section('cleaning.kcore')
        spark_cfg = config.get_section('spark')
        cleaning['kcore'] = {
            'enabled': True,
            'k': args.k_core or kcore_cfg.get('k', 5),
            'checkpoint_dir': spark_cfg.get('checkpoint_dir', None)
        }

    result['cleaning'] = cleaning

    # 输出配置
    result['output_format'] = args.format or config.get('output.format', 'json')

    # Spark配置
    spark_cfg = config.get_section('spark')
    result['spark'] = {
        'master': args.master or spark_cfg.get('master', 'local[*]'),
        'memory': args.driver_memory or spark_cfg.get('memory', '4g'),
        'driver_cores': args.driver_cores or spark_cfg.get('driver_cores', 2),
        'executor_cores': args.executor_cores or spark_cfg.get('executor_cores', 2),
        'executor_memory': args.executor_memory or spark_cfg.get('executor_memory', '4g'),
        'executor_numbers': args.executor_numbers or spark_cfg.get('executor_numbers', 1),
        'partitions': args.partitions or spark_cfg.get('partitions', 8),
        'local_dir': spark_cfg.get('local_dir', '/tmp/spark-tmp'),
        'checkpoint_dir': spark_cfg.get('checkpoint_dir', None)
    }

    return result
