# -*- coding: utf-8 -*-
"""pytest 配置文件和共享 fixtures"""

import pytest
from pyspark.sql import SparkSession
import os
import sys

os.environ['PYSPARK_PYTHON'] = sys.executable
os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable


@pytest.fixture(scope="session")
def spark():
    """创建本地 Spark 会话（session 级别，所有测试共享）"""
    spark = SparkSession.builder \
        .master("local[1]") \
        .appName("UnitTest") \
        .config("spark.driver.memory", "512m") \
        .config("spark.sql.shuffle.partitions", "2") \
        .config("spark.ui.enabled", "false") \
        .config("spark.driver.maxResultSize", "256m") \
        .config("spark.executor.memory", "512m") \
        .getOrCreate()
    spark.sparkContext.setLogLevel("WARN")

    yield spark

    spark.stop()


@pytest.fixture
def spark_session(spark):
    """返回 Spark 会话（function 级别，每个测试函数独立）"""
    return spark