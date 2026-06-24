"""清洗流程管理器"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from typing import List, Dict, Any

from pyspark.sql import DataFrame

from filters import (
    BaseFilter,
    FieldCompletenessFilter,
    OutlierFilter,
    QualityFilter,
    SpamFilter,
    TimeFilter,
    TextLengthFilter,
    DeduplicateFilter,
    KCoreFilter,
)


class CleaningPipeline:
    """数据清洗流程管理器"""

    def __init__(self):
        self.filters: List[BaseFilter] = []
        self.stats: List[Dict[str, Any]] = []  # 存储每个步骤的统计信息

    def add_filter(self, filter_obj: BaseFilter):
        """添加过滤器到流程中"""
        self.filters.append(filter_obj)
        return self

    def build_default_pipeline(self, min_text_length: int = 10, max_text_length: int = 700,
                               years: int = 10, k: int = 5) -> "CleaningPipeline":
        """构建默认的清洗流程"""
        self.filters = [
            FieldCompletenessFilter(),
            OutlierFilter(),
            QualityFilter(min_text_length=min_text_length),
            SpamFilter(),
            TimeFilter(years=years),
            TextLengthFilter(max_length=max_text_length),
            DeduplicateFilter(),
            KCoreFilter(k=k),
        ]
        return self

    def run(self, df: DataFrame) -> DataFrame:
        """执行清洗流程"""
        result = df
        self.stats = []  # 重置统计信息

        for i, filter_obj in enumerate(self.filters, 1):
            before_count = result.count()
            print(f"\n{'=' * 60}")
            print(f"步骤{i}: {filter_obj.name}")
            print("=" * 60)
            print(f"   过滤前记录数: {before_count:,}")

            result = filter_obj.filter(result)

            after_count = result.count()
            removed_count = before_count - after_count

            # 记录统计信息
            self.stats.append({
                "step": i,
                "filter_name": filter_obj.name,
                "before_count": before_count,
                "after_count": after_count,
                "removed_count": removed_count,
                "removed_rate": (removed_count / before_count * 100) if before_count > 0 else 0
            })

            print(f"   过滤后记录数: {after_count:,}")
            print(
                f"   移除记录: {removed_count:,} ({removed_count / before_count * 100:.2f}%)" if before_count > 0 else "")

        return result

    def get_stats(self) -> List[Dict[str, Any]]:
        """获取清洗流程的统计信息"""
        return self.stats

    def get_filter_names(self) -> List[str]:
        """获取所有过滤器的名称"""
        return [f.name for f in self.filters]
