"""Spark会话管理模块"""

import os
import random
from pyspark.sql import SparkSession


class SparkManager:
    """Spark会话管理器（单例模式）"""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, app_name: str = "DataProcessing",
                 memory: str = "4g",
                 partitions: int = 8,
                 driver_cores: int = 2,
                 executor_cores: int = 2,
                 executor_memory: str = "4g",
                 executor_numbers: int = 1,
                 master: str = "local[*]",
                 local_dir: str = None,
                 checkpoint_dir: str = None):
        if not hasattr(self, '_initialized'):
            self.app_name = app_name
            self.memory = memory
            self.partitions = partitions
            self.driver_cores = driver_cores
            self.executor_cores = executor_cores
            self.executor_memory = executor_memory
            self.executor_numbers = executor_numbers
            self.master = master
            # Windows 兼容的临时目录
            self.local_dir = local_dir or os.path.join(os.path.expanduser("~"), "spark-tmp")
            self.checkpoint_dir = checkpoint_dir
            self._spark = None
            self._initialized = True

    def get_session(self) -> SparkSession:
        """获取或创建SparkSession"""
        # 确保临时目录存在
        os.makedirs(self.local_dir, exist_ok=True)
        if self.checkpoint_dir:
            os.makedirs(self.checkpoint_dir, exist_ok=True)

        if self._spark is None or self._spark.sparkContext.isStopped():
            driver_port = random.randint(20000, 60000)
            builder = SparkSession.builder \
                .appName(self.app_name) \
                .master(self.master) \
                .config("spark.driver.memory", self.memory) \
                .config("spark.driver.cores", self.driver_cores) \
                .config("spark.sql.shuffle.partitions", self.partitions) \
                .config("spark.driver.port", driver_port) \
                .config("spark.blockManager.port", driver_port + 1) \
                .config("spark.local.dir", self.local_dir) \
                .config("spark.sql.autoBroadcastJoinThreshold", "100MB") \
                .config("spark.sql.broadcastTimeout", "600") \
                .config("spark.network.timeout", "600s") \
                .config("spark.executor.heartbeatInterval", "60s")

            # 设置 checkpoint 目录
            if self.checkpoint_dir:
                builder = builder.config("spark.sparkContext.checkpointDir", self.checkpoint_dir)

            # Executor 配置（仅在非 local 模式下生效）
            if self.master != "local[*]" and not self.master.startswith("local"):
                builder = builder \
                    .config("spark.executor.cores", self.executor_cores) \
                    .config("spark.executor.memory", self.executor_memory) \
                    .config("spark.executor.instances", self.executor_numbers)

            self._spark = builder \
                .enableHiveSupport() \
                .getOrCreate()
            self._spark.sparkContext.setLogLevel("WARN")
        return self._spark

    def stop(self):
        """停止SparkSession"""
        if self._spark is not None:
            self._spark.stop()
            self._spark = None


def create_spark_session(app_name: str = "DataProcessing", **kwargs) -> SparkSession:
    """创建SparkSession的便捷函数"""
    manager = SparkManager(app_name, **kwargs)
    return manager.get_session()