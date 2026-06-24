"""统一配置加载

覆盖 4 步管线(稽核 / 清洗 / 标准化 / 特征提取) + 适配器 + Spark 的全部配置。
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml


logger = logging.getLogger(__name__)


@dataclass
class SparkConfig:
    """Spark 配置"""
    master: str = "local[*]"
    memory: str = "4g"
    driver_cores: int = 2
    executor_cores: int = 2
    executor_memory: str = "4g"
    executor_numbers: int = 1
    partitions: int = 8
    local_dir: str = "/tmp/spark-tmp"
    checkpoint_dir: str = None


@dataclass
class DataSourceConfig:
    """数据源配置"""
    adapter: str = "amazon"
    # 适配器专用配置字典,避免每新增适配器都要修改此处
    adapter_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditConfig:
    """数据质量稽核配置(步骤 1)"""
    enabled: bool = True
    output_dir: str = "./audit_report"
    # 报告输出的指标(全部默认开启)
    metrics_row_count: bool = True
    metrics_field_completeness: bool = True
    metrics_primary_key_uniqueness: bool = True
    metrics_time_range: bool = True
    metrics_outlier_check: bool = True
    # 数值列异常范围(用于异常值稽核)
    outlier_rules: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class CleaningConfig:
    """数据清洗配置(步骤 2)"""
    # 字段完整性
    field_completeness: bool = True
    required_fields: List[str] = field(
        default_factory=lambda: ["user_id", "item_id", "timestamp"]
    )
    # 商品存在性
    product_exists: bool = True
    # 时间过滤
    time: bool = True
    years: int = 18
    # 去重
    deduplicate: bool = True
    dedup_column: str = None
    # 突发评论
    burst_review: bool = True
    burst_window_minutes: int = 10
    burst_max_reviews: int = 50
    # 用户-物品连续去重
    user_item_dedup: bool = True
    # K-core
    kcore: bool = True
    kcore_k: int = 5
    kcore_checkpoint_dir: str = None
    # 异常值
    outlier: bool = True
    min_rating: float = 1.0
    max_rating: float = 5.0
    min_year: int = 1990
    # 垃圾数据
    spam: bool = True
    # 文本长度
    text_length: bool = True
    min_text_length: int = 10
    # 声明式规则
    interaction_rules: List[Dict[str, Any]] = field(default_factory=list)
    interaction_rules_logic: str = "AND"
    user_rules: List[Dict[str, Any]] = field(default_factory=list)
    user_rules_logic: str = "AND"
    item_rules: List[Dict[str, Any]] = field(default_factory=list)
    item_rules_logic: str = "AND"


@dataclass
class NormalizationConfig:
    """文本标准化配置(步骤 3)"""
    enabled: bool = True
    # {DataFrame 名称: [{normalizer, columns}, ...]}
    df_config: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)


@dataclass
class FeatureExtractionConfig:
    """特征提取配置(步骤 4)"""
    enabled: bool = True
    output_dir: str = "./features"
    output_format: str = "parquet"

    # 5 类特征开关
    item_features: bool = True
    user_features: bool = True
    user_interaction_history: bool = True
    co_purchase: bool = True
    impression_log: bool = False  # 默认关闭,待 LP 主流程回流曝光日志后开启

    # 序列最大长度(超过截断)
    max_seq_length: int = 200
    # 共购统计窗口(天)
    co_purchase_window_days: int = 30
    # 冷启动/新用户阈值(交互数 < N 视为新用户)
    new_user_threshold: int = 3


@dataclass
class OutputConfig:
    """输出配置"""
    dir: str = "./output"
    format: str = "parquet"
    save_intermediate: bool = False


@dataclass
class Config:
    """统一配置类"""
    data: DataSourceConfig = field(default_factory=DataSourceConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    cleaning: CleaningConfig = field(default_factory=CleaningConfig)
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    feature_extraction: FeatureExtractionConfig = field(default_factory=FeatureExtractionConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    spark: SparkConfig = field(default_factory=SparkConfig)

    @classmethod
    def from_yaml(cls, config_path: str) -> "Config":
        with open(config_path, 'r', encoding='utf-8') as f:
            config_dict = yaml.safe_load(f)
        return cls.from_dict(config_dict)

    @classmethod
    def from_dict(cls, config_dict: dict) -> "Config":
        return cls(
            data=DataSourceConfig(**config_dict.get('data', {})),
            audit=AuditConfig(**config_dict.get('audit', {})),
            cleaning=CleaningConfig(**config_dict.get('cleaning', {})),
            normalization=NormalizationConfig(**config_dict.get('normalization', {})),
            feature_extraction=FeatureExtractionConfig(**config_dict.get('feature_extraction', {})),
            output=OutputConfig(**config_dict.get('output', {})),
            spark=SparkConfig(**config_dict.get('spark', {})),
        )


def load_config(config_path: str) -> Config:
    """加载 YAML 配置文件"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    return Config.from_yaml(config_path)
