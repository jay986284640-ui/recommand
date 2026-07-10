#!/usr/bin/env python3
"""检测器 - 地理不匹配(LBS 券异常,可选)

O2O 门店券应由门店附近用户自然发现;全站 push/banner 会让远距离用户产生交互。
用 haversine 计算每条交互 "用户位置(user_lat/lon)↔门店位置(item_lat/lon)" 的
距离,按 item 聚合 p50/p90 距离与超远占比,标记地理异常商品。

依赖交互透传的 user_lat/user_lon 与门店画像的 item_lat/item_lon(meta_df)。
"""

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


def haversine_km(lat1, lon1, lat2, lon2):
    """两点球面距离(公里)。参数为 Spark Column(十进制度)。"""
    r = 6371.0
    dlat = F.radians(lat2 - lat1)
    dlon = F.radians(lon2 - lon1)
    a = (
        F.sin(dlat / 2) ** 2
        + F.cos(F.radians(lat1)) * F.cos(F.radians(lat2)) * F.sin(dlon / 2) ** 2
    )
    return F.lit(2 * r) * F.asin(F.sqrt(a))


class GeoMismatchAnalyzer(BaseAnalyzer):
    """地理不匹配分析器"""

    @property
    def name(self) -> str:
        return "地理不匹配(LBS 券远距离交互)"

    @property
    def output_file(self) -> str:
        return "geo_mismatch"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        far_km = float(self.config.get("far_km", 50.0))
        far_share_threshold = float(self.config.get("far_share_threshold", 0.5))
        p90_threshold = float(self.config.get("p90_km_threshold", 100.0))
        min_interactions = int(self.config.get("min_interactions", 50))

        if meta_df is None or "item_lat" not in meta_df.columns:
            # 无门店经纬度,返回空标记表
            return reviews_df.groupBy("item_id").agg(
                F.count("*").alias("interaction_count"),
                F.lit(None).cast("double").alias("p90_km"),
                F.lit(0.0).alias("far_share"),
                F.lit(False).alias("flag_geo"),
            )

        shop = meta_df.select(
            F.col("item_id"),
            F.col("item_lat").cast("double"),
            F.col("item_lon").cast("double"),
        )

        joined = reviews_df.select(
            "item_id", "user_lat", "user_lon"
        ).join(shop, "item_id", "inner")

        joined = joined.filter(
            F.col("user_lat").isNotNull()
            & F.col("user_lon").isNotNull()
            & F.col("item_lat").isNotNull()
            & F.col("item_lon").isNotNull()
        ).withColumn(
            "dist_km",
            haversine_km(
                F.col("user_lat"), F.col("user_lon"),
                F.col("item_lat"), F.col("item_lon"),
            ),
        )

        per_item = joined.groupBy("item_id").agg(
            F.count("*").alias("interaction_count"),
            F.expr("approx_percentile(dist_km, 0.9)").alias("p90_km"),
            F.avg((F.col("dist_km") >= F.lit(far_km)).cast("double")).alias("far_share"),
        )

        per_item = per_item.withColumn(
            "flag_geo",
            (F.col("interaction_count") >= F.lit(min_interactions))
            & (
                (F.col("far_share") >= F.lit(far_share_threshold))
                | (F.col("p90_km") >= F.lit(p90_threshold))
            ),
        )

        return per_item.orderBy(F.desc("far_share"))


AnalyzerFactory.register("geo_mismatch", GeoMismatchAnalyzer)
