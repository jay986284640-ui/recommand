"""适配器工厂模块"""

from typing import Dict, Type, Optional
from pyspark.sql import SparkSession
from .base import BaseDataSource


# 适配器注册表
_ADAPTER_REGISTRY: Dict[str, Type[BaseDataSource]] = {}


def register_adapter(adapter_name: str):
    """
    适配器注册装饰器

    使用方式:
        @register_adapter("amazon")
        class AmazonAdapter(BaseDataSource):
            ...

    Args:
        adapter_name: 适配器名称，用于配置文件中指定
    """
    def decorator(cls: Type[BaseDataSource]) -> Type[BaseDataSource]:
        _ADAPTER_REGISTRY[adapter_name.lower()] = cls
        return cls
    return decorator


class AdapterFactory:
    """适配器工厂类"""

    _registry: Dict[str, Type[BaseDataSource]] = {}

    @classmethod
    def register(cls, adapter_name: str, adapter_class: Type[BaseDataSource]):
        """
        注册适配器

        Args:
            adapter_name: 适配器名称
            adapter_class: 适配器类
        """
        cls._registry[adapter_name.lower()] = adapter_class

    @classmethod
    def create(cls, adapter_name: str, spark: SparkSession, config: dict) -> BaseDataSource:
        """
        创建适配器实例

        Args:
            adapter_name: 适配器名称（在配置中指定）
            spark: SparkSession 实例
            config: 配置字典

        Returns:
            适配器实例

        Raises:
            ValueError: 当适配器名称不存在时抛出
        """
        adapter_name_lower = adapter_name.lower()

        # 优先从类注册表查找
        if adapter_name_lower in cls._registry:
            adapter_class = cls._registry[adapter_name_lower]
            return adapter_class(spark, config)

        # 从全局注册表查找
        if adapter_name_lower in _ADAPTER_REGISTRY:
            adapter_class = _ADAPTER_REGISTRY[adapter_name_lower]
            return adapter_class(spark, config)

        available = list(cls._registry.keys()) + list(_ADAPTER_REGISTRY.keys())
        raise ValueError(
            f"未找到适配器 '{adapter_name}'. "
            f"可用的适配器: {available}. "
            f"请确保已正确注册适配器."
        )

    @classmethod
    def list_adapters(cls) -> list:
        """列出所有已注册的适配器"""
        return list(set(cls._registry.keys()) | set(_ADAPTER_REGISTRY.keys()))
