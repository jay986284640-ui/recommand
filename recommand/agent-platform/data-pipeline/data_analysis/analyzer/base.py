#!/usr/bin/env python3
"""
基础分析器 - 所有分析器的父类
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F


class BaseAnalyzer(ABC):
    """分析器基类"""

    def __init__(self, spark: SparkSession, config: Dict[str, Any], output_dir: str):
        """
        初始化分析器

        Args:
            spark: SparkSession 实例
            config: 配置字典
            output_dir: 输出目录
        """
        self.spark = spark
        self.config = config
        self.output_dir = output_dir
        self.result_df: Optional[DataFrame] = None

    @property
    @abstractmethod
    def name(self) -> str:
        """分析器名称"""
        pass

    @property
    @abstractmethod
    def output_file(self) -> str:
        """输出文件名"""
        pass

    @abstractmethod
    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        """
        执行分析

        Args:
            reviews_df: 评论数据 DataFrame
            meta_df: 元数据 DataFrame (可选)

        Returns:
            分析结果 DataFrame
        """
        pass

    def save_result(self, df: DataFrame) -> None:
        """保存结果到 CSV"""
        if df is not None:
            df.coalesce(1).write.mode("overwrite").option("header", "true").csv(
                f"{self.output_dir}/{self.output_file}.csv"
            )
            print(f"   已保存至: {self.output_dir}/{self.output_file}.csv")

    def run(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        """
        运行分析器

        Args:
            reviews_df: 评论数据 DataFrame
            meta_df: 元数据 DataFrame (可选)

        Returns:
            分析结果 DataFrame
        """
        print(f"\n[{self.name}]")
        self.result_df = self.analyze(reviews_df, meta_df)

        if self.result_df is not None:
            self.result_df.show(20, truncate=False)
            self.save_result(self.result_df)

        return self.result_df


class DataFrameMixin:
    """DataFrame 工具 mixin"""

    @staticmethod
    def add_derived_columns(df: DataFrame) -> DataFrame:
        """添加衍生字段"""
        df = df.withColumn(
            "review_date",
            F.to_date(F.from_unixtime(F.col("timestamp") / 1000, "yyyy-MM-dd"))
        )
        df = df.withColumn(
            "review_year_month",
            F.date_format(F.col("review_date"), "yyyy-MM")
        )
        df = df.withColumn(
            "review_weekday",
            F.date_format(F.col("review_date"), "EEEE")
        )
        df = df.withColumn(
            "review_text_length",
            F.length(F.col("text"))
        )
        df = df.withColumn(
            "review_title_length",
            F.length(F.col("title"))
        )
        df = df.withColumn(
            "is_verified",
            F.when(F.lower(F.col("verified_purchase")) == "true", True).otherwise(False)
        )
        return df