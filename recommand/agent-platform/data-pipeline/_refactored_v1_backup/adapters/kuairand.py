"""Kuairand 数据集适配器"""
from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql.functions import col, unix_timestamp, when

from .base import BaseDataSource
from .factory import register_adapter
import os


@register_adapter("Kuairand")
class KuairandAdapter(BaseDataSource):
    """
    kuairand 数据集适配器

    支持的数据格式:
    - 交互数据字段:
    - 物品数据字段:
    """

    def load_users(self) -> DataFrame:
        """
        加载用户数据

        Amazon 数据集本身不包含单独的用户文件，
        用户信息需要从交互数据中提取。
        """
        kuairand_path = self.config.get("kuaiRandFolder")
        if not kuairand_path:
            raise ValueError("配置中未指定 kuaiRandFolder")

        df = self.spark.read.option("header", "true").csv(f"{kuairand_path}/user_features_*.csv")


        cols_to_convert = [f"onehot_feat{i}" for i in range(18)]
        cols_to_convert += ["is_lowactive_period", "is_live_streamer", "is_video_author",
                            "follow_user_num", "fans_user_num", "friend_user_num", "register_days"]
        # 2. 构造转换映射字典 {列名: 转换后的列对象}
        conversion_map = {c: col(c).cast("double").cast("int") for c in cols_to_convert}
        df = df.withColumns(conversion_map)
        return df

    def load_items(self) -> DataFrame:
        """加载旧版格式的物品数据"""
        kuairand_path = self.config.get("kuaiRandFolder")
        if not kuairand_path:
            raise ValueError("配置中未指定 kuaiRandFolder")

        kuairand_video_captions = self.spark.read.option("header", "true").csv(f"{kuairand_path}/kuairand_video_captions.csv")
        kuairand_video_categories = self.spark.read.option("header", "true").csv(f"{kuairand_path}/kuairand_video_categories.csv")
        video_features_basic = self.spark.read.option("header", "true").csv(f"{kuairand_path}/video_features_basic*.csv")
        video_features_statistic = self.spark.read.option("header", "true").csv(f"{kuairand_path}/video_features_statistic*.csv")

        #除了video_id和count其他列都变成float
        exclude_cols = ["video_id", "counts"]
        float_cols_map = {c: col(c).cast("float") for c in video_features_statistic.columns if c not in exclude_cols}
        video_features_statistic = video_features_statistic.withColumns(float_cols_map)

        kuairand_video_captions = kuairand_video_captions.withColumnRenamed("final_video_id", "video_id")
        kuairand_video_categories = kuairand_video_categories.withColumnRenamed("final_video_id", "video_id")

        df = video_features_basic.join(video_features_statistic, on="video_id", how="left")
        df = df.join(kuairand_video_categories, on="video_id", how="left")
        df = df.join(kuairand_video_captions, on="video_id", how="left")

        cols_convert_int = ["video_duration", "server_width", "server_height", "music_id", "music_type", "counts"]
        conversion_map = {c: col(c).cast("double").cast("int") for c in cols_convert_int}
        df = df.withColumns(conversion_map)

        cols_convert_float = ["duration", "first_level_category_id", "first_level_category_prob", "second_level_category_id",
                              "second_level_category_prob", "third_level_category_id", "third_level_category_prob",
                              "fourth_level_category_id", "fourth_level_category_prob"]
        conversion_map = {c: col(c).cast("float") for c in cols_convert_float}
        df = df.withColumn("upload_dt", unix_timestamp(col("upload_dt")))
        df = df.withColumns(conversion_map)
        rename_map = {
            "video_id": "item_id",
            "show_cover_text": "item_title",
            "caption": "item_description"
        }

        return df.withColumnsRenamed(rename_map)

    def load_co_occurrence(self) -> DataFrame:
        pass

    def load_interactions(self) -> DataFrame:
        """加载交互数据"""
        kuairand_path = self.config.get("kuaiRandFolder")
        if not kuairand_path:
            raise ValueError("配置中未指定 kuaiRandFolder")

        df = self.spark.read.option("header", "true").csv(f"{kuairand_path}/log_standard*.csv")
        df = df.withColumn("timestamp", col("time_ms").cast("long"))
        df = df.withColumn("action",
                           when(col("is_like") == "1", "like")
                           .when(col("long_view") == "1", "like")
                           .otherwise("dislike"))
        df = df.withColumnRenamed("video_id", "item_id")
        df = df.drop("time_ms", "video_id")
        exclude_cols = ["item_id", "user_id", "timestamp", "action"]
        float_cols_map = {c: col(c).cast("int") for c in df.columns if c not in exclude_cols}
        df = df.withColumns(float_cols_map)
        return df