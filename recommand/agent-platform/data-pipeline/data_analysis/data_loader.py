#!/usr/bin/env python3
"""
数据加载器 - 支持多种数据格式
"""

from typing import Dict, Any, Tuple, Optional
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.types import FloatType, IntegerType, StringType, StructType, StructField


class DataLoader:
    """数据加载器"""

    # 新版 Amazon 数据 Schema (All_Beauty)
    AMAZON_NEW_REVIEW_SCHEMA = StructType([
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

    AMAZON_NEW_META_SCHEMA = StructType([
        StructField("main_category", StringType(), True),
        StructField("title", StringType(), True),
        StructField("average_rating", FloatType(), True),
        StructField("rating_number", IntegerType(), True),
        StructField("features", StringType(), True),
        StructField("description", StringType(), True),
        StructField("price", FloatType(), True),
        StructField("images", StringType(), True),
        StructField("videos", StringType(), True),
        StructField("store", StringType(), True),
        StructField("categories", StringType(), True),
        StructField("details", StringType(), True),
        StructField("parent_asin", StringType(), True),
        StructField("bought_together", StringType(), True),
    ])

    # 旧版 Amazon 数据 Schema (Books, Movies, Video Games)
    AMAZON_OLD_REVIEW_SCHEMA = StructType([
        StructField("overall", FloatType(), True),
        StructField("verified", StringType(), True),
        StructField("reviewTime", StringType(), True),
        StructField("reviewerID", StringType(), True),
        StructField("asin", StringType(), True),
        StructField("style", StringType(), True),
        StructField("reviewerName", StringType(), True),
        StructField("reviewText", StringType(), True),
        StructField("summary", StringType(), True),
        StructField("unixReviewTime", IntegerType(), True),
    ])

    AMAZON_OLD_META_SCHEMA = StructType([
        StructField("category", StringType(), True),
        StructField("tech1", StringType(), True),
        StructField("description", StringType(), True),
        StructField("fit", StringType(), True),
        StructField("title", StringType(), True),
        StructField("also_buy", StringType(), True),
        StructField("tech2", StringType(), True),
        StructField("brand", StringType(), True),
        StructField("feature", StringType(), True),
        StructField("rank", StringType(), True),
        StructField("also_view", StringType(), True),
        StructField("main_cat", StringType(), True),
        StructField("similar_item", StringType(), True),
        StructField("date", StringType(), True),
        StructField("price", StringType(), True),
        StructField("asin", StringType(), True),
        StructField("imageURL", StringType(), True),
        StructField("imageURLHighRes", StringType(), True),
    ])

    def __init__(self, spark: SparkSession, source_type: str = 'amazon_new'):
        """
        初始化数据加载器

        Args:
            spark: SparkSession 实例
            source_type: 数据源类型 (amazon_new | amazon_old)
        """
        self.spark = spark
        self.source_type = source_type

    def load_review_data(self, file_path: str) -> DataFrame:
        """
        加载评论数据

        Args:
            file_path: 评论数据文件路径

        Returns:
            评论 DataFrame
        """
        if self.source_type == 'amazon_new':
            return self.spark.read.json(file_path, schema=self.AMAZON_NEW_REVIEW_SCHEMA)
        else:
            return self.spark.read.json(file_path, schema=self.AMAZON_OLD_REVIEW_SCHEMA)

    def load_meta_data(self, file_path: str) -> DataFrame:
        """
        加载元数据

        Args:
            file_path: 元数据文件路径

        Returns:
            元数据 DataFrame
        """
        if self.source_type == 'amazon_new':
            return self.spark.read.json(file_path, schema=self.AMAZON_NEW_META_SCHEMA)
        else:
            return self.spark.read.json(file_path, schema=self.AMAZON_OLD_META_SCHEMA)

    def normalize_data(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> Tuple[DataFrame, Optional[DataFrame]]:
        """
        统一数据格式，将不同数据源的字段名标准化

        Args:
            reviews_df: 原始评论 DataFrame
            meta_df: 原始元数据 DataFrame

        Returns:
            标准化后的 (reviews_df, meta_df)
        """
        if self.source_type == 'amazon_new':
            # 新版数据已经是标准格式，直接返回
            return reviews_df, meta_df
        else:
            # 旧版数据需要字段映射
            reviews_df = self._normalize_old_review(reviews_df)
            if meta_df is not None:
                meta_df = self._normalize_old_meta(meta_df)
            return reviews_df, meta_df

    def _normalize_old_review(self, df: DataFrame) -> DataFrame:
        """将旧版评论数据字段映射到标准格式"""
        from pyspark.sql import functions as F

        # 字段映射: 旧字段 -> 新字段
        # rating, user_id, product_id, review_text, review_title, timestamp, verified_purchase, helpful_vote
        return df.withColumnRenamed("overall", "rating") \
            .withColumnRenamed("reviewerID", "user_id") \
            .withColumnRenamed("asin", "parent_asin") \
            .withColumnRenamed("reviewText", "text") \
            .withColumnRenamed("summary", "title") \
            .withColumnRenamed("unixReviewTime", "timestamp") \
            .withColumn("verified_purchase", F.when(F.col("verified") == True, "true").otherwise("false")) \
            .withColumn("helpful_vote", F.lit(0).cast(IntegerType())) \
            .withColumn("images", F.lit("").cast(StringType())) \
            .withColumn("asin", F.col("parent_asin"))

    def _normalize_old_meta(self, df: DataFrame) -> DataFrame:
        """将旧版元数据字段映射到标准格式"""
        return df  # 元数据暂时保持原样


def create_data_loader(spark: SparkSession, config: Dict[str, Any]) -> DataLoader:
    """
    创建数据加载器

    Args:
        spark: SparkSession 实例
        config: 配置字典

    Returns:
        DataLoader 实例
    """
    source_type = config.get('data', {}).get('source_type', 'amazon_new')
    return DataLoader(spark, source_type)