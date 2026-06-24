"""Netflix 数据集适配器"""

import pyspark.sql
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.functions import col, to_timestamp, unix_timestamp, last, lit, monotonically_increasing_id, regexp_extract
from pyspark.sql.types import StructType, StructField, StringType, IntegerType

from .base import BaseDataSource
from .factory import register_adapter


@register_adapter("netflix")
class NetflixAdapter(BaseDataSource):
    """
    Netflix 数据集适配器

    Netflix Prize 数据集格式:
    - combined_data_*.txt: 交互数据，格式 movie_id,rating,date
    - movie_titles.csv: 电影信息，格式 movie_id,year,title
    """

    def load_users(self) -> DataFrame:
        """
        加载用户数据

        Netflix 数据集不包含单独的用户文件，
        用户信息需要从交互数据中提取。
        只需要 user_id，原始数据集中没有其他用户特征。
        """
        interactions = self.load_interactions()

        # 从交互数据中提取唯一用户，只保留 user_id
        users_df = interactions.select("user_id").distinct()

        return users_df

    def load_items(self) -> DataFrame:
        """加载物品（电影）数据"""
        titles_path = self.config.get("titles_input")
        if not titles_path:
            raise ValueError("配置中未指定 titles_input (电影标题数据路径)")

        # 读取电影标题文件
        # 格式: movie_id,year,title
        schema = StructType([
            StructField("movie_id", IntegerType(), True),
            StructField("year", IntegerType(), True),
            StructField("title", StringType(), True),
        ])

        df = self.spark.read.csv(titles_path, header=False, schema=schema)

        # 转换为标准列名
        result = df.withColumnRenamed("movie_id", "item_id") \
                   .withColumn("item_id", col("item_id").cast("string"))

        # item_title 是必须的，如果没有则为空字符串
        if "title" in df.columns:
            result = result.withColumnRenamed("title", "item_title")
        else:
            result = result.withColumn("item_title", lit(""))

        # item_description 是必须的，如果没有则为空字符串
        result = result.withColumn("item_description", lit(""))

        # 保留原始数据集中的其他字段（动态扩展列）
        extra_cols = [c for c in df.columns if c not in ["movie_id", "title"]]
        for c in extra_cols:
            if c == "year":
                result = result.withColumnRenamed("year", "item_year")
            # 其他字段保留原名

        return result

    def load_interactions(self) -> DataFrame:
        """加载交互数据"""
        combined_data_inputs = self.config.get("combined_data_input")
        file_paths = self._validated_inputs(combined_data_inputs)

        # Netflix 数据格式是特殊的：
        # movie_id, (后面跟着多个 rating 记录)
        # 例如:
        # 1:
        # 1488844,3,2005-09-06
        # 822109,5,2005-05-13
        #
        # 需要先读取原始文本，然后解析

        # 读取所有文件并合并，同时添加文件索引以支持分区窗口操作
        raw_dfs = []
        for idx, file_path in enumerate(file_paths):
            raw_df = self.spark.read.text(file_path)
            raw_df = raw_df.withColumn("file_idx", lit(idx))
            raw_dfs.append(raw_df)

        raw_df = raw_dfs[0]
        if len(raw_dfs) > 1:
            for i in range(1, len(raw_dfs)):
                raw_df = raw_df.unionAll(raw_dfs[i])

        # 标记哪些行是电影ID行
        raw_df = raw_df.withColumn("is_movie_id", col("value").rlike("^\\d+:$"))

        # 电影ID行的值（去掉冒号）
        raw_df = raw_df.withColumn(
            "movie_id",
            F.when(col("is_movie_id"), regexp_extract("value", "^(\\d+):$", 1)).otherwise(None)
        )

        # 使用前向填充将电影ID向下传播（按文件分区，按行号排序）
        # 先添加行号列
        raw_df = raw_df.withColumn("row_num", monotonically_increasing_id())
        # 按文件分区，电影ID向下传播
        window_spec = pyspark.sql.Window.partitionBy("file_idx").orderBy("row_num")
        raw_df = raw_df.withColumn("movie_id", last("movie_id", ignorenulls=True).over(
            window_spec
        ))

        # 过滤掉电影ID行，只保留评分记录
        ratings_df = raw_df.filter(~col("is_movie_id"))

        # 解析评分记录: user_id,rating,date
        ratings_df = ratings_df.withColumn("user_id", regexp_extract("value", "^(\\d+),", 1).cast("integer")) \
                               .withColumn("rating", regexp_extract("value", "^\\d+,(\\d+),", 1).cast("float")) \
                               .withColumn("date_str", regexp_extract("value", "^\\d+,\\d+,(.+)$", 1))

        # 过滤掉无效记录
        ratings_df = ratings_df.filter(
            (col("user_id").isNotNull()) &
            (col("rating").isNotNull()) &
            (col("date_str").isNotNull())
        )

        # 转换日期为时间戳
        ratings_df = ratings_df.withColumn(
            "timestamp",
            unix_timestamp(to_timestamp("date_str", "yyyy-MM-dd"))
        )

        # 添加 action 列（基于 rating）
        # Netflix 使用 1-5 评分，>=4 视为 like，<=2 视为 dislike
        ratings_df = ratings_df.withColumn(
            "action",
            F.when(col("rating") >= 4, "like")
            .when(col("rating") <= 2, "dislike")
            .otherwise("neutral")
        )

        # 转换 movie_id 和 user_id 为字符串，并重命名
        ratings_df = ratings_df.withColumn("movie_id", col("movie_id").cast("string")) \
                               .withColumn("user_id", col("user_id").cast("string")) \
                               .withColumnRenamed("movie_id", "item_id")

        # 选择并返回标准列（按设计文档要求）
        return ratings_df.select(
            "user_id", "item_id", "timestamp", "action", "rating"
        )

    def _validated_inputs(self, combined_data_inputs) -> list:
        if not combined_data_inputs:
            raise ValueError("配置中未指定 combined_data_input (交互数据路径)")

        # 支持单文件或多文件（列表）
        if isinstance(combined_data_inputs, str):
            file_paths = [combined_data_inputs]
        elif isinstance(combined_data_inputs, list):
            file_paths = combined_data_inputs
        else:
            raise ValueError("combined_data_input 必须是字符串或字符串列表")
        return file_paths

    def load_co_occurrence(self) -> DataFrame | None:
        """Netflix 数据集没有共现数据"""
        return None

    def validate_config(self) -> None:
        """验证 Netflix 适配器配置完整性"""
        if not self.config.get("combined_data_input"):
            raise ValueError("配置中未指定 combined_data_input (交互数据路径)")
        if not self.config.get("titles_input"):
            raise ValueError("配置中未指定 titles_input (电影标题数据路径)")