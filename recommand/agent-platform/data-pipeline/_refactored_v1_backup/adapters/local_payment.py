"""本地优惠买单适配器(对齐 LP Agent content_type=local_payment)

本地优惠买单 = 用户到店出示券码 → 商家扫码 → 收银台按 X 元结算。
数据形态:没有"券",只有订单(transaction)。
"""

from pyspark.sql import DataFrame
from pyspark.sql.functions import col, lit, concat

from .base import BaseDataSource
from .factory import register_adapter


def _store_item_id(store_id_col):
    """把 store_id 拼成虚拟 item_id (store-{store_id})"""
    return concat(lit("store-"), col(store_id_col))


@register_adapter("local_payment")
class LocalPaymentAdapter(BaseDataSource):
    """本地优惠买单数据适配器

    配置项:
        transaction_input: 买单记录路径
        store_input: 门店表路径
    """

    def load_users(self) -> DataFrame:
        txn = self._read_transaction()
        return txn.select("user_id").distinct().withColumn("source", lit("local_payment"))

    def load_items(self) -> DataFrame:
        # 本地优惠买单没有独立 item 概念,合成 store-{store_id} 的虚拟 item
        txn = self._read_transaction()
        store = self._read_store()
        items = (
            txn.select("store_id")
            .distinct()
            .withColumn("item_id", _store_item_id("store_id"))
            .join(store, on="store_id", how="left")
        )
        return items.withColumn("content_type", lit("local_payment"))

    def load_interactions(self) -> DataFrame:
        txn = self._read_transaction()
        return (
            txn.withColumn("item_id", _store_item_id("store_id"))
            .select("user_id", "item_id", "timestamp", "amount", "store_id")
            .withColumn("action", lit("pay"))
        )

    def load_co_occurrence(self) -> DataFrame:
        # 同一用户同一天的到店组合
        return None

    def _read_transaction(self) -> DataFrame:
        path = self.config.get("transaction_input")
        if not path:
            raise ValueError("local_payment adapter: transaction_input 未配置")
        return self.spark.read.parquet(path)

    def _read_store(self) -> DataFrame:
        path = self.config.get("store_input")
        if not path:
            schema = "store_id STRING, store_name STRING, category STRING, lat DOUBLE, lng DOUBLE"
            return self.spark.createDataFrame([], schema)
        return self.spark.read.parquet(path)
