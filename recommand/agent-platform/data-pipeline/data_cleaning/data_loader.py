"""数据加载模块"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from pyspark.sql import SparkSession
from pyspark.sql.types import IntegerType, FloatType, StringType, StructType, StructField


class DataLoader:
    """数据加载器"""

    def __init__(self, spark: SparkSession):
        self.spark = spark

    def load_review_data(self, file_path: str, source_type: str = "amazon_new"):
        """加载评论数据"""
        if source_type == "amazon_new":
            schema = StructType([
                StructField("rating", FloatType(), True),
                StructField("title", StringType(), True),
                StructField("text", StringType(), True),
                StructField("images", StringType(), True),
                StructField("asin", StringType(), True),
                StructField("parent_asin", StringType(), True),
                StructField("user_id", StringType(), True),
                StructField("timestamp", IntegerType(), True),
                StructField("helpful_vote", IntegerType(), True),
                StructField("verified_purchase", StringType(), True),
            ])
        else:
            schema = StructType([
                StructField("overall", FloatType(), True),
                StructField("summary", StringType(), True),
                StructField("reviewText", StringType(), True),
                StructField("reviewerID", StringType(), True),
                StructField("asin", StringType(), True),
                StructField("unixReviewTime", IntegerType(), True),
                StructField("verified", StringType(), True),
                StructField("style", StringType(), True),
                StructField("reviewTime", StringType(), True),
            ])

        df = self.spark.read.json(file_path, schema=schema)

        # 标准化字段名
        if source_type == "amazon_new":
            df = df.withColumnRenamed("text", "review_text") \
                .withColumnRenamed("title", "review_title") \
                .withColumnRenamed("parent_asin", "product_id")
        else:
            df = df.withColumnRenamed("overall", "rating") \
                .withColumnRenamed("reviewText", "review_text") \
                .withColumnRenamed("summary", "review_title") \
                .withColumnRenamed("reviewerID", "user_id") \
                .withColumnRenamed("asin", "product_id") \
                .withColumnRenamed("unixReviewTime", "timestamp")

        return df

    def load_meta_data(self, file_path: str):
        """加载元数据"""
        df = self.spark.read.json(file_path)

        # 标准化字段名
        if "parent_asin" in df.columns:
            df = df.withColumnRenamed("parent_asin", "product_id")
        elif "asin" in df.columns:
            df = df.withColumnRenamed("asin", "product_id")

        return df
