"""兴业生活 - 美团门店券推荐数据适配器(CSV 版)

与 ``xingye_coupon``(Hive 直读)保持相同的标准中间格式,但数据来源改为
``profile_extract.sql`` 落盘的两份 CSV:

- item_profile.csv       门店/券画像(~3000 行)
    列: item_id, item_nm, type, city_nm, cnty_nm, lon, lat, cat_nm1
- user_seq.csv           用户行为序列(~150w+ 行)
    列: custref_no, event, event_time, item_id, lat, lon, event_duration, btn_nm, cls_info

关键数据事实(决定 action 建模):
- event 仅两种取值:showPage(曝光/浏览)、Click(点击)。
- Click 的真实行为由 btn_nm 决定(收藏/领取/购买/查看详情…);
  因此 "漏斗动作" 需从 (event, btn_nm) 派生,而非单看 event。
- event_duration / cls_info 全为空,仅保留字段,不参与建模、不透传。

本适配器为 "运营行为排查" 而生,除标准四列 user_id/item_id/timestamp/action
外,额外透传排查所需列:event(原始)、btn_nm、user_lat、user_lon。
门店画像的经纬度重命名为 item_lon/item_lat,避免与用户经纬度冲突。

注意:本文件为纯新增,不改动既有 ``xingye_coupon``(Hive)与美团门店相关逻辑。
"""

from typing import Optional

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseDataSource
from .factory import register_adapter


