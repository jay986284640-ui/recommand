"""数据源适配器抽象基类"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from pyspark.sql import DataFrame, SparkSession


class BaseDataSource(ABC):
    """
    数据源适配器抽象基类

    所有数据集适配器必须继承此类并实现抽象方法。
    适配器负责将异构的原始数据转换为框架定义的标准中间格式。
    """

    def __init__(self, spark: SparkSession, config: dict):
        """
        初始化适配器

        Args:
            spark: SparkSession 实例
            config: 配置字典，包含输入路径等信息
        """
        self.spark = spark
        self.config = config
        self._users_df: Optional[DataFrame] = None
        self._items_df: Optional[DataFrame] = None
        self._interactions_df: Optional[DataFrame] = None
        self._co_occurrence_df: Optional[DataFrame] = None

    def validate_config(self) -> None:
        """
        验证配置完整性，由子类实现具体验证逻辑

        Raises:
            ValueError: 当必填配置缺失时抛出
        """
        # 子类可以重写此方法进行验证
        # 默认不做任何验证
        pass

    @abstractmethod
    def load_users(self) -> DataFrame:
        """
        读取并转换用户数据

        Returns:
            DataFrame，必须包含以下列:
            - user_id (String): 用户ID，必填
            - 其他可选的动态扩展列
        """
        pass

    @abstractmethod
    def load_items(self) -> DataFrame:
        """
        读取并转换物品数据

        Returns:
            DataFrame，必须包含以下列:
            - item_id (String): 物品ID，必填
            - item_title (String, optional): 物品标题
            - item_description (String, optional): 物品描述
            - 其他可选的动态扩展列
        """
        pass

    @abstractmethod
    def load_interactions(self) -> DataFrame:
        """
        读取并转换交互数据

        Returns:
            DataFrame，必须包含以下列:
            - user_id (String): 用户ID，必填
            - item_id (String): 物品ID，必填
            - timestamp (Long): 时间戳（Unix timestamp），必填
            - action (String): 行为类型 (如 like/dislike)，必填
            - 其他可选的动态扩展列
        """
        pass

    def load_co_occurrence(self) -> Optional[DataFrame]:
        """
        读取并转换共现数据

        Returns:
            DataFrame，可选，包含以下列:
            - item_id (String): 物品ID，必填
            - related_items (Array[String]): 共现物品列表，必填

            如果数据集没有共现数据，返回 None
        """
        return None

    def get_users(self) -> DataFrame:
        """获取用户数据（带缓存）"""
        if self._users_df is None:
            self._users_df = self.load_users()
        return self._users_df

    def get_items(self) -> DataFrame:
        """获取物品数据（带缓存）"""
        if self._items_df is None:
            self._items_df = self.load_items()
        return self._items_df

    def get_interactions(self) -> DataFrame:
        """获取交互数据（带缓存）"""
        if self._interactions_df is None:
            self._interactions_df = self.load_interactions()
        return self._interactions_df

    def get_co_occurrence(self) -> Optional[DataFrame]:
        """获取共现数据（带缓存）"""
        if self._co_occurrence_df is None:
            self._co_occurrence_df = self.load_co_occurrence()
        return self._co_occurrence_df

    def get_schema_info(self) -> dict:
        """获取数据源的模式信息，用于调试和日志"""
        info = {}
        try:
            info['users'] = [f.name for f in self.get_users().schema.fields]
        except Exception:
            info['users'] = None

        try:
            info['items'] = [f.name for f in self.get_items().schema.fields]
        except Exception:
            info['items'] = None

        try:
            info['interactions'] = [f.name for f in self.get_interactions().schema.fields]
        except Exception:
            info['interactions'] = None

        try:
            co_occurrence = self.get_co_occurrence()
            info['co_occurrence'] = [f.name for f in co_occurrence.schema.fields] if co_occurrence is not None else None
        except Exception:
            info['co_occurrence'] = None

        return info