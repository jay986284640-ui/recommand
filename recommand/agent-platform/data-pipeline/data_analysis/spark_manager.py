#!/usr/bin/env python3
"""
Spark 会话管理器 - 支持本地和集群模式
"""

import os
import time
import random
from typing import Dict, Any, Optional
from pyspark.sql import SparkSession


class SparkManager:
    """Spark 会话管理器"""

    def __init__(self):
        """初始化管理器"""
        self._spark: Optional[SparkSession] = None

    def _create_spark_session(self, config: Dict[str, Any]) -> SparkSession:
        """创建 SparkSession"""
        # 获取配置
        mode = config.get('mode', 'local')
        app_name = config.get('app_name', 'Amazon_Analysis')
        master = config.get('master', 'local[*]')
        driver_memory = config.get('driver_memory', '4g')
        executor_instances = config.get('executor_instances', 2)
        executor_memory = config.get('executor_memory', '2g')
        shuffle_partitions = config.get('shuffle_partitions', 8)

        # 生成随机端口避免冲突
        driver_port = random.randint(20000, 60000)
        block_manager_port = driver_port + 1
        rpc_port = driver_port + 2

        # 根据模式构建 builder
        builder = SparkSession.builder \
            .appName(app_name) \
            .config("spark.driver.memory", driver_memory) \
            .config("spark.sql.shuffle.partitions", shuffle_partitions) \
            .config("spark.driver.port", driver_port) \
            .config("spark.blockManager.port", block_manager_port) \
            .config("spark.rpc.message.maxSize", "256") \
            .config("spark.driver.maxRetries", "10")

        if mode == 'local':
            # 本地模式
            builder = builder.master("local[*]")
        else:
            # 集群模式
            builder = builder.master(master)
            builder = builder.config("spark.executor.instances", executor_instances)
            builder = builder.config("spark.executor.memory", executor_memory)

        # 启用 Hive 支持（可选）
        builder = builder.enableHiveSupport()

        spark = builder.getOrCreate()
        spark.sparkContext.setLogLevel(config.get('level', 'WARN'))

        return spark

    def get_session(self) -> SparkSession:
        """获取 SparkSession"""
        return self._spark

    def create_session(self, config: Dict[str, Any]) -> SparkSession:
        """根据配置创建新的 SparkSession"""
        self._spark = self._create_spark_session(config)
        return self._spark

    def stop(self):
        """停止 SparkSession"""
        if self._spark is not None:
            try:
                self._spark.stop()
            except Exception as e:
                print(f"Warning: Error stopping Spark: {e}")
            self._spark = None