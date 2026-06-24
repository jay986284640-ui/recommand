"""美团门店券适配器(对齐 LP Agent content_type=meituan_coupon)

数据来源:美团门店券交易系统导出
- 交易表:coupon_id, store_id, user_id, timestamp, action(buy/use/refund)
- 门店表:store_id, store_name, lat, lng, category
- 券模板表:coupon_template_id, denomination, threshold, valid_days
- 共购表:coupon_a_id, coupon_b_id, frequency(同店 / 同时段券共购)
"""

from pyspark.sql import DataFrame
from pyspark.sql.functions import col, lit, when

from .base import BaseDataSource
from .factory import register_adapter


@register_adapter("meituan_coupon")
class MeituanCouponAdapter(BaseDataSource):
    """美团门店券数据适配器

    配置项:
        trade_input: 交易表输入路径(parquet/json/csv)
        store_input: 门店表输入路径
        template_input: 券模板表输入路径
        cooccurrence_input: 共购表输入路径(可选)
    """

    def load_users(self) -> DataFrame:
        """从交易表提取唯一用户"""
        trade = self._read_trade()
        return trade.select("user_id").distinct().withColumn("source", lit("meituan_coupon"))

    def load_items(self) -> DataFrame:
        """券 = 物品,item_id = coupon_id,关联券模板 + 门店"""
        trade = self._read_trade()
        template = self._read_template()
        items = (
            trade.select("coupon_id", "store_id", "coupon_template_id")
            .dropDuplicates(["coupon_id"])
            .join(template, on="coupon_template_id", how="left")
        )
        return items.withColumnRenamed("coupon_id", "item_id").withColumn("content_type", lit("meituan_coupon"))

    def load_interactions(self) -> DataFrame:
        """交易行为作为交互记录"""
        trade = self._read_trade()
        # action: buy/use/refund → 推荐场景用 buy/use 作为正向信号
        return (
            trade.filter(col("action").isin(["buy", "use"]))
            .select("user_id", col("coupon_id").alias("item_id"), "timestamp", "action", "store_id")
        )

    def load_co_occurrence(self) -> DataFrame:
        """共购 = 同一用户在同一 1h 内购买的券对"""
        cooc = self._read_cooccurrence()
        if cooc is None:
            return None
        return cooc.select(
            col("coupon_a_id").alias("item_id"),
            col("coupon_b_id").alias("related_items_flat"),
            "frequency",
        )

    # ---------- helpers ----------
    def _read_trade(self) -> DataFrame:
        path = self.config.get("trade_input")
        if not path:
            raise ValueError("meituan_coupon adapter: trade_input 未配置")
        return self.spark.read.parquet(path)

    def _read_template(self) -> DataFrame:
        path = self.config.get("template_input")
        if not path:
            # 没有模板表时,返回空 DataFrame 让 join 出空
            schema = "coupon_template_id STRING, denomination DOUBLE, threshold DOUBLE, valid_days INT"
            return self.spark.createDataFrame([], schema)
        return self.spark.read.parquet(path)

    def _read_cooccurrence(self) -> DataFrame:
        path = self.config.get("cooccurrence_input")
        if not path:
            return None
        return self.spark.read.parquet(path)
