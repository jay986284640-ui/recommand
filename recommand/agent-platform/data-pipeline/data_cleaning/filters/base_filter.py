"""过滤器基类"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from abc import ABC, abstractmethod

from pyspark.sql import DataFrame


class BaseFilter(ABC):
    """数据过滤器的抽象基类"""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def filter(self, df: DataFrame) -> DataFrame:
        """执行过滤操作，子类必须实现"""
        pass

    def _print_step(self, step_num: int, before_count: int, after_count: int):
        """打印过滤步骤的统计信息"""
        removed_count = before_count - after_count
        print(f"   过滤后记录数: {after_count:,}")
        print(f"   移除记录: {removed_count:,} ({removed_count / before_count * 100:.2f}%)" if before_count > 0 else "")

    def _log_step(self, df: DataFrame, step_num: int) -> DataFrame:
        """记录步骤并打印日志"""
        before_count = df.count()
        print(f"\n{'=' * 60}")
        print(f"步骤{step_num}: {self.name}")
        print("=" * 60)
        print(f"   过滤前记录数: {before_count:,}")

        result = self.filter(df)

        after_count = result.count()
        self._print_step(step_num, before_count, after_count)
        return result
