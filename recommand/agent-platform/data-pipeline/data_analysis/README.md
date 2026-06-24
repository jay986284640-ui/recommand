# Amazon 评论数据分析系统

基于 PySpark 的 Amazon 商品评论数据分析工具，支持本地和集群模式运行。

## 功能概述

### 基础分析 (8项)

| 序号 | 功能 | 说明 |
|------|------|------|
| 1 | 用户评论数量统计 | 统计每个用户发表的评论数量 |
| 2 | 商品评论数量统计 | 统计每个商品的评论数量 |
| 3 | 商品评分统计 | 每个商品的最高分、最低分、中位数、平均分 |
| 4 | 评分时间趋势 | 评分随时间变化的情况 |
| 5 | 评分分布 | 商品平均分分布 (0.5分桶) |
| 6 | 评论长度统计 | 评论文本长度统计 |
| 7 | 标题长度统计 | 评论标题长度统计 |
| 8 | 空值占比 | 各字段空值占比统计 |

### 深度分析 (10项)

| 序号 | 功能 | 说明 |
|------|------|------|
| 10.1 | 验证购买对比 | Verified Purchase vs 非验证购买的评分差异 |
| 10.2 | 首次评论对比 | 用户首次评论 vs 后续评论的评分对比 |
| 10.3 | 星期分布 | 评分按星期分布 (工作日 vs 周末) |
| 10.4 | 长度与评分 | 评论长度与评分的相关性分析 |
| 10.5 | 两极分化 | 1星和5星评论占比分析 |
| 10.6 | 长尾分布 | 商品评论数的长尾分布 |
| 10.7 | 用户评分趋势 | 用户第N条评论的评分变化 |
| 10.8 | Helpfulness | 有用投票分布分析 |
| 10.9 | 热门对比 | 热门商品 vs 冷门商品的评分对比 |
| 10.10 | 月度分布 | 评分分布随时间变化 |

## 项目结构

```
amazon_analysis/
├── config.yaml                 # 配置文件
├── main.py                     # 主程序入口
├── spark_manager.py            # Spark 会话管理器
├── __init__.py
├── analyzer/                   # 分析器模块
│   ├── __init__.py
│   ├── base.py                 # 基础分析器类 (抽象基类)
│   ├── factory.py              # 分析器工厂 (注册机制)
│   ├── user_review_count.py    # 用户评论数量分析器
│   ├── product_review_count.py # 商品评论数量分析器
│   ├── product_rating_stats.py # 商品评分统计分析器
│   ├── rating_by_time.py       # 评分时间变化分析器
│   ├── rating_distribution.py  # 评分分布分析器
│   ├── review_length_stats.py  # 评论长度统计分析器
│   ├── title_length_stats.py   # 标题长度统计分析器
│   ├── null_statistics.py      # 空值占比统计分析器
│   ├── verified_purchase.py    # 验证购买对比分析器
│   ├── first_vs_subsequent.py  # 首次/后续评论分析器
│   ├── weekday_rating.py       # 星期评分分析器
│   ├── length_by_rating.py     # 长度与评分分析器
│   ├── rating_polarization.py  # 两极分化分析器
│   ├── product_review_tail.py  # 长尾分布分析器
│   ├── user_rating_trend.py    # 用户评分趋势分析器
│   ├── helpful_vote.py         # Helpfulness 分析器
│   ├── popularity_comparison.py# 热门/冷门对比分析器
│   └── monthly_rating_distribution.py # 月度评分分布分析器
└── config/
    └── config_loader.py        # 配置加载器
```

## 环境要求

- Python 3.8+
- Java 8+ (建议 Java 11)
- PySpark 3.5.3
- PyYAML

## 安装依赖

```bash
pip install pyspark==3.5.3 pyyaml
```

## 使用方法

### 本地模式运行 (默认)

```bash
cd /opt/recommand/amazon_analysis
python3 main.py
```

### 集群模式运行

```bash
python3 main.py --mode cluster --master spark://master:7077
```

### 指定配置文件

```bash
python3 main.py --config /path/to/custom_config.yaml
```

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--config` / `-c` | 配置文件路径 | config.yaml |
| `--mode` / `-m` | 运行模式 (local/cluster) | local |
| `--master` | Spark master 地址 | local[*] |

## 配置文件说明

```yaml
# Spark 配置
spark:
  mode: local                    # 运行模式: local | cluster
  master: spark://master:7077   # 集群地址 (cluster模式使用)
  app_name: Amazon_Analysis      # 应用名称
  driver_memory: 4g              # Driver 内存
  executor_instances: 2          # Executor 数量 (cluster)
  executor_memory: 2g            # Executor 内存 (cluster)
  shuffle_partitions: 8          # Shuffle 分区数

# 数据路径配置
data:
  review_file: ../data/All_Beauty_sample_1000.jsonl  # 评论数据
  meta_file: ../data/meta_All_Beauty_sample_1000.jsonl # 元数据
  output_dir: ../output  # 输出目录

# 分析配置
analysis:
  basic_analysis:
    - user_review_count
    - product_review_count
    - product_rating_stats
    - rating_by_time
    - rating_distribution
    - review_length_stats
    - title_length_stats
    - null_statistics
  deep_analysis:
    - verified_purchase_comparison
    - first_vs_subsequent_review
    # ... 更多分析器

# 可视化配置
visualization:
  enabled: true
  dpi: 150
  style: seaborn-v0_8-whitegrid

# 日志配置
logging:
  level: WARN
```

## 添加新的分析器

### 步骤 1: 创建分析器文件

在 `analyzer/` 目录下创建新的分析器文件，例如 `my_analyzer.py`:

```python
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from typing import Optional
from .base import BaseAnalyzer


class MyAnalyzer(BaseAnalyzer):
    """我的自定义分析器"""

    @property
    def name(self) -> str:
        return "[自定义] 我的分析器"

    @property
    def output_file(self) -> str:
        return "my_custom_analysis"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        # 在这里编写分析逻辑
        return reviews_df.groupBy("some_column").agg(
            F.count("*").alias("count")
        )


# 注册到工厂 (重要!)
from analyzer.factory import AnalyzerFactory
AnalyzerFactory.register('my_analyzer', MyAnalyzer)
```

### 步骤 2: 在配置文件中启用

在 `config.yaml` 的 `analysis` 部分添加分析器名称:

```yaml
analysis:
  basic_analysis:
    - my_analyzer  # 添加这一行
```

### 步骤 3: 运行测试

```bash
python3 main.py
```

## 代码编写注意事项

### 1. 分析器基类使用

所有分析器必须继承 `BaseAnalyzer` 并实现以下属性和方法:

```python
from analyzer.base import BaseAnalyzer

class MyAnalyzer(BaseAnalyzer):
    @property
    def name(self) -> str:
        """分析器名称，用于日志输出"""
        return "分析器名称"

    @property
    def output_file(self) -> str:
        """输出文件名 (不含.csv后缀)"""
        return "output_filename"

    def analyze(self, reviews_df: DataFrame, meta_df: Optional[DataFrame] = None) -> DataFrame:
        """执行分析逻辑"""
        # 返回分析结果 DataFrame
        return result_df
```

### 2. Spark 版本兼容性

- 本项目使用 **PySpark 3.5.3**
- 注意函数命名差异:
  - PySpark 4.x: `F.percentile_approx()`
  - PySpark 3.x: `F.expr("approx_percentile(...)")`

```python
# 正确写法 (兼容 3.x)
F.expr("approx_percentile(rating, 0.5)").alias("median_rating")

# 错误写法 (PySpark 4.x 语法)
F.percentile_approx("rating", 0.5)
```

### 3. 数组排序问题

避免在 Spark SQL 中使用 Python 列表作为 `array_position` 参数:

```python
# 错误写法
weekday_order = ["Monday", "Tuesday", ...]
F.expr(f"array_position({weekday_order}, review_weekday)")

# 正确写法: 使用 case when
F.when(F.col("review_weekday") == "Monday", 1) \
 .when(F.col("review_weekday") == "Tuesday", 2) \
 ...
```

### 4. approx_percentile 调用

`approx_percentile` 是聚合函数，不能直接在 DataFrame 上调用:

```python
# 错误写法
median_reviews = product_counts.approx_percentile("review_count", 0.5)

# 正确写法
median_reviews = product_counts.agg(F.approx_percentile("review_count", 0.5)).collect()[0][0]
```

### 5. 空值处理

日期字段可能为空，绘图时需过滤:

```python
pandas_weekday = weekday_rating.toPandas()
pandas_weekday_clean = pandas_weekday[
    pandas_weekday['review_weekday'].notna() &
    (pandas_weekday['review_weekday'] != 'NULL')
]
```

### 6. Spark Session 管理

使用单例模式管理 SparkSession:

```python
from analyzer.spark_manager import SparkManager

# 创建会话
spark_manager = SparkManager()
spark = spark_manager.create_session(config)

# 关闭会话
spark_manager.stop()
```

### 7. DataFrame Mixin

使用 `DataFrameMixin` 添加常用衍生字段:

```python
from analyzer.base import DataFrameMixin

mixin = DataFrameMixin()
reviews_df = mixin.add_derived_columns(reviews_df)
```

添加的字段包括:
- `review_date` - 评论日期
- `review_year_month` - 年月
- `review_weekday` - 星期
- `review_text_length` - 评论长度
- `review_title_length` - 标题长度
- `is_verified` - 是否验证购买

## 输出文件

分析结果保存在 `output_dir` 指定的目录下:

```
output/
├── 1_user_review_count.csv
├── 2_product_review_count.csv
├── 3_product_rating_stats.csv
├── 4_rating_by_time.csv
├── 5_rating_distribution.csv
├── 6_review_length_stats.csv
├── 7_title_length_stats.csv
├── 8_null_statistics.csv
├── 10_verified_purchase_comparison.csv
├── 11_first_vs_subsequent_review.csv
├── 12_weekday_rating.csv
├── 13_length_by_rating.csv
├── 14_rating_polarization.csv
├── 15_product_review_tail.csv
├── 16_user_rating_trend.csv
├── 17_helpful_vote_analysis.csv
├── 18_popularity_rating_comparison.csv
└── 19_monthly_rating_distribution.csv
```

## 常见问题

### Q: Java 版本不兼容

**问题**: PySpark 4.x 需要 Java 11+，但系统只有 Java 8

**解决**: 安装 PySpark 3.5.3
```bash
pip install pyspark==3.5.3
```

### Q: JAVA_HOME 未设置

**解决**: 在运行前执行:
```bash
source /etc/profile
export JAVA_HOME=$(dirname $(dirname $(readlink -f $(which java))))
```

### Q: 时间字段为空

**原因**: 样本数据的 timestamp 字段为空

**解决**: 使用完整数据集进行分析

## 技术栈

- **数据处理**: Apache Spark 3.5.3 (PySpark)
- **配置管理**: PyYAML
- **数据可视化**: Matplotlib
- **编程语言**: Python 3.8+

## License

MIT License