@register_adapter("xingye_coupon_csv")
class XingyeCouponCsvAdapter(BaseDataSource):
    """兴业生活(美团门店券)CSV 适配器

    配置项(adapter_config):
        items_path:            门店画像 CSV 路径(必填)
        interactions_path:     用户行为序列 CSV 路径(必填)
        time_format:           event_time 格式,s(秒)/ ms(毫秒)/ datetime(默认 s)
        item_id_column:        门店表 item_id 列名(默认 item_id)
        item_name_column:      门店表名称列名(默认 item_nm)
        interaction_user_column:  交互表 user_id 列名(默认 custref_no)
        interaction_item_column:  交互表 item_id 列名(默认 item_id)
        interaction_time_column:  交互表时间列名(默认 event_time)
        impression_event:      曝光事件名(默认 showPage)→ 映射为 action=impression
        click_event:           点击事件名(默认 Click)
        btn_action_mapping:    Click 时 btn_nm→action 的映射字典(EDA 后填);
                               未命中时落 default_click_action。
        default_click_action:  Click 且 btn_nm 未命中映射时的兜底 action(默认 click)
    """

    def __init__(self, spark, config: dict):
        super().__init__(spark, config)
        self.items_path: str = self.config.get("items_path")
        self.interactions_path: str = self.config.get("interactions_path")
        self.time_format: str = str(self.config.get("time_format", "s")).lower()

        self.item_id_column: str = self.config.get("item_id_column", "item_id")
        self.item_name_column: str = self.config.get("item_name_column", "item_nm")

        self.interaction_user_column: str = self.config.get(
            "interaction_user_column", "custref_no"
        )
        self.interaction_item_column: str = self.config.get(
            "interaction_item_column", "item_id"
        )
        self.interaction_time_column: str = self.config.get(
            "interaction_time_column", "event_time"
        )

        self.impression_event: str = self.config.get("impression_event", "showPage")
        self.click_event: str = self.config.get("click_event", "Click")
        self.btn_action_mapping: dict = self.config.get("btn_action_mapping") or {}
        self.default_click_action: str = self.config.get("default_click_action", "click")

    # ------------------------------------------------------------------ utils

    def _read_csv(self, path: str) -> DataFrame:
        if not path:
            raise ValueError("CSV 路径未配置(items_path / interactions_path)")
        return self.spark.read.option("header", "true").csv(path)

    def _convert_timestamp(self, col):
        """把时间列统一转成 unix 秒级 LongType。"""
        if self.time_format == "s":
            return col.cast("long")
        if self.time_format == "datetime":
            return F.unix_timestamp(F.to_timestamp(col), "yyyy-MM-dd HH:mm:ss")
        # ms(或自动):大于 1e12 视为毫秒
        ts_long = col.cast("long")
        return F.when(ts_long > F.lit(10 ** 12), ts_long / F.lit(1000)).otherwise(
            ts_long
        ).cast("long")

    def _build_action(self) -> "pyspark.sql.Column":
        """由 (event, btn_nm) 派生标准 action。

        - event == impression_event(showPage) → impression
        - event == click_event(Click)         → btn_action_mapping[btn_nm],
                                                 未命中落 default_click_action
        - 其它                                → lower(event) 兜底透传
        """
        # Click 分支:先按 btn_nm 映射
        click_expr = F.lit(self.default_click_action)
        for btn, act in self.btn_action_mapping.items():
            click_expr = F.when(F.col("btn_nm") == F.lit(btn), F.lit(act)).otherwise(
                click_expr
            )

        return (
            F.when(F.col("event") == F.lit(self.impression_event), F.lit("impression"))
            .when(F.col("event") == F.lit(self.click_event), click_expr)
            .otherwise(F.lower(F.col("event")))
        )

    # ------------------------------------------------------------------ users

    def load_users(self) -> DataFrame:
        """无独立用户画像文件,从交互序列派生去重 user_id。"""
        interactions = self.get_interactions()
        return interactions.select("user_id").dropDuplicates(["user_id"])

    # ------------------------------------------------------------------ items

    def load_items(self) -> DataFrame:
        """加载门店/券画像。item_id 规范化,经纬度→item_lon/item_lat。"""
        df = self._read_csv(self.items_path)

        item_col = self.item_id_column
        if item_col not in df.columns:
            raise ValueError(
                f"门店表 {self.items_path} 缺少 item_id 列 '{item_col}',实际列: {df.columns}"
            )

        result = df.withColumn("item_id", F.trim(F.col(item_col)).cast("string"))

        if self.item_name_column in result.columns:
            result = result.withColumnRenamed(self.item_name_column, "item_title")
        if "item_title" not in result.columns:
            result = result.withColumn("item_title", F.lit("").cast("string"))
        if "item_description" not in result.columns:
            result = result.withColumn("item_description", F.lit("").cast("string"))

        # 门店经纬度重命名,避免与用户经纬度冲突;转 double
        if "lon" in result.columns:
            result = result.withColumn("item_lon", F.col("lon").cast("double")).drop("lon")
        if "lat" in result.columns:
            result = result.withColumn("item_lat", F.col("lat").cast("double")).drop("lat")

        return result.dropDuplicates(["item_id"])

    # ------------------------------------------------------------ interactions

    def load_interactions(self) -> DataFrame:
        """加载用户行为序列,派生标准四列 + 透传排查列。"""
        df = self._read_csv(self.interactions_path)

        user_col = self.interaction_user_column
        item_col = self.interaction_item_column
        time_col = self.interaction_time_column

        missing = [c for c in (user_col, item_col, time_col) if c not in df.columns]
        if missing:
            raise ValueError(
                f"交互表 {self.interactions_path} 缺少必需列 {missing},实际列: {df.columns}"
            )

        has_event = "event" in df.columns
        has_btn = "btn_nm" in df.columns

        # 统一 btn_nm/event 存在性,便于 _build_action 引用
        if not has_btn:
            df = df.withColumn("btn_nm", F.lit(None).cast("string"))
        if not has_event:
            df = df.withColumn("event", F.lit("showPage").cast("string"))

        result = df.select(
            F.trim(F.col(user_col)).cast("string").alias("user_id"),
            F.trim(F.col(item_col)).cast("string").alias("item_id"),
            self._convert_timestamp(F.col(time_col)).alias("timestamp"),
            F.col("event").cast("string").alias("event"),
            F.col("btn_nm").cast("string").alias("btn_nm"),
            (F.col("lat").cast("double") if "lat" in df.columns else F.lit(None).cast("double")).alias("user_lat"),
            (F.col("lon").cast("double") if "lon" in df.columns else F.lit(None).cast("double")).alias("user_lon"),
        )

        result = result.withColumn("action", self._build_action())

        # 过滤空主键
        result = result.filter(
            F.col("user_id").isNotNull()
            & (F.col("user_id") != "")
            & F.col("item_id").isNotNull()
            & (F.col("item_id") != "")
            & F.col("timestamp").isNotNull()
        )

        return result

    # ------------------------------------------------------------ co-occurrence

    def load_co_occurrence(self) -> Optional[DataFrame]:
        """排查场景不需要共现,返回 None。"""
        return None

    # ------------------------------------------------------------ validate

    def validate_config(self) -> None:
        if not self.items_path or not self.interactions_path:
            raise ValueError(
                "xingye_coupon_csv 需要配置 items_path 与 interactions_path"
            )
