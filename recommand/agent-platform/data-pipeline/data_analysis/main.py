#!/usr/bin/env python3
"""
Amazon 数据分析主程序
支持本地和集群模式运行
"""

import os
import sys
import argparse
from pathlib import Path

# 添加当前目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from config.config_loader import Config
from spark_manager import SparkManager
from analyzer.factory import AnalyzerFactory
from analyzer.base import DataFrameMixin
from data_loader import DataLoader
from visualizer import create_visualizer
from pyspark.sql import functions as F


class AmazonAnalysisApp:
    """Amazon 数据分析应用"""

    def __init__(self, config_path: str = None):
        """
        初始化应用

        Args:
            config_path: 配置文件路径
        """
        # 加载配置
        self.config = Config()
        if config_path:
            self.config.load_from_file(config_path)

        # Spark 配置
        self.spark_config = self.config.get_spark_config()
        self.data_config = self.config.get_data_config()
        self.analysis_config = self.config.get_analysis_config()
        self.viz_config = self.config.get_visualization_config()

        # 输出目录
        self.output_dir = self.data_config.get('output_dir', '/opt/recommand/output')
        os.makedirs(self.output_dir, exist_ok=True)

        # Spark 会话
        self.spark = None
        self.reviews_df = None
        self.meta_df = None

    def init_spark(self):
        """初始化 Spark 会话"""
        print("=" * 60)
        print(f"初始化 Spark (模式: {self.spark_config.get('mode', 'local')})")
        print("=" * 60)

        spark_manager = SparkManager()
        self.spark = spark_manager.create_session(self.spark_config)

    def load_data(self):
        """加载数据"""
        print("\n[1] 加载数据...")

        # 创建数据加载器
        source_type = self.data_config.get('source_type', 'amazon_new')
        print(f"   数据源类型: {source_type}")

        data_loader = DataLoader(self.spark, source_type)

        # 读取数据文件
        review_file = self.data_config.get('review_file')
        meta_file = self.data_config.get('meta_file')

        self.reviews_df = data_loader.load_review_data(review_file)
        self.meta_df = data_loader.load_meta_data(meta_file)

        # 标准化字段名称
        self.reviews_df, self.meta_df = data_loader.normalize_data(self.reviews_df, self.meta_df)

        # 添加衍生字段
        mixin = DataFrameMixin()
        self.reviews_df = mixin.add_derived_columns(self.reviews_df)

        print(f"   评论数据: {self.reviews_df.count()} 条记录")
        print(f"   元数据: {self.meta_df.count()} 条记录")

    def run_basic_analysis(self):
        """运行基础分析"""
        print("\n" + "=" * 60)
        print("开始基础分析...")
        print("=" * 60)

        basic_analyzers = self.analysis_config.get('basic_analysis', [])

        for analyzer_name in basic_analyzers:
            try:
                analyzer = AnalyzerFactory.create(
                    analyzer_name,
                    self.spark,
                    self.spark_config,
                    self.output_dir
                )
                analyzer.run(self.reviews_df, self.meta_df)
            except Exception as e:
                print(f"   [警告] 分析器 {analyzer_name} 执行失败: {e}")

    def run_deep_analysis(self):
        """运行深度分析"""
        print("\n" + "=" * 60)
        print("开始深度数据分析...")
        print("=" * 60)

        deep_analyzers = self.analysis_config.get('deep_analysis', [])

        for analyzer_name in deep_analyzers:
            try:
                analyzer = AnalyzerFactory.create(
                    analyzer_name,
                    self.spark,
                    self.spark_config,
                    self.output_dir
                )
                analyzer.run(self.reviews_df, self.meta_df)
            except Exception as e:
                print(f"   [警告] 分析器 {analyzer_name} 执行失败: {e}")

    def print_summary(self):
        """打印汇总信息"""
        print("\n" + "=" * 60)
        print("【数据汇总】")
        print("=" * 60)

        total_count = self.reviews_df.count() if self.reviews_df else 0
        user_count = self.reviews_df.select("user_id").distinct().count() if self.reviews_df else 0
        product_count = self.reviews_df.select("parent_asin").distinct().count() if self.reviews_df else 0

        print(f"  - 评论总数: {total_count:,}")
        print(f"  - 用户总数: {user_count:,}")
        print(f"  - 商品总数: {product_count:,}")

    def run(self):
        """运行完整分析流程"""
        try:
            # 初始化 Spark
            self.init_spark()

            # 加载数据
            self.load_data()

            # 打印汇总
            self.print_summary()

            # 运行基础分析
            self.run_basic_analysis()

            # 运行深度分析
            self.run_deep_analysis()

            # 生成可视化
            if self.viz_config.get('enabled', True):
                visualizer = create_visualizer(self.viz_config, self.output_dir)
                visualizer.generate_all(self.spark, self.reviews_df)

            print("\n" + "=" * 60)
            print(f"分析完成! 结果已保存至: {self.output_dir}")
            print("=" * 60)

        except Exception as e:
            print(f"Error: {e}")
            raise
        finally:
            self.stop()

    def stop(self):
        """停止 Spark"""
        if self.spark:
            self.spark.stop()
            print("\nSpark 会话已关闭")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Amazon 数据分析')
    parser.add_argument('--config', '-c', type=str, default=None,
                        help='配置文件路径')
    parser.add_argument('--mode', '-m', type=str, choices=['local', 'cluster'], default=None,
                        help='运行模式: local 或 cluster')
    parser.add_argument('--master', type=str, default=None,
                        help='Spark master 地址 (cluster 模式时使用)')
    args = parser.parse_args()

    # 创建应用
    app = AmazonAnalysisApp(config_path=args.config)

    # 如果命令行指定了模式，覆盖配置
    if args.mode:
        app.spark_config['mode'] = args.mode
    if args.master:
        app.spark_config['master'] = args.master

    # 运行
    app.run()


if __name__ == "__main__":
    main()