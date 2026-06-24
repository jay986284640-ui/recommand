"""自拓展门店券适配器(对齐 LP Agent content_type=self_operated_coupon)

数据来源:商家自助入驻平台的券交易导出
"""

from pyspark.sql import DataFrame
from pyspark.sql.functions import col, lit

from .base import BaseDataSource
from .factory import register_adapter


@register_adapter("self_operated_coupon")
class SelfOperatedCouponAdapter(BaseDataSource):
    """自拓展门店券数据适配器

    配置项:
        trade_input: 交易表路径
        merchant_input: 商家表路径
    """

    def load_users(self) -> DataFrame:
        trade = self._read_trade()
        return trade.select("user_id").distinct().withColumn("source", lit("self_operated_coupon"))

    def load_items(self) -> DataFrame:
        trade = self._read_trade()
        merchant = self._read_merchant()
        items = (
            trade.select("coupon_id", "merchant_id")
            .dropDuplicates(["coupon_id"])
            .join(merchant, on="merchant_id", how="left")
        )
        return items.withColumnRenamed("coupon_id", "item_id").withColumn("content_type", lit("self_operated_coupon"))

    def load_interactions(self) -> DataFrame:
        trade = self._read_trade()
        return (
            trade.filter(col("action").isin(["buy", "use"]))
            .select("user_id", col("coupon_id").alias("item_id"), "timestamp", "action", "merchant_id")
        )

    def load_co_occurrence(self) -> DataFrame:
        # 自拓展门店券没有跨店共购语义,返回 None
        return None

    def _read_trade(self) -> DataFrame:
        path = self.config.get("trade_input")
        if not path:
            raise ValueError("self_operated_coupon adapter: trade_input 未配置")
        return self.spark.read.parquet(path)

    def _read_merchant(self) -> DataFrame:
        path = self.config.get("merchant_input")
        if not path:
            schema = "merchant_id STRING, merchant_name STRING, category STRING, lat DOUBLE, lng DOUBLE"
            return self.spark.createDataFrame([], schema)
        return self.spark.read.parquet(path)
