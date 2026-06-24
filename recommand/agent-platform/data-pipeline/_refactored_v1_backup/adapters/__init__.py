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

本项目特有的适配器(对齐 LP Agent content_type):
- meituan_coupon: 美团门店券
- self_operated_coupon: 自拓展门店券
- local_payment: 本地优惠买单
- external_coupon: 外部券
- amazon_old / amazon_new / netflix / kuairand: 公开数据集,用于离线实验
"""

__all__ = [
    "BaseDataSource",
    "AdapterFactory",
    "register_adapter",
]

from .base import BaseDataSource
from .factory import AdapterFactory, register_adapter

# 公开数据集适配器
from . import netflix  # noqa: F401
from . import kuairand  # noqa: F401
from . import amazon23  # noqa: F401
from . import amazon  # noqa: F401

# LP 项目业务适配器
from . import meituan_coupon  # noqa: F401
from . import self_operated_coupon  # noqa: F401
from . import local_payment  # noqa: F401
from . import external_coupon  # noqa: F401
