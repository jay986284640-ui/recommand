"""数据保存模块"""

#  Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

import os

from pyspark.sql import DataFrame


class DataSaver:
    """数据保存器"""

    def __init__(self, output_dir: str, output_format: str = "json"):
        self.output_dir = output_dir
        self.output_format = output_format

    def save(self, reviews_df: DataFrame, meta_df: DataFrame):
        """保存清洗后的数据"""
        print("\n" + "=" * 60)
        print("保存结果")
        print("=" * 60)

        os.makedirs(self.output_dir, exist_ok=True)

        review_output = os.path.join(self.output_dir, "reviews_cleaned")
        meta_output = os.path.join(self.output_dir, "meta_cleaned")

        if self.output_format == "json":
            reviews_df.coalesce(1).write.mode("overwrite").json(review_output)
            meta_df.coalesce(1).write.mode("overwrite").json(meta_output)
        elif self.output_format == "parquet":
            reviews_df.write.mode("overwrite").parquet(review_output)
            meta_df.write.mode("overwrite").parquet(meta_output)
        elif self.output_format == "csv":
            reviews_df.coalesce(1).write.mode("overwrite").option("header", "true").csv(review_output)
            meta_df.coalesce(1).write.mode("overwrite").option("header", "true").csv(meta_output)

        print(f"   评论数据: {review_output}")
        print(f"   元数据: {meta_output}")
