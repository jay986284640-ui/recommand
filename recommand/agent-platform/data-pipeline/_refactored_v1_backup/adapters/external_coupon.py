"""外部券适配器(对齐 LP Agent content_type=external_coupon)

数据来源:第三方券源 API 拉取(点评、抖音、京东到家 等)
"""

from pyspark.sql import DataFrame
from pyspark.sql.functions import col, lit

from .base import BaseDataSource
from .factory import register_adapter


@register_adapter("external_coupon")
class ExternalCouponAdapter(BaseDataSource):
    """外部券数据适配器

    配置项:
        coupon_input: 外部券主表路径
        link_input: 外部券领取/核销关联表路径
    """

    def load_users(self) -> DataFrame:
        link = self._read_link()
        if link is None:
            # 外部券没有关联表 → 用户侧留空,由 pipeline 后续从 LP 主流程回流
            return self.spark.createDataFrame([], "user_id STRING, source STRING")
        return link.select("user_id").distinct().withColumn("source", lit("external_coupon"))

    def load_items(self) -> DataFrame:
        coupon = self._read_coupon()
        return coupon.select(
            col("coupon_id").alias("item_id"),
            "title",
            "category",
            "denomination",
            "threshold",
            col("source").alias("external_source"),
        ).withColumn("content_type", lit("external_coupon"))

    def load_interactions(self) -> DataFrame:
        link = self._read_link()
        if link is None:
            return self.spark.createDataFrame([], "user_id STRING, item_id STRING, timestamp LONG, action STRING")
        return link.select(
            "user_id",
            col("coupon_id").alias("item_id"),
            "timestamp",
            "action",
        )

    def load_co_occurrence(self) -> DataFrame:
        # 外部券无跨店共购语义
        return None

    def _read_coupon(self) -> DataFrame:
        path = self.config.get("coupon_input")
        if not path:
            raise ValueError("external_coupon adapter: coupon_input 未配置")
        return self.spark.read.parquet(path)

    def _read_link(self) -> DataFrame:
        path = self.config.get("link_input")
        if not path:
            return None
        return self.spark.read.parquet(path)
