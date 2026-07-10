"""数据源适配器模块

提供统一的适配器接口来处理不同格式的原始数据集。

使用方式:
    from adapters import AdapterFactory

    # 从配置文件加载
    adapter = AdapterFactory.create("amazon", spark, config)

    # 获取标准格式的数据
    users = adapter.get_users()
    items = adapter.get_items()
    interactions = adapter.get_interactions()
"""

__all__ = [
    "BaseDataSource",
    "AdapterFactory",
    "register_adapter",
]

from .base import BaseDataSource
from .factory import AdapterFactory, register_adapter

# 导入内置适配器
from . import netflix
from . import kuairand
from . import amazon23
from . import amazon
from . import xingye_coupon
from . import xingye_coupon_csv