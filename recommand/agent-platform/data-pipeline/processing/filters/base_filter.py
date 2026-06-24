"""处理模块过滤器基类"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pyspark.sql import DataFrame


logger = logging.getLogger(__name__)


class BaseFilter(ABC):
    """数据过滤器的抽象基类"""

    def __init__(self, name: str, enabled: bool = True):
        """
        初始化过滤器

        Args:
            name: 过滤器名称
            enabled: 是否启用该过滤器
        """
        self.name = name
        self.enabled = enabled

    @abstractmethod
    def filter(self, df: DataFrame) -> DataFrame:
        """
        执行过滤操作，子类必须实现

        Args:
            df: 输入的 DataFrame

        Returns:
            过滤后的 DataFrame
        """
        pass

    def _log_step(self, df: DataFrame, step_num: int) -> DataFrame:
        """记录步骤并打印日志"""
        if not self.enabled:
            return df

        before_count = df.count()
        logger.info("步骤 %d: %s (过滤前: %d)", step_num, self.name, before_count)

        result = self.filter(df)

        after_count = result.count()
        removed_count = before_count - after_count

        logger.info("步骤 %d: %s (过滤后: %d, 移除: %d, %.2f%%)",
                    step_num, self.name, after_count, removed_count,
                    removed_count/before_count*100 if before_count > 0 else 0)

        return result

    def get_config(self) -> Dict[str, Any]:
        """获取过滤器配置信息"""
        return {
            "name": self.name,
            "enabled": self.enabled
        }


class FilterOperator(ABC):
    """
    过滤算子抽象基类

    用于声明式规则引擎的算子实现
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def build_condition(self, df: DataFrame, params: dict) -> "pyspark.sql.Column":
        """
        构建过滤条件

        Args:
            df: 输入的 DataFrame
            params: 算子参数

        Returns:
            Spark Column 条件
        """
        pass


# 算子注册表
_OPERATOR_REGISTRY: Dict[str, FilterOperator] = {}


def register_operator(name: str):
    """
    算子注册装饰器

    使用方式:
        @register_operator("range_check")
        class RangeCheckOperator(FilterOperator):
            ...
    """
    def decorator(cls: type) -> type:
        _OPERATOR_REGISTRY[name] = cls()
        return cls
    return decorator


def get_operator(name: str) -> Optional[FilterOperator]:
    """获取注册的算子"""
    return _OPERATOR_REGISTRY.get(name)