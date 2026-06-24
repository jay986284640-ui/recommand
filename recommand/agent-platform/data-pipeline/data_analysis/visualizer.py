#!/usr/bin/env python3
"""
可视化生成器 - 生成数据分析图表
"""

import os
from typing import Dict, Any, Optional, List
import pandas as pd
import matplotlib.pyplot as plt
from pyspark.sql import functions as F
import warnings
warnings.filterwarnings('ignore')


class Visualizer:
    """可视化生成器"""

    def __init__(self, config: Dict[str, Any], output_dir: str):
        """
        初始化可视化生成器

        Args:
            config: 可视化配置
            output_dir: 输出目录
        """
        self.config = config
        self.output_dir = output_dir

        # 设置样式
        style = config.get('style', 'seaborn-v0_8-whitegrid')
        plt.style.use(style)

        # 颜色方案
        self.colors = config.get('colors', ['#e74c3c', '#e67e22', '#f1c40f', '#2ecc71', '#3498db'])

    def generate_all(self, spark, reviews_df):
        """生成所有可视化图表"""
        if not self.config.get('enabled', True):
            print("   可视化已禁用")
            return

        print("\n[图表生成] 开始生成可视化...")

        # 转换数据为 Pandas - 直接从 Spark DataFrame 转换
        rating_counts_pd = reviews_df.groupBy("rating").count().orderBy("rating").toPandas()

        user_avg_rating = reviews_df.groupBy("user_id").agg(
            F.avg("rating").alias("avg_rating")
        ).toPandas()

        product_avg_rating = reviews_df.groupBy("parent_asin").agg(
            F.avg("rating").alias("avg_rating")
        ).toPandas()

        review_lengths = reviews_df.select("review_text_length").toPandas()
        title_lengths = reviews_df.select("review_title_length").toPandas()

        # 生成图表
        self._generate_rating_pie(rating_counts_pd)
        self._generate_rating_bar(rating_counts_pd)
        self._generate_user_avg_rating(user_avg_rating)
        self._generate_product_avg_rating(product_avg_rating)
        self._generate_review_length(review_lengths)
        self._generate_title_length(title_lengths)

        print(f"   已生成可视化图表: {self.output_dir}")

    def _generate_rating_pie(self, df: pd.DataFrame):
        """生成评分饼图"""
        fig, ax = plt.subplots(figsize=(8, 8))
        if len(df) > 0:
            explode = [0.05] * len(df)
            wedges, texts, autotexts = ax.pie(
                df['count'],
                labels=[f'{int(r)} Star' for r in df['rating']],
                autopct='%1.1f%%',
                colors=self.colors[:len(df)],
                explode=explode,
                shadow=True,
                startangle=90
            )
            for autotext in autotexts:
                autotext.set_fontsize(11)
                autotext.set_fontweight('bold')
            ax.set_title('Rating Distribution', fontsize=14, fontweight='bold')
        plt.tight_layout()
        fig.savefig(f"{self.output_dir}/chart_rating_pie.png", dpi=150, bbox_inches='tight')
        plt.close(fig)

    def _generate_rating_bar(self, df: pd.DataFrame):
        """生成评分柱状图"""
        fig, ax = plt.subplots(figsize=(10, 6))
        if len(df) > 0:
            total = df['count'].sum()
            percentages = df['count'] / total * 100
            bars = ax.bar(df['rating'].astype(str), df['count'],
                         color=self.colors[:len(df)], edgecolor='white', linewidth=1.5)
            ax.set_xlabel('Rating', fontsize=12)
            ax.set_ylabel('Number of Reviews', fontsize=12)
            ax.set_title('Rating Distribution (1-5 Stars)', fontsize=14, fontweight='bold')
            for bar, pct in zip(bars, percentages):
                height = bar.get_height()
                ax.annotate(f'{pct:.1f}%',
                           xy=(bar.get_x() + bar.get_width() / 2, height),
                           xytext=(0, 3), textcoords="offset points",
                           ha='center', va='bottom', fontsize=10, fontweight='bold')
        plt.tight_layout()
        fig.savefig(f"{self.output_dir}/chart_rating_bar.png", dpi=150, bbox_inches='tight')
        plt.close(fig)

    def _generate_user_avg_rating(self, df: pd.DataFrame):
        """生成用户平均评分分布"""
        fig, ax = plt.subplots(figsize=(12, 6))
        if len(df) > 0:
            ax.hist(df['avg_rating'], bins=20, color='#9b59b6', edgecolor='white', alpha=0.8)
            ax.set_xlabel('Average Rating', fontsize=12)
            ax.set_ylabel('Number of Users', fontsize=12)
            ax.set_title('User Average Rating Distribution', fontsize=14, fontweight='bold')
            ax.axvline(x=df['avg_rating'].mean(), color='red', linestyle='--',
                      label=f'Mean: {df["avg_rating"].mean():.2f}')
            ax.legend()
        plt.tight_layout()
        fig.savefig(f"{self.output_dir}/chart_user_avg_rating.png", dpi=150, bbox_inches='tight')
        plt.close(fig)

    def _generate_product_avg_rating(self, df: pd.DataFrame):
        """生成商品平均评分分布"""
        fig, ax = plt.subplots(figsize=(12, 6))
        if len(df) > 0:
            ax.hist(df['avg_rating'], bins=20, color='#1abc9c', edgecolor='white', alpha=0.8)
            ax.set_xlabel('Average Rating', fontsize=12)
            ax.set_ylabel('Number of Products', fontsize=12)
            ax.set_title('Product Average Rating Distribution', fontsize=14, fontweight='bold')
            ax.axvline(x=df['avg_rating'].mean(), color='red', linestyle='--',
                      label=f'Mean: {df["avg_rating"].mean():.2f}')
            ax.legend()
        plt.tight_layout()
        fig.savefig(f"{self.output_dir}/chart_product_avg_rating.png", dpi=150, bbox_inches='tight')
        plt.close(fig)

    def _generate_review_length(self, df: pd.DataFrame):
        """生成评论长度分布"""
        fig, ax = plt.subplots(figsize=(12, 6))
        if len(df) > 0:
            lengths = df['review_text_length'].dropna()
            if len(lengths) > 0:
                ax.hist(lengths, bins=30, color='#34495e', edgecolor='white', alpha=0.8)
                ax.set_xlabel('Review Text Length (characters)', fontsize=12)
                ax.set_ylabel('Number of Reviews', fontsize=12)
                ax.set_title('Review Length Distribution', fontsize=14, fontweight='bold')
                mean_len = lengths.mean()
                ax.axvline(x=mean_len, color='red', linestyle='--', label=f'Mean: {mean_len:.0f}')
                ax.legend()
        plt.tight_layout()
        fig.savefig(f"{self.output_dir}/chart_review_length.png", dpi=150, bbox_inches='tight')
        plt.close(fig)

    def _generate_title_length(self, df: pd.DataFrame):
        """生成标题长度分布"""
        fig, ax = plt.subplots(figsize=(12, 6))
        if len(df) > 0:
            lengths = df['review_title_length'].dropna()
            if len(lengths) > 0:
                ax.hist(lengths, bins=30, color='#e67e22', edgecolor='white', alpha=0.8)
                ax.set_xlabel('Review Title Length (characters)', fontsize=12)
                ax.set_ylabel('Number of Reviews', fontsize=12)
                ax.set_title('Review Title Length Distribution', fontsize=14, fontweight='bold')
                mean_len = lengths.mean()
                ax.axvline(x=mean_len, color='red', linestyle='--', label=f'Mean: {mean_len:.0f}')
                ax.legend()
        plt.tight_layout()
        fig.savefig(f"{self.output_dir}/chart_title_length.png", dpi=150, bbox_inches='tight')
        plt.close(fig)


def create_visualizer(config: Dict[str, Any], output_dir: str) -> Visualizer:
    """创建可视化生成器"""
    return Visualizer(config, output_dir)