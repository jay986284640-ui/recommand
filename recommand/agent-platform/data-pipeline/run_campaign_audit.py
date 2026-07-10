#!/usr/bin/env python3
"""运营行为排查与清洗 - 驱动脚本

复用 data_analysis 的 BaseAnalyzer/AnalyzerFactory 框架 + adapters 的插件适配器,
对 profile_extract.sql 落盘的 item_profile.csv / user_seq.csv 做:

  1) 定制 CSV adapter 转换为标准交互
  2) 逐个运营行为检测器(单品热度/时间突刺/券漏斗/用户速度/地理)出报告
  3) campaign_scorer 复合打分 → item_flags.csv / user_flags.csv
  4) CampaignFilter 按策略产出清洗后的训练交互 + 汇总 JSON

用法:
  python run_campaign_audit.py --config config/datasets/xingye_coupon_csv.yaml

不改动既有美团(xingye_coupon Hive)与 Amazon 分析逻辑,纯新增。
"""

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

# 保证 data_analysis / processing / adapters 可被导入
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data_analysis"))

from processing.spark_manager import SparkManager  # noqa: E402
from adapters import AdapterFactory  # noqa: E402  触发适配器注册
from data_analysis.analyzer import AnalyzerFactory  # noqa: E402  触发分析器注册
from data_analysis.analyzer import campaign_scorer  # noqa: E402
from processing.filters.campaign_filter import CampaignFilter  # noqa: E402


ITEM_DETECTORS = [
    "item_popularity_anomaly",
    "item_time_burst",
    "item_funnel_stats",
    "geo_mismatch",
]
USER_DETECTORS = ["user_velocity_anomaly"]


def _write_single_csv(df, path):
    df.coalesce(1).write.mode("overwrite").option("header", "true").csv(path)


def main():
    parser = argparse.ArgumentParser(description="运营行为排查与清洗")
    parser.add_argument("--config", "-c", required=True, help="YAML 配置路径")
    parser.add_argument("--output-dir", "-o", default=None, help="覆盖输出目录")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    data_cfg = cfg.get("data", {})
    adapter_name = data_cfg.get("adapter", "xingye_coupon_csv")
    adapter_config = data_cfg.get("adapter_config", {})
    spark_cfg = cfg.get("spark", {})
    detectors_cfg = cfg.get("detectors", {})
    scoring_cfg = cfg.get("scoring", {})
    cleaning_cfg = cfg.get("cleaning", {})

    output_dir = args.output_dir or cfg.get("output", {}).get(
        "dir", "./pipeline_output/campaign_audit"
    )
    os.makedirs(output_dir, exist_ok=True)

    # Spark
    manager = SparkManager(
        app_name="campaign_audit",
        memory=spark_cfg.get("memory", "4g"),
        partitions=spark_cfg.get("partitions", 8),
        master=spark_cfg.get("master", "local[*]"),
    )
    spark = manager.get_session()

    summary = {"detectors": {}, "cleaning": {}}
    try:
        # 1) adapter → 标准交互 + 门店画像
        adapter = AdapterFactory.create(adapter_name, spark, adapter_config)
        adapter.validate_config()
        interactions = adapter.get_interactions().cache()
        items = adapter.get_items().cache()
        total_interactions = interactions.count()
        print(f"交互总数: {total_interactions:,}, 门店数: {items.count():,}")
        summary["total_interactions"] = total_interactions

        # 2) 逐检测器
        item_results = {}
        user_result = None
        for name in ITEM_DETECTORS + USER_DETECTORS:
            det_cfg = detectors_cfg.get(name, {})
            if not det_cfg.get("enabled", True):
                continue
            try:
                analyzer = AnalyzerFactory.create(name, spark, det_cfg, output_dir)
                result = analyzer.run(interactions, items)
                if name in USER_DETECTORS:
                    user_result = result
                else:
                    item_results[name] = result
                summary["detectors"][name] = "ok"
            except Exception as e:  # noqa: BLE001
                print(f"[警告] 检测器 {name} 失败: {e}")
                summary["detectors"][name] = f"failed: {e}"

        # 3) 复合打分 + 打标
        item_flags = campaign_scorer.score_items(
            item_results, min_score=int(scoring_cfg.get("min_score", 1))
        )
        user_flags = campaign_scorer.score_users(user_result)

        if item_flags is not None:
            item_flags = item_flags.cache()
            _write_single_csv(item_flags, f"{output_dir}/item_flags.csv")
            n_camp = item_flags.filter("is_campaign_item").count()
            summary["campaign_items"] = n_camp
            print(f"运营商品命中: {n_camp}")
        if user_flags is not None:
            user_flags = user_flags.cache()
            _write_single_csv(user_flags, f"{output_dir}/user_flags.csv")
            n_bad = user_flags.filter("is_abnormal_user").count()
            summary["abnormal_users"] = n_bad
            print(f"异常用户命中: {n_bad}")

        # 4) 清洗产出训练交互
        if cleaning_cfg.get("enabled", True):
            cf = CampaignFilter(
                item_flags=item_flags,
                user_flags=user_flags,
                drop_campaign_items=cleaning_cfg.get("drop_campaign_items", True),
                drop_abnormal_users=cleaning_cfg.get("drop_abnormal_users", True),
                downsample_campaign_items=cleaning_cfg.get(
                    "downsample_campaign_items", False
                ),
                cap_per_item=int(cleaning_cfg.get("cap_per_item", 500)),
            )
            cleaned = cf.filter(interactions)
            cleaned_count = cleaned.count()
            fmt = cleaning_cfg.get("output_format", "parquet")
            out_path = f"{output_dir}/cleaned_interactions"
            cleaned.write.mode("overwrite").format(fmt).save(out_path)
            summary["cleaning"] = {
                "before": total_interactions,
                "after": cleaned_count,
                "removed": total_interactions - cleaned_count,
                "removed_pct": round(
                    (total_interactions - cleaned_count)
                    / total_interactions
                    * 100,
                    2,
                )
                if total_interactions
                else 0,
                "output": out_path,
                "format": fmt,
            }
            print(
                f"清洗: {total_interactions:,} → {cleaned_count:,} "
                f"(移除 {summary['cleaning']['removed_pct']}%)"
            )

        with open(f"{output_dir}/summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"完成,输出目录: {output_dir}")
    finally:
        manager.stop()


if __name__ == "__main__":
    main()
