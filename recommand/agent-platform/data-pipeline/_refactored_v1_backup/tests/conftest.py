# -*- coding: utf-8 -*-
"""pytest 配置 + 把项目根加到 sys.path(让 from cleaning.X / from normalization.X 工作)"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest
from pyspark.sql import SparkSession

os.environ.setdefault('PYSPARK_PYTHON', sys.executable)
os.environ.setdefault('PYSPARK_DRIVER_PYTHON', sys.executable)


@pytest.fixture(scope="session")
def spark():
    """session 级共享的本地 Spark"""
    spark = (
        SparkSession.builder
        .master("local[1]")
        .appName("DataPipelineUnitTest")
        .config("spark.driver.memory", "512m")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .config("spark.driver.maxResultSize", "256m")
        .config("spark.executor.memory", "512m")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    yield spark
    spark.stop()


@pytest.fixture
def spark_session(spark):
    return spark
