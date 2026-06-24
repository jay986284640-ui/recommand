"""汇总统计模块"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

import json
import os
from typing import List, Dict, Any

from pyspark.sql import DataFrame


class SummaryGenerator:
    """清洗结果汇总生成器"""

    def __init__(self):
        pass

    def generate(self, cleaned_reviews_df: DataFrame, meta_cleaned_df: DataFrame,
                 original_review_count: int, original_meta_count: int,
                 pipeline_stats: List[Dict[str, Any]] = None,
                 output_path: str = None):
        """
        生成清洗汇总报告

        Args:
            cleaned_reviews_df: 清洗后的评论DataFrame
            meta_cleaned_df: 清洗后的元数据DataFrame
            original_review_count: 原始评论数
            original_meta_count: 原始元数据数
            pipeline_stats: 清洗流程的统计信息
            output_path: 报告输出路径（可选）
        """
        print("\n" + "=" * 60)
        print("数据清洗汇总")
        print("=" * 60)

        final_review_count = cleaned_reviews_df.count()
        final_meta_count = meta_cleaned_df.count()

        print(f"\n   评论数据:")
        print(f"      原始: {original_review_count:,}")
        print(f"      最终: {final_review_count:,}")
        print(f"      保留: {final_review_count / original_review_count * 100:.2f}%")

        print(f"\n   元数据:")
        print(f"      原始: {original_meta_count:,}")
        print(f"      最终: {final_meta_count:,}")
        print(f"      保留: {final_meta_count / original_meta_count * 100:.2f}%")

        user_count = cleaned_reviews_df.select("user_id").distinct().count()
        product_count = cleaned_reviews_df.select("product_id").distinct().count()

        print(f"\n   唯一用户数: {user_count:,}")
        print(f"   唯一商品数: {product_count:,}")

        # 打印每个步骤的详细统计
        if pipeline_stats:
            print("\n" + "-" * 60)
            print("   各步骤过滤详情:")
            print("-" * 60)
            print(f"   {'步骤':<4} {'过滤器':<30} {'移除记录':<15} {'移除率':<10}")
            print("-" * 60)
            for stat in pipeline_stats:
                step = stat["step"]
                name = stat["filter_name"]
                removed = stat["removed_count"]
                rate = stat["removed_rate"]
                print(f"   {step:<4} {name:<30} {removed:<15,} {rate:.2f}%")

        # 保存报告到文件
        if output_path:
            self.save_report(
                output_path=output_path,
                original_review_count=original_review_count,
                final_review_count=final_review_count,
                original_meta_count=original_meta_count,
                final_meta_count=final_meta_count,
                user_count=user_count,
                product_count=product_count,
                pipeline_stats=pipeline_stats
            )

    def save_report(self, output_path: str, original_review_count: int,
                    final_review_count: int, original_meta_count: int,
                    final_meta_count: int, user_count: int, product_count: int,
                    pipeline_stats: List[Dict[str, Any]] = None):
        """保存报告为 JSON 文件"""
        # 构建报告数据
        report = {
            "summary": {
                "original_reviews": original_review_count,
                "final_reviews": final_review_count,
                "reviews_kept_percent": round(final_review_count / original_review_count * 100,
                                              2) if original_review_count > 0 else 0,
                "original_meta": original_meta_count,
                "final_meta": final_meta_count,
                "meta_kept_percent": round(final_meta_count / original_meta_count * 100,
                                           2) if original_meta_count > 0 else 0,
                "unique_users": user_count,
                "unique_products": product_count
            },
            "pipeline_stats": pipeline_stats or []
        }

        # 确保输出目录存在
        os.makedirs(output_path, exist_ok=True)

        # 保存 JSON 文件
        json_path = os.path.join(output_path, "cleaning_report.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n   报告已保存: {json_path}")
