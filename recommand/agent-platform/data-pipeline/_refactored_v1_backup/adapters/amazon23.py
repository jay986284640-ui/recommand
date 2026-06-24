"""Amazon23 数据集适配器"""

from pyspark.sql import DataFrame
from pyspark.sql.functions import (col, when, array, coalesce, from_json)

from .base import BaseDataSource
from .factory import register_adapter


@register_adapter("amazon_new")
class AmazonAdapter(BaseDataSource):
    """
    Amazon 新版数据集适配器（2018版及以后）

    支持的数据格式:
    - 交互数据字段: rating, title, text, images, asin, parent_asin, user_id, timestamp, helpful_vote, verified_purchase
    - 物品数据字段: asin, parent_asin, title, description, image, category, brand, etc.
    """

    def load_users(self) -> DataFrame:
        """
        加载用户数据

        Amazon 数据集本身不包含单独的用户文件，
        用户信息需要从交互数据中提取。
        """
        interactions = self.load_interactions()

        return interactions.select("user_id")

    def load_items(self) -> DataFrame:
        """加载物品数据"""
        meta_path = self.config.get("meta_input")

        if not meta_path:
            raise ValueError("配置中未指定 meta_input (物品数据路径)")
        from pyspark.sql.types import StructType, StructField, FloatType, StringType, IntegerType, ArrayType
        schema = StructType([
            StructField("main_category", StringType(), True),
            StructField("title", StringType(), True),
            StructField("average_rating", FloatType(), True),
            StructField("rating_number", IntegerType(), True),
            StructField("features", ArrayType(StringType()), True),
            StructField("description", ArrayType(StringType()), True),
            StructField("price", FloatType(), True),
            StructField("images", ArrayType(StringType()), True),
            StructField("videos", ArrayType(StringType()), True),
            StructField("store", StringType(), True),
            StructField("categories", ArrayType(StringType()), True),
            StructField("parent_asin", StringType(), True),
            StructField("bought_together", ArrayType(StringType()), True),
        ])
        df = self.spark.read.json(meta_path, schema=schema)

        # df
        df = df.drop("bought_together")
        rename_map = {
            "parent_asin": "item_id",
            "title": "item_title",
            "description": "item_description"
        }

        df = df.drop("details")
        return df.withColumnsRenamed(rename_map)

    def load_co_occurrence(self) -> DataFrame:
        meta_path = self.config.get("meta_input")
        if not meta_path:
            raise ValueError("配置中未指定 meta_input (物品数据路径)")

        df = self.spark.read.json(meta_path)
        df = df.select("parent_asin", "bought_together")
        from pyspark.sql.types import ArrayType, StringType

        df = df.withColumn(
            "bought_together",
            # 1. 先用 from_json 将 String 转换为 Array
            # 2. 如果转换结果为 null，再用 coalesce 补上空数组
            coalesce(
                from_json(col("bought_together"), ArrayType(StringType())),
                array().cast("array<string>")
            )
        )
        rename_map = {
            "parent_asin": "item_id",
            "bought_together": "related_items"
        }

        return df.withColumnsRenamed(rename_map)

    def load_interactions(self) -> DataFrame:
        """加载交互数据"""
        review_path = self.config.get("review_input")
        if not review_path:
            raise ValueError("配置中未指定 review_input (交互数据路径)")

        # 定义 schema
        from pyspark.sql.types import StructType, StructField, FloatType, StringType, IntegerType, LongType

        schema = StructType([
            StructField("rating", FloatType(), True),
            StructField("title", StringType(), True),
            StructField("text", StringType(), True),
            StructField("images", StringType(), True),
            StructField("asin", StringType(), True),
            StructField("parent_asin", StringType(), True),
            StructField("user_id", StringType(), True),
            StructField("timestamp", LongType(), True),
            StructField("helpful_vote", IntegerType(), True),
            StructField("verified_purchase", StringType(), True),
        ])
        self.spark.conf.set("spark.sql.caseSensitive", "true")
        df = self.spark.read.json(review_path, schema=schema)

        # 标准化字段名
        result = (df
                  .withColumnRenamed("text", "review_text") \
                  .withColumnRenamed("title", "review_title") \
                  .withColumnRenamed("parent_asin", "item_id") \
                  .withColumnRenamed("verified_purchase", "verified"))

        # 转换 timestamp（如果是毫秒转为秒）
        # Amazon 数据集的 timestamp 可能是秒或毫秒，需要根据数据范围判断
        result = result.withColumn(
            "timestamp",
            when(col("timestamp") > 1000000000000, col("timestamp") / 1000)  # 毫秒转秒
            .otherwise(col("timestamp"))
        )

        # 添加 action 列（基于 rating）
        result = result.withColumn(
            "action",
            when(col("rating") >= 4, "like")
            .when(col("rating") <= 2, "dislike")
            .otherwise("neutral")
        )

        # 添加额外特征列
        result = result.withColumn("rating", col("rating")) \
            .withColumn("verified", col("verified").isNotNull())

        # 选择并返回标准列
        standard_cols = ["user_id", "item_id", "timestamp",
                         "action", "rating", "review_text", "review_title", "verified"]
        available_cols = [c for c in standard_cols if c in result.columns]

        return result.select(*available_cols)
