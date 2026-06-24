"""清洗步骤 Pipeline

按配置依次应用过滤器;对 user / item / interaction 三类数据分别清洗;
最后做级联过滤保证 user_id / item_id 在交互记录中真实存在。
"""

import logging
from typing import List, Optional, Dict, Any, Tuple
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base_filter import BaseFilter
from .field_completeness_filter import FieldCompletenessFilter
from .time_filter import TimeFilter
from .kcore_filter import KCoreFilter
from .deduplicate_filter import DeduplicateFilter
from .burst_review_filter import BurstReviewFilter
from .user_item_dedup_filter import UserItemDeduplicateFilter
from .quality_filter import QualityFilter
from .product_exists_filter import ProductExistsFilter
from .rule_filter import RuleBasedFilter
from .outlier_filter import OutlierFilter
from .spam_filter import SpamFilter
from .text_length_filter import TextLengthFilter


logger = logging.getLogger(__name__)


class CleaningPipeline:
    """数据清洗步骤 Pipeline"""

    def __init__(self, config):
        self.config = config
        self.stats: List[Dict[str, Any]] = []

    def _build_interaction_filters(self) -> List[BaseFilter]:
        cfg = self.config.cleaning
        filters: List[BaseFilter] = []
        if cfg.field_completeness:
            filters.append(FieldCompletenessFilter(required_fields=cfg.required_fields))
        if cfg.outlier:
            filters.append(OutlierFilter(
                min_rating=cfg.min_rating, max_rating=cfg.max_rating, min_year=cfg.min_year
            ))
        if cfg.time:
            filters.append(TimeFilter(years=cfg.years))
        if cfg.interaction_rules:
            filters.append(RuleBasedFilter(
                rules=cfg.interaction_rules, logic=cfg.interaction_rules_logic
            ))
        if cfg.deduplicate:
            filters.append(DeduplicateFilter(key_column=cfg.dedup_column))
        if cfg.burst_review:
            filters.append(BurstReviewFilter(
                time_window_minutes=cfg.burst_window_minutes, max_reviews=cfg.burst_max_reviews
            ))
        if cfg.user_item_dedup:
            filters.append(UserItemDeduplicateFilter())
        if cfg.text_length:
            filters.append(TextLengthFilter(min_length=cfg.min_text_length))
        if cfg.spam:
            filters.append(SpamFilter())
        if cfg.quality if hasattr(cfg, "quality") else False:  # 兼容旧字段
            filters.append(QualityFilter(min_text_length=cfg.min_text_length))
        if cfg.kcore:
            filters.append(KCoreFilter(k=cfg.kcore_k, checkpoint_dir=cfg.kcore_checkpoint_dir))
        return filters

    def _build_user_filters(self) -> List[BaseFilter]:
        cfg = self.config.cleaning
        filters: List[BaseFilter] = []
        if cfg.user_rules:
            filters.append(RuleBasedFilter(rules=cfg.user_rules, logic=cfg.user_rules_logic))
        return filters

    def _build_item_filters(self, items_df: DataFrame) -> List[BaseFilter]:
        cfg = self.config.cleaning
        filters: List[BaseFilter] = []
        if cfg.product_exists and items_df is not None:
            filters.append(ProductExistsFilter(items_df=items_df))
        if cfg.item_rules:
            filters.append(RuleBasedFilter(rules=cfg.item_rules, logic=cfg.item_rules_logic))
        return filters

    def _run_filters(self, df: DataFrame, filters: List[BaseFilter], step_name: str) -> DataFrame:
        result = df
        before = result.count()
        for i, f in enumerate(filters, 1):
            if not f.enabled:
                continue
            logger.info("[%s] 步骤 %d: %s (前: %d)", step_name, i, f.name, before)
            result = f.filter(result)
            after = result.count()
            removed = before - after
            logger.info("[%s] 步骤 %d: %s (后: %d, 移除: %d)", step_name, i, f.name, after, removed)
            self.stats.append({"step": step_name, "filter": f.name, "before": before, "after": after, "removed": removed})
            before = after
        return result

    def _cascade_filter(self, users: DataFrame, items: DataFrame, interactions: DataFrame) -> Tuple[DataFrame, DataFrame, DataFrame]:
        """级联过滤,保证 user/item ID 在交互记录中真实存在"""
        valid_user_ids = interactions.select("user_id").distinct()
        valid_item_ids = interactions.select("item_id").distinct()
        return (
            users.join(valid_user_ids, "user_id", "inner"),
            items.join(valid_item_ids, "item_id", "inner"),
            interactions,
        )

    def run(self, users_df: DataFrame, items_df: DataFrame, interactions_df: DataFrame) -> Dict[str, DataFrame]:
        logger.info("====== 开始清洗步骤 ======")
        # 1) 交互数据清洗
        interaction_filters = self._build_interaction_filters()
        cleaned_interactions = self._run_filters(interactions_df, interaction_filters, "interaction")

        # 2) 物品数据清洗(商品存在性依赖交互表)
        item_filters = self._build_item_filters(items_df)
        # 注意:商品存在性过滤是反向的(交互表需要 item 存在),所以单独用 left_semi join
        cleaned_items = items_df
        for f in item_filters:
            if isinstance(f, ProductExistsFilter):
                # 商品存在性不在 items 上跑,而是在 interactions 上 join
                continue
            cleaned_items = self._run_filters(cleaned_items, [f], "item")

        # 3) 用户数据清洗
        user_filters = self._build_user_filters()
        cleaned_users = self._run_filters(users_df, user_filters, "user")

        # 4) 商品存在性过滤
        if self.config.cleaning.product_exists and items_df is not None:
            cleaned_interactions = ProductExistsFilter(items_df=items_df).filter(cleaned_interactions)

        # 5) 级联过滤
        final_users, final_items, final_interactions = self._cascade_filter(
            cleaned_users, cleaned_items, cleaned_interactions
        )
        return {
            "users": final_users,
            "items": final_items,
            "interactions": final_interactions,
        }
