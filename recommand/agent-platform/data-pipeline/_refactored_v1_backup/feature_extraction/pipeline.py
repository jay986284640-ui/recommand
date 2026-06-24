"""特征提取 Pipeline

按配置开关,选择性地写出 5 类特征 parquet。
"""

import logging
import os
from typing import Dict
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .item_features import extract_item_features
from .user_features import extract_user_features
from .user_interaction_history import build_user_interaction_history
from .co_purchase import build_co_purchase
from .impression_log import build_impression_log_stub


logger = logging.getLogger(__name__)


class FeatureExtractionPipeline:
    """特征提取 Pipeline(步骤 4)"""

    def __init__(self, config, spark):
        self.config = config
        self.spark = spark
        os.makedirs(config.feature_extraction.output_dir, exist_ok=True)

    def _write(self, df: DataFrame, name: str) -> str:
        if df is None:
            logger.info("跳过写出 %s (df is None)", name)
            return None
        path = os.path.join(
            self.config.feature_extraction.output_dir,
            f"{name}.{self.config.feature_extraction.output_format}",
        )
        mode = "overwrite"
        fmt = self.config.feature_extraction.output_format
        if fmt == "parquet":
            df.write.mode(mode).parquet(path)
        elif fmt == "json":
            df.write.mode(mode).json(path)
        elif fmt == "csv":
            df.write.mode(mode).csv(path, header=True)
        else:
            raise ValueError(f"不支持的输出格式: {fmt}")
        logger.info("已写出: %s", path)
        return path

    def run(
        self,
        users_df: DataFrame,
        items_df: DataFrame,
        interactions_df: DataFrame,
    ) -> Dict[str, str]:
        if not self.config.feature_extraction.enabled:
            logger.info("特征提取步骤被禁用,跳过")
            return {}

        logger.info("====== 开始特征提取步骤 ======")
        cfg = self.config.feature_extraction
        outputs: Dict[str, str] = {}

        if cfg.item_features:
            outputs["item_features"] = self._write(
                extract_item_features(items_df, interactions_df),
                "item_features",
            )
        if cfg.user_features:
            outputs["user_features"] = self._write(
                extract_user_features(users_df, interactions_df, items_df, new_user_threshold=cfg.new_user_threshold),
                "user_features",
            )
        if cfg.user_interaction_history:
            outputs["user_interaction_history"] = self._write(
                build_user_interaction_history(interactions_df, max_seq_length=cfg.max_seq_length),
                "user_interaction_history",
            )
        if cfg.co_purchase:
            outputs["co_purchase"] = self._write(
                build_co_purchase(interactions_df, window_days=cfg.co_purchase_window_days),
                "co_purchase",
            )
        if cfg.impression_log:
            outputs["impression_log"] = self._write(
                build_impression_log_stub(self.spark),
                "impression_log",
            )

        return outputs
