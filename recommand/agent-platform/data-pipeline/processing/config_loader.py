"""配置加载模块"""

import logging
import os
import yaml
from typing import Any, Dict, Optional, List, Union
from dataclasses import dataclass, field


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
    # 适配器专用配置（使用字典存储，避免每次新增适配器都要修改此处）
    # 适配器通过 self.config.get("xxx") 获取
    adapter_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CleaningConfig:
    """清洗配置"""
    # 字段完整性
    field_completeness: bool = True
    required_fields: list = field(default_factory=lambda: ["user_id", "item_id", "timestamp"])

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

    # 通用规则过滤 - 交互数据
    interaction_rules: list = field(default_factory=list)
    interaction_rules_logic: str = "AND"  # AND 或 OR

    # 通用规则过滤 - 用户数据
    user_rules: list = field(default_factory=list)
    user_rules_logic: str = "AND"

    # 通用规则过滤 - 物品数据
    item_rules: list = field(default_factory=list)
    item_rules_logic: str = "AND"

    # 多个规则组（更灵活的配置）
    rule_groups: list = field(default_factory=list)


@dataclass
class NormalizationConfig:
    """文本标准化配置"""
    enabled: bool = True

    # 每个表的独立配置
    # 格式：{DataFrame名称: [{normalizer: "xxx", columns: [...]}]}
    # DataFrame 名称: users, items, interactions
    # normalizer: lowercase, html_normalizer, special_char_normalizer, unicode_normalizer, whitespace_normalizer, regex_replace_normalizer, regex_extract_normalizer
    df_config: dict = field(default_factory=dict)


@dataclass
class OutputConfig:
    """输出配置"""
    dir: str = "./output"
    format: str = "json"
    save_intermediate: bool = False  # 是否保存中间格式（Adapter 输出）


@dataclass
class Config:
    """统一配置类"""
    data: DataSourceConfig = field(default_factory=DataSourceConfig)
    cleaning: CleaningConfig = field(default_factory=CleaningConfig)
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    spark: SparkConfig = field(default_factory=SparkConfig)

    @classmethod
    def from_yaml(cls, config_path: str) -> "Config":
        """从 YAML 文件加载配置"""
        with open(config_path, 'r', encoding='utf-8') as f:
            config_dict = yaml.safe_load(f)

        return cls.from_dict(config_dict)

    @classmethod
    def from_dict(cls, config_dict: dict) -> "Config":
        """从字典加载配置"""
        data_cfg = config_dict.get('data', {})
        cleaning_cfg = config_dict.get('cleaning', {})
        norm_cfg = config_dict.get('normalization', {})
        output_cfg = config_dict.get('output', {})
        spark_cfg = config_dict.get('spark', {})

        return cls(
            data=DataSourceConfig(**{k: v for k, v in data_cfg.items()}),
            cleaning=CleaningConfig(**{k: v for k, v in cleaning_cfg.items()}),
            normalization=NormalizationConfig(**{k: v for k, v in norm_cfg.items()}),
            output=OutputConfig(**{k: v for k, v in output_cfg.items()}),
            spark=SparkConfig(**{k: v for k, v in spark_cfg.items()})
        )


def load_config(config_path: str) -> Config:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径

    Returns:
        Config 对象
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    return Config.from_yaml(config_path)


if __name__ == "__main__":
    config = CleaningConfig(kcore=False)
    logger.info("测试配置: %s", config)