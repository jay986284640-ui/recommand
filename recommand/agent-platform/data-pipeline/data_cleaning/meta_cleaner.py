"""元数据清洗模块"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


class MetaCleaner:
    """元数据清洗器"""

    def __init__(self):
        pass

    def clean(self, meta_df: DataFrame, reviews_df: DataFrame) -> DataFrame:
        """
        清洗元数据：只保留评论中存在的商品，并清理 also_buy/also_view

        Args:
            meta_df: 元数据DataFrame
            reviews_df: 清洗后的评论DataFrame

        Returns:
            清洗后的元数据DataFrame
        """
        print("\n" + "=" * 60)
        print("步骤9: 清洗 Meta 数据")
        print("=" * 60)

        # 获取清洗后评论中的有效商品 ID
        valid_products = reviews_df.select("product_id").distinct()

        before_count = meta_df.count()
        print(f"   清洗前商品数: {before_count:,}")

        # 过滤元数据：只保留有效商品（使用广播 join）
        meta_cleaned = meta_df.join(F.broadcast(valid_products), "product_id", "inner")

        # 清理 also_buy 中无效的商品
        if "also_buy" in meta_cleaned.columns:
            meta_cleaned = self._filter_also_field(meta_cleaned, "also_buy", valid_products)

        # 清理 also_view 中无效的商品
        if "also_view" in meta_cleaned.columns:
            meta_cleaned = self._filter_also_field(meta_cleaned, "also_view", valid_products)

        after_count = meta_cleaned.count()
        removed_count = before_count - after_count

        print(f"   清洗后商品数: {after_count:,}")
        print(f"   移除无效商品: {removed_count:,} ({removed_count / before_count * 100:.2f}%)")

        return meta_cleaned

    def _filter_also_field(self, df: DataFrame, field_name: str, valid_products: DataFrame) -> DataFrame:
        """
        使用 broadcast join 过滤 also_buy/also_view 字段

        步骤：
        1. explode 将数组展开为多行
        2. 与 valid_products 进行 inner join 过滤
        3. 使用 collect_list 重新聚合为数组
        """
        # 记录原始列
        original_columns = df.columns

        # 展开数组
        exploded = df.select("product_id", F.explode(F.col(field_name)).alias("also_item"))

        # 与有效商品进行 inner join 过滤
        valid_products_renamed = valid_products.withColumnRenamed("product_id", "also_item")
        filtered = exploded.join(F.broadcast(valid_products_renamed), "also_item", "inner")

        # 重新聚合为数组
        filtered_agg = filtered.groupBy("product_id").agg(
            F.collect_list("also_item").alias(field_name)
        )

        # 与原数据合并
        result = df.drop(field_name).join(filtered_agg, "product_id", "left")

        # 调整列顺序，保持与原始一致
        return result.select(*original_columns)
