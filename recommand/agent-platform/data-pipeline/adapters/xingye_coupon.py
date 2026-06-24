"""兴业生活 - 美团门店券推荐数据适配器

数据源(profile_extract.sql 产出的 3 张派生表):
- {db}.user_profile_recommand    用户画像
- {db}.item_profile              门店画像
- {db}.user_seq_recommand        用户行为序列

通过 Hive 表 spark.table() 直读,转换为标准中间格式
{user_id, item_id, timestamp, action}。

共现数据由 interactions 派生(同用户 30 天内访问过的其它门店)。
"""

from typing import Optional, Dict, Any

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from .base import BaseDataSource
from .factory import register_adapter


# 默认 action 映射(神策事件名 → 标准 action)
DEFAULT_ACTION_MAPPING = {
    "$pageview": "view",
    "page_view": "view",
    "view": "view",
    "$element_click": "click",
    "click": "click",
    "btn_click": "click",
    "$exposure": "impression",
    "exposure": "impression",
    "coupon_receive": "receive",
    "receive": "receive",
    "coupon_use": "use",
    "use": "use",
    "pay": "use",
}


@register_adapter("xingye_coupon")
class XingyeCouponAdapter(BaseDataSource):
    """
    兴业生活(美团门店券)适配器

    配置项(adapter_config):
        hive_database: 派生表所在 Hive 数据库(默认 recommand_workspace)
        users_table: 用户画像表名(默认 user_profile_recommand)
        items_table: 门店画像表名(默认 item_profile)
        interactions_table: 行为序列表名(默认 user_seq_recommand)
        time_format: 时间字段格式,ms(毫秒) / s(秒) / datetime(字符串)(默认 ms)
        action_mapping: 自定义事件→action 映射字典(覆盖默认)
        cooccurrence_enabled: 是否派生共现数据(默认 True)
        cooccurrence_window_days: 同用户共现时间窗(默认 30)
        cooccurrence_min_cooccur: 共现最小次数(默认 2)
        cooccurrence_max_related: 单个 item 最多保留的相关 item 数(默认 50)
        user_id_column: 用户画像表中的 user_id 列名(默认 custref_no)
        item_id_column: 门店画像表中的 item_id 列名(默认 str_id)
        interaction_user_column: 交互表 user_id 列名(默认 custref_no)
        interaction_item_column: 交互表 item_id 列名(默认 shopid)
        interaction_time_column: 交互表时间戳列名(默认 event_time 或 time)
    """

    def __init__(self, spark, config: dict):
        super().__init__(spark, config)
        self.hive_database: str = self.config.get("hive_database", "recommand_workspace")
        self.users_table: str = self.config.get("users_table", "user_profile_recommand")
        self.items_table: str = self.config.get("items_table", "item_profile")
        self.interactions_table: str = self.config.get(
            "interactions_table", "user_seq_recommand"
        )
        self.time_format: str = self.config.get("time_format", "ms").lower()
        self.action_mapping: Dict[str, str] = {
            **DEFAULT_ACTION_MAPPING,
            **(self.config.get("action_mapping") or {}),
        }
        self.cooccurrence_enabled: bool = self.config.get("cooccurrence_enabled", True)
        self.cooccurrence_window_days: int = int(
            self.config.get("cooccurrence_window_days", 30)
        )
        self.cooccurrence_min_cooccur: int = int(
            self.config.get("cooccurrence_min_cooccur", 2)
        )
        self.cooccurrence_max_related: int = int(
            self.config.get("cooccurrence_max_related", 50)
        )
        self.user_id_column: str = self.config.get("user_id_column", "custref_no")
        self.item_id_column: str = self.config.get("item_id_column", "str_id")
        self.interaction_user_column: str = self.config.get(
            "interaction_user_column", "custref_no"
        )
        self.interaction_item_column: str = self.config.get(
            "interaction_item_column", "shopid"
        )
        # 事件表里时间字段可能是 `time`(原始)或 `event_time`(profile_extract.sql 派生别名)
        self.interaction_time_column: str = self.config.get(
            "interaction_time_column", "event_time"
        )

    # ------------------------------------------------------------------ utils

    def _full_table_name(self, table: str) -> str:
        """拼接 db.table,若用户已写 db.table 则不再拼接"""
        if "." in table:
            return table
        return f"{self.hive_database}.{table}"

    def _read_hive(self, table: str) -> DataFrame:
        name = self._full_table_name(table)
        try:
            return self.spark.table(name)
        except Exception as e:
            raise RuntimeError(
                f"读取 Hive 表失败: {name}. "
                f"请确认已 enableHiveSupport() 且 Hive 中存在该表。"
                f"原始异常: {e}"
            ) from e

    # ------------------------------------------------------------------ users

    def load_users(self) -> DataFrame:
        """加载用户画像。custref_no → user_id,附加 age/sex/self_income_round。"""
        df = self._read_hive(self.users_table)

        user_col = self.user_id_column
        if user_col not in df.columns:
            raise ValueError(
                f"用户表 {self._full_table_name(self.users_table)} 缺少 user_id 列 '{user_col}',"
                f"实际列: {df.columns}"
            )

        # 重命名 user_id,其它字段透传
        rename = {user_col: "user_id"}
        result = df.withColumnsRenamed(rename)

        # 标准化 user_id 类型为字符串
        result = result.withColumn("user_id", F.col("user_id").cast("string"))

        # 去重
        result = result.dropDuplicates(["user_id"])

        # 兜底:若 age/sex/self_income_round 缺失则填空
        for col_name in ("age", "sex", "self_income_round"):
            if col_name not in result.columns:
                result = result.withColumn(col_name, F.lit(None).cast("string"))

        return result

    # ------------------------------------------------------------------ items

    def load_items(self) -> DataFrame:
        """加载门店画像。str_id → item_id,str_nm → item_title。"""
        df = self._read_hive(self.items_table)

        item_col = self.item_id_column
        if item_col not in df.columns:
            raise ValueError(
                f"门店表 {self._full_table_name(self.items_table)} 缺少 item_id 列 '{item_col}',"
                f"实际列: {df.columns}"
            )

        result = df.withColumnRenamed(item_col, "item_id")
        result = result.withColumn("item_id", F.col("item_id").cast("string"))

        # 必需列兜底
        if "str_nm" in result.columns and "item_title" not in result.columns:
            result = result.withColumnRenamed("str_nm", "item_title")
        if "item_title" not in result.columns:
            result = result.withColumn("item_title", F.lit("").cast("string"))
        if "item_description" not in result.columns:
            result = result.withColumn("item_description", F.lit("").cast("string"))

        # 去重
        result = result.dropDuplicates(["item_id"])

        return result

    # ------------------------------------------------------------ interactions

    def load_interactions(self) -> DataFrame:
        """加载用户行为序列。time(ms→s)→timestamp,event→action。"""
        df = self._read_hive(self.interactions_table)

        user_col = self.interaction_user_column
        item_col = self.interaction_item_column
        time_col = self._resolve_time_column(df)

        missing = [c for c in (user_col, item_col, time_col) if c not in df.columns]
        if missing:
            raise ValueError(
                f"交互表 {self._full_table_name(self.interactions_table)} 缺少必需列 {missing},"
                f"实际列: {df.columns}"
            )

        # 时间戳转换
        ts_col = self._convert_timestamp(df[time_col])

        # 字段裁剪 + 重命名
        result = df.select(
            F.col(user_col).cast("string").alias("user_id"),
            F.col(item_col).cast("string").alias("item_id"),
            ts_col.alias("timestamp"),
        )

        # action 映射
        result = self._apply_action_mapping(result)

        # 过滤空值
        result = result.filter(
            F.col("user_id").isNotNull()
            & (F.col("user_id") != "")
            & F.col("item_id").isNotNull()
            & (F.col("item_id") != "")
            & F.col("timestamp").isNotNull()
        )

        return result

    def _resolve_time_column(self, df: DataFrame) -> str:
        """解析交互表的时间戳列名,优先用配置项,其次回退到 event_time/time。"""
        candidates = [self.interaction_time_column, "event_time", "time"]
        for c in candidates:
            if c in df.columns:
                return c
        raise ValueError(
            f"交互表 {self._full_table_name(self.interactions_table)} 找不到时间列"
            f"(尝试: {candidates}),实际列: {df.columns}"
        )

    def _convert_timestamp(self, col):
        """根据 time_format 把各种时间列转换为 unix 秒级 LongType 列。

        Args:
            col: pyspark.sql.Column 对象(由 df[col_name] 得到)
        """
        if self.time_format == "s":
            return col.cast("long")

        if self.time_format == "datetime":
            # 字符串日期时间: yyyy-MM-dd HH:mm:ss
            return F.unix_timestamp(F.to_timestamp(col), "yyyy-MM-dd HH:mm:ss")

        # ms(默认): 先尝试 long,若 > 1e12 则按毫秒处理
        ts_long = col.cast("long")
        seconds = F.when(ts_long > F.lit(10**12), ts_long / F.lit(1000)).otherwise(ts_long)
        return seconds.cast("long")

    def _apply_action_mapping(self, df: DataFrame) -> DataFrame:
        """用 action_mapping 把原始 event 列映射到 action;event 列名固定为 'event'。"""
        if "event" not in df.columns:
            return df.withColumn("action", F.lit("view"))

        mapping_expr = F.lit(None).cast("string")
        # 倒序遍历让先匹配的覆盖
        for src, dst in reversed(list(self.action_mapping.items())):
            mapping_expr = F.when(F.col("event") == F.lit(src), F.lit(dst)).otherwise(
                mapping_expr
            )
        # 默认: 透传 event 小写化
        mapping_expr = F.coalesce(
            mapping_expr, F.lower(F.col("event"))
        ).alias("action")

        return df.withColumn("action", mapping_expr)

    # ---------------------------------------------------------- co-occurrence

    def load_co_occurrence(self) -> Optional[DataFrame]:
        """从 interactions 派生共现(同用户窗口期内访问过的其它门店)。

        输出: item_id, related_items(Array[String])
        """
        if not self.cooccurrence_enabled:
            return None

        interactions = self.get_interactions()

        # 时间窗过滤(基于已转换后的 timestamp)
        if self.cooccurrence_window_days > 0:
            max_ts = interactions.agg(F.max("timestamp")).first()[0]
            if max_ts is not None:
                cutoff = max_ts - self.cooccurrence_window_days * 86400
                interactions = interactions.filter(F.col("timestamp") >= F.lit(cutoff))

        # 同一用户按时间排序访问的门店列表(去重)
        user_shops = (
            interactions.select("user_id", "item_id", "timestamp")
            .dropDuplicates(["user_id", "item_id"])
            .orderBy("user_id", "timestamp")
        )

        # 用 window self-join 取同用户其它门店
        # 等价于: 按 user_id 内连接 + 排除自身 + 时间窗
        w = Window.partitionBy("user_id").orderBy("timestamp")
        indexed = user_shops.withColumn("rn", F.row_number().over(w))

        joined = indexed.alias("a").join(
            indexed.alias("b"),
            (F.col("a.user_id") == F.col("b.user_id"))
            & (F.col("a.item_id") != F.col("b.item_id"))
            & (
                F.col("b.timestamp").between(
                    F.col("a.timestamp") - self.cooccurrence_window_days * 86400,
                    F.col("a.timestamp") + self.cooccurrence_window_days * 86400,
                )
            ),
            how="inner",
        )

        # 统计共现次数,过滤低频
        co_counts = (
            joined.groupBy("a.item_id", "b.item_id")
            .agg(F.count("*").alias("co_count"))
            .filter(F.col("co_count") >= self.cooccurrence_min_cooccur)
            .select(
                F.col("a.item_id").cast("string").alias("item_id"),
                F.col("b.item_id").cast("string").alias("related_item"),
            )
        )

        # 聚合成 array + 截断
        co_array = co_counts.groupBy("item_id").agg(
            F.slice(
                F.array_distinct(
                    F.collect_list(F.col("related_item"))
                ),
                1,
                self.cooccurrence_max_related,
            ).alias("related_items")
        )

        # 过滤空数组
        co_array = co_array.filter(F.size("related_items") > 0)

        return co_array

    # ------------------------------------------------------------ validate

    def validate_config(self) -> None:
        """校验配置完整性,失败抛 ValueError。"""
        if not self.hive_database:
            raise ValueError("adapter_config.hive_database 不能为空")
        if not self.users_table:
            raise ValueError("adapter_config.users_table 不能为空")
        if not self.items_table:
            raise ValueError("adapter_config.items_table 不能为空")
        if not self.interactions_table:
            raise ValueError("adapter_config.interactions_table 不能为空")
        if self.time_format not in ("ms", "s", "datetime"):
            raise ValueError(
                f"adapter_config.time_format 取值非法: {self.time_format},"
                f"必须是 ms / s / datetime"
            )