"""过滤器抽象基类 + 声明式算子注册"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pyspark.sql import DataFrame


logger = logging.getLogger(__name__)


class BaseFilter(ABC):
    """数据过滤器抽象基类"""

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled

    @abstractmethod
    def filter(self, df: DataFrame) -> DataFrame:
        pass

    def get_config(self) -> Dict[str, Any]:
        return {"name": self.name, "enabled": self.enabled}


class FilterOperator(ABC):
    """过滤算子抽象基类(声明式规则引擎用)"""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def build_condition(self, df: DataFrame, params: dict):
        pass


# 算子注册表
_OPERATOR_REGISTRY: Dict[str, FilterOperator] = {}


def register_operator(name: str):
    def decorator(cls):
        _OPERATOR_REGISTRY[name] = cls()
        return cls
    return decorator


def get_operator(name: str) -> Optional[FilterOperator]:
    return _OPERATOR_REGISTRY.get(name)
