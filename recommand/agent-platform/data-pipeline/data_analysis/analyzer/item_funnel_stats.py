#!/usr/bin/env python3
"""检测器 - 券漏斗异常

event 仅 showPage(曝光)/ Click(点击),Click 的真实行为在 btn_nm。
adapter 已把 (event, btn_nm) 派生成标准 action(showPage→impression;
Click→btn_nm 映射或 click)。本检测器按 item 透视各 action 计数,计算
点击率(CTR = 非曝光交互 / 曝光),对全局基线做 z-score,标记漏斗畸形商品:
- 大曝光但 CTR 显著高于基线(z 高)或超过硬上限 → 疑似刷点击/领取
- 有大量点击却几乎无曝光 → 数据异常/运营灌入

funnel_actions 可配置(EDA 拿到 btn_nm 词表后补 favorite/receive/buy 等),
用显式列表 pivot 保证输出列稳定。
"""

from typing import Optional, List

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from .base import BaseAnalyzer
from .factory import AnalyzerFactory


class ItemFunnelStatsAnalyzer(BaseAnalyzer):
    """券漏斗异常分析器"""

    @property
    def name(self) -> str:
        return "券漏斗异常(曝光/点击/领取/购买 转化)"

    @property
    def output_file(self) -> str:
        return "item_funnel_stats"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        funnel_actions: List[str] = list(
            self.config.get("funnel_actions", ["impression", "click"])
        )
        if "impression" not in funnel_actions:
            funnel_actions = ["impression"] + funnel_actions
        min_impressions = int(self.config.get("min_impressions", 200))
        ctr_z_threshold = float(self.config.get("ctr_z_threshold", 3.0))
        ctr_hard_cap = float(self.config.get("ctr_hard_cap", 1.0))

        # 显式列表 pivot,列稳定;缺失动作填 0
        pivoted = (
            reviews_df.groupBy("item_id")
            .pivot("action", funnel_actions)
            .count()
            .na.fill(0)
        )

        total_col = F.lit(0)
        for a in funnel_actions:
            total_col = total_col + F.col(a)
        pivoted = pivoted.withColumn("total", total_col)

        impressions = F.col("impression")
        non_impression = F.col("total") - impressions
        pivoted = pivoted.withColumn("clicks", non_impression).withColumn(
            "ctr",
            F.when(impressions > 0, non_impression / impressions).otherwise(F.lit(None)),
        )

        # 全局 CTR 基线(仅统计曝光量达标的商品)
        eligible = pivoted.filter(F.col("impression") >= F.lit(min_impressions))
        stats = eligible.agg(
            F.avg("ctr").alias("mean_ctr"),
            F.stddev("ctr").alias("std_ctr"),
        ).first()
        mean_ctr = float(stats["mean_ctr"] or 0.0)
        std_ctr = float(stats["std_ctr"] or 0.0)

        if std_ctr > 0:
            ctr_z = (F.col("ctr") - F.lit(mean_ctr)) / F.lit(std_ctr)
        else:
            ctr_z = F.lit(0.0)
        pivoted = pivoted.withColumn("ctr_z", ctr_z)

        pivoted = pivoted.withColumn(
            "flag_funnel",
            (
                (F.col("impression") >= F.lit(min_impressions))
                & (
                    (F.col("ctr_z") >= F.lit(ctr_z_threshold))
                    | (F.col("ctr") >= F.lit(ctr_hard_cap))
                )
            )
            | (
                (F.col("impression") < F.lit(min_impressions))
                & (F.col("clicks") >= F.lit(min_impressions))
            ),
        ).na.fill({"flag_funnel": False})

        return pivoted.orderBy(F.desc("total"))


AnalyzerFactory.register("item_funnel_stats", ItemFunnelStatsAnalyzer)
