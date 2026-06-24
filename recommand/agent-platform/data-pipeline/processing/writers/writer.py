"""数据写入器模块"""

import logging
import os
from typing import Optional
from pyspark.sql import DataFrame


logger = logging.getLogger(__name__)


class DataWriter:
    """数据写入器 - 将 DataFrame 写入到不同格式的文件"""

    def __init__(self, output_dir: str, format: str = "json"):
        """
        初始化数据写入器

        Args:
            output_dir: 输出目录
            format: 输出格式，支持 json, parquet, csv
        """
        self.output_dir = output_dir
        self.format = format.lower()

        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)

    def write(self, df: DataFrame, filename: str) -> str:
        """
        写入 DataFrame 到文件

        Args:
            df: 要写入的 DataFrame
            filename: 文件名（不含扩展名）

        Returns:
            写入文件的完整路径
        """
        output_path = os.path.join(self.output_dir, f"{filename}.{self.format}")

        if self.format == "json":
            df.write.mode("overwrite").option("encoding", "utf-8").json(output_path)
        elif self.format == "parquet":
            df.write.mode("overwrite").parquet(output_path)
        elif self.format == "csv":
            df.write.mode("overwrite").csv(output_path, header=True)
        else:
            raise ValueError(f"不支持的输出格式: {self.format}")

        return output_path

    def write_users(self, df: DataFrame) -> str:
        """写入用户数据"""
        logger.info("写入用户数据...")
        return self.write(df, "users")

    def write_items(self, df: DataFrame) -> str:
        """写入物品数据"""
        logger.info("写入物品数据...")
        return self.write(df, "items")

    def write_interactions(self, df: DataFrame) -> str:
        """写入交互数据"""
        logger.info("写入交互数据...")
        return self.write(df, "interactions")

    def write_user_sequences(self, df: DataFrame) -> str:
        """写入用户序列数据"""
        logger.info("写入用户序列数据...")
        return self.write(df, "user_interaction_seq")

    def write_co_occurrence(self, df: DataFrame) -> str:
        """写入共现数据"""
        logger.info("写入共现数据...")
        return self.write(df, "co_occurrence")


class StandardDataWriter:
    """
    标准数据写入器

    按照设计文档的标准输出格式写入数据：
    - users.json: 用户数据
    - items.json: 物品数据
    - interactions.json: 交互数据
    - user_interaction_seq.json: 用户行为序列
    - co_occurrence.json: 共现数据（可选）
    """

    def __init__(self, output_dir: str, format: str = "json"):
        """
        初始化标准数据写入器

        Args:
            output_dir: 输出目录
            format: 输出格式
        """
        self.writer = DataWriter(output_dir, format)

    def write_all(self,
                  users_df: Optional[DataFrame] = None,
                  items_df: Optional[DataFrame] = None,
                  interactions_df: Optional[DataFrame] = None,
                  sequences_df: Optional[DataFrame] = None,
                  co_occurrence_df: Optional[DataFrame] = None):
        """
        写入所有标准数据文件

        Args:
            users_df: 用户数据
            items_df: 物品数据
            interactions_df: 交互数据
            sequences_df: 用户行为序列数据
            co_occurrence_df: 共现数据

        Returns:
            写入文件路径的字典
        """
        results = {}

        if users_df is not None:
            results["users"] = self.writer.write_users(users_df)
            logger.info("用户数据已保存: %s", results['users'])

        if items_df is not None:
            results["items"] = self.writer.write_items(items_df)
            logger.info("物品数据已保存: %s", results['items'])

        if interactions_df is not None:
            results["interactions"] = self.writer.write_interactions(interactions_df)
            logger.info("交互数据已保存: %s", results['interactions'])

        if sequences_df is not None:
            results["user_interaction_seq"] = self.writer.write_user_sequences(sequences_df)
            logger.info("用户序列数据已保存: %s", results['user_interaction_seq'])

        if co_occurrence_df is not None:
            results["co_occurrence"] = self.writer.write_co_occurrence(co_occurrence_df)
            logger.info("共现数据已保存: %s", results['co_occurrence'])

        return results
