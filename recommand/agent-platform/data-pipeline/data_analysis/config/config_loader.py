#!/usr/bin/env python3
"""
配置加载器 - 读取 YAML 配置文件
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


class Config:
    """配置管理类"""

    _instance: Optional['Config'] = None
    _config: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._config:
            self._load_default_config()

    def _load_default_config(self):
        """加载默认配置"""
        config_path = Path(__file__).parent.parent / "config.yaml"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f)
        else:
            self._config = self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            'spark': {
                'mode': 'local',
                'master': 'spark://master:7077',
                'app_name': 'Amazon_Analysis',
                'driver_memory': '4g',
                'executor_instances': 2,
                'executor_memory': '2g',
                'shuffle_partitions': 8
            },
            'data': {
                'review_file': '/opt/recommand/data/All_Beauty_sample_1000.jsonl',
                'meta_file': '/opt/recommand/data/meta_All_Beauty_sample_1000.jsonl',
                'output_dir': '/opt/recommand/output'
            },
            'analysis': {
                'basic_analysis': [
                    'user_review_count',
                    'product_review_count',
                    'product_rating_stats',
                    'rating_by_time',
                    'rating_distribution',
                    'review_length_stats',
                    'title_length_stats',
                    'null_statistics'
                ],
                'deep_analysis': [
                    'verified_purchase_comparison',
                    'first_vs_subsequent_review',
                    'weekday_rating',
                    'length_by_rating',
                    'rating_polarization',
                    'product_review_tail',
                    'user_rating_trend',
                    'helpful_vote_analysis',
                    'popularity_comparison',
                    'monthly_rating_distribution'
                ]
            },
            'visualization': {
                'enabled': True,
                'dpi': 150,
                'style': 'seaborn-v0_8-whitegrid',
                'colors': ['#e74c3c', '#e67e22', '#f1c40f', '#2ecc71', '#3498db']
            },
            'logging': {
                'level': 'WARN',
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            }
        }

    def load_from_file(self, config_path: str) -> None:
        """从文件加载配置"""
        with open(config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点号分隔的路径"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    def get_spark_config(self) -> Dict[str, Any]:
        """获取 Spark 配置"""
        return self._config.get('spark', {})

    def get_data_config(self) -> Dict[str, Any]:
        """获取数据配置"""
        return self._config.get('data', {})

    def get_source_config(self) -> Dict[str, Any]:
        """获取数据源配置"""
        return self._config.get('source_config', {})

    def get_source_type(self) -> str:
        """获取数据源类型"""
        return self._config.get('data.source_type', 'amazon_new')

    def get_analysis_config(self) -> Dict[str, Any]:
        """获取分析配置"""
        return self._config.get('analysis', {})

    def get_visualization_config(self) -> Dict[str, Any]:
        """获取可视化配置"""
        return self._config.get('visualization', {})

    def get_logging_config(self) -> Dict[str, Any]:
        """获取日志配置"""
        return self._config.get('logging', {})

    @property
    def is_cluster_mode(self) -> bool:
        """是否集群模式"""
        return self.get('spark.mode') == 'cluster'

    @property
    def is_local_mode(self) -> bool:
        """是否本地模式"""
        return self.get('spark.mode') == 'local'


# 全局配置实例
config = Config()