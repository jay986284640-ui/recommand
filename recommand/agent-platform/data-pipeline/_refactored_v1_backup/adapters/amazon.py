"""Amazon 数据集适配器"""

from pyspark.sql import DataFrame
from pyspark.sql.functions import col, when, lit

from .base import BaseDataSource
from .factory import register_adapter


@register_adapter("amazon_old")
class AmazonOldAdapter(BaseDataSource):
    """
    Amazon 旧版数据集适配器（2014版及以前）

    支持的数据格式:
    - 交互数据字段: overall, summary, reviewText, reviewerID, asin, unixReviewTime, verified, style, reviewTime
    """
    
    def load_users(self) -> DataFrame:
        """
        加载用户数据

        Amazon 数据集本身不包含单独的用户文件，
        用户信息需要从交互数据中提取。
        """
        interactions = self.load_interactions()

        # 从交互数据中提取唯一用户
        users_df = interactions.select("user_id", "reviewerName").dropDuplicates(["user_id"])
        users_df = users_df.withColumnRenamed("reviewerName", "user_name")

        # 添加用户相关特征（如果交互数据中有）
        extra_cols = [c for c in interactions.columns if c not in ["user_id", "item_id", "timestamp", "action"]]

        if extra_cols:
            # 聚合用户的其他特征
            from pyspark.sql.functions import count, max as spark_max, min as spark_min
            users_df = users_df.join(
                interactions.groupBy("user_id").agg(
                    count("*").alias("interaction_count"),
                    spark_max("timestamp").alias("last_interaction_time"),
                    spark_min("timestamp").alias("first_interaction_time"),
                ),
                on="user_id",
                how="left"
            )
        else:
            users_df = users_df.withColumn("interaction_count", lit(0))

        return users_df

    def load_interactions(self) -> DataFrame:
        """加载旧版格式的交互数据"""
        review_path = self.config.get("review_input")
        if not review_path:
            raise ValueError("配置中未指定 review_input (交互数据路径)")

        from pyspark.sql.types import StructType, StructField, FloatType, StringType, IntegerType

        schema = StructType([
            StructField("overall", FloatType(), True),
            StructField("summary", StringType(), True),
            StructField("reviewText", StringType(), True),
            StructField("reviewerID", StringType(), True),
            StructField("asin", StringType(), True),
            StructField("unixReviewTime", IntegerType(), True),
            StructField("verified", StringType(), True),
            StructField("reviewerName", StringType(), True),
            StructField("reviewTime", StringType(), True),
        ])

        df = self.spark.read.json(review_path, schema=schema)

        # 标准化字段名
        result = df.withColumnRenamed("overall", "rating") \
                   .withColumnRenamed("reviewText", "review_text") \
                   .withColumnRenamed("summary", "review_title") \
                   .withColumnRenamed("reviewerID", "user_id") \
                   .withColumnRenamed("asin", "item_id") \
                   .withColumnRenamed("unixReviewTime", "timestamp")

        # 添加 action 列
        result = result.withColumn(
            "action",
            when(col("rating") >= 4, "like")
            .when(col("rating") <= 3, "dislike")
            .otherwise("neutral")
        )

        # 选择并返回标准列
        standard_cols = ["user_id", "item_id", "timestamp", 
                         "action", "rating", "review_text", "review_title", "reviewerName", "verified"]
        available_cols = [c for c in standard_cols if c in result.columns]

        return result.select(*available_cols)

    def load_items(self) -> DataFrame:
        """加载旧版格式的物品数据"""
        meta_path = self.config.get("meta_input")
        if not meta_path:
            raise ValueError("配置中未指定 meta_input (物品数据路径)")

        df = self.spark.read.json(meta_path)

        # df
        df = df.drop("also_view", "also_buy")
        rename_map = {
            "asin": "item_id",
            "title": "item_title",
            "description": "item_description"
        }

        df = df.withColumnsRenamed(rename_map)
        df = df.dropDuplicates(["item_id"])
        return df

    def load_co_occurrence(self) -> DataFrame | None:
        meta_path = self.config.get("meta_input")
        if not meta_path:
            raise ValueError("配置中未指定 meta_input (物品数据路径)")

        df = self.spark.read.json(meta_path)

        df = df.select(["asin", "also_buy"])

        rename_map = {
            "asin": "item_id",
            "also_buy": "related_items",
        }
        df = df.withColumnsRenamed(rename_map)
        df = df.dropDuplicates(["item_id"])

        return df
