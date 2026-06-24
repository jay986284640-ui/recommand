"""数据清洗(步骤 2)

合并自旧版 processing/filters/ + data_cleaning/filters/,以 processing/filters 为骨架,
补充 OutlierFilter / SpamFilter / TextLengthFilter。BaseFilter 沿用 processing 版本
(支持 enabled 标志 + FilterOperator 注册表)。
"""

from .base_filter import BaseFilter, FilterOperator, register_operator, get_operator
from .field_completeness_filter import FieldCompletenessFilter
from .time_filter import TimeFilter
from .kcore_filter import KCoreFilter
from .deduplicate_filter import DeduplicateFilter
from .burst_review_filter import BurstReviewFilter
from .user_item_dedup_filter import UserItemDeduplicateFilter
from .quality_filter import QualityFilter
from .product_exists_filter import ProductExistsFilter
from .rule_filter import RuleBasedFilter, DynamicFilter
from .outlier_filter import OutlierFilter
from .spam_filter import SpamFilter
from .text_length_filter import TextLengthFilter
from .pipeline import CleaningPipeline

__all__ = [
    "BaseFilter",
    "FilterOperator",
    "register_operator",
    "get_operator",
    "FieldCompletenessFilter",
    "TimeFilter",
    "KCoreFilter",
    "DeduplicateFilter",
    "BurstReviewFilter",
    "UserItemDeduplicateFilter",
    "QualityFilter",
    "ProductExistsFilter",
    "RuleBasedFilter",
    "DynamicFilter",
    "OutlierFilter",
    "SpamFilter",
    "TextLengthFilter",
    "CleaningPipeline",
]
