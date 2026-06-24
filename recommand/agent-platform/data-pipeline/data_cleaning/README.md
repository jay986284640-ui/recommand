# 亚马逊数据集数据清洗工具

基于 PySpark 的 Amazon 产品评论数据清洗系统，支持灵活的配置和可扩展的过滤器架构。

## 功能特性

数据清洗流程包含 10 个过滤步骤：

| 步骤 | 过滤器       | 说明                                                       |
|:--:|-----------|----------------------------------------------------------|
| 1  | 字段完整性过滤   | 过滤关键字段（user_id, product_id, review_text, timestamp）为空的记录 |
| 2  | 异常值过滤     | 过滤评分不在 [1, 5] 范围或时间戳异常的记录                                |
| 3  | 数据质量过滤    | 过滤过短文本（默认最小 10 字符）                                       |
| 4  | 垃圾数据过滤    | 过滤广告、链接等垃圾评论                                             |
| 5  | 时间过滤      | 只保留最近 N 年的评论                                             |
| 6  | 文本长度过滤    | 过滤超过最大长度（默认 700 字符）的文本                                   |
| 7  | 去重过滤      | 对 reviewText 完全一致的记录去重                                   |
| 8  | 突发评论过滤    | 过滤短时间内评论次数过多的用户（默认10分钟内>50条）                             |
| 9  | 用户-商品连续去重 | 按时间排序后，相邻的同一用户-商品记录只保留一条（K-core之前）                       |
| 10 | K-core 过滤 | 过滤评论数少于 K 的用户和商品                                         |

此外还包括：

- 元数据同步清洗：只保留评论中存在的商品
- also_buy/also_view 清理：移除不在有效商品列表中的商品

## 安装依赖

```bash
pip install pyspark pyyaml
```

## 快速开始

### 方式一：命令行参数

```bash
cd /opt/recommand/data_cleaning
python data_cleaning.py \
    -ri /path/to/reviews.json \
    -mi /path/to/meta.json \
    -o /path/to/output
```

### 方式二：配置文件

```bash
python data_cleaning.py --config config.yaml
```

### 方式三：配置文件 + 命令行覆盖

```bash
python data_cleaning.py --config config.yaml -o /path/to/output -l 500
```

命令行参数优先级高于配置文件。

## 命令行参数

| 参数               | 简写    | 说明        | 默认值          |
|------------------|-------|-----------|--------------|
| `--config`       | `-c`  | 配置文件路径    | -            |
| `--review-input` | `-ri` | 评论数据输入路径  | -            |
| `--meta-input`   | `-mi` | 元数据输入路径   | -            |
| `--output`       | `-o`  | 输出目录      | -            |
| `--source-type`  | `-s`  | 数据源类型     | `amazon_new` |
| `--max-length`   | `-l`  | 评论文本最大长度  | `700`        |
| `--min-length`   | -     | 评论文本最小长度  | `10`         |
| `--years`        | `-y`  | 保留最近 N 年  | `10`         |
| `--k-core`       | `-k`  | K-core 阈值 | `5`          |
| `--format`       | `-f`  | 输出格式      | `json`       |

## 配置文件

配置文件采用 YAML 格式，默认文件名为 `config.yaml`：

```yaml
# 数据源配置
data:
  review_input: /data/reviews.json
  meta_input: /data/meta.json
  output: /output/cleaned
  source_type: amazon_new   # amazon_new 或 amazon_old

# 清洗参数配置
cleaning:
  field_completeness:
    enabled: true
    required_fields:
      - user_id
      - product_id
      - review_text
      - timestamp

  outlier:
    enabled: true
    min_rating: 1.0
    max_rating: 5.0
    min_year: 1990

  quality:
    enabled: true
    min_text_length: 10

  spam:
    enabled: true
    custom_patterns: [ ]     # 可选：自定义垃圾模式

  time:
    enabled: true
    years: 10

  text_length:
    enabled: true
    max_length: 700

  deduplicate:
    enabled: true
    key_column: review_text

  burst_review:
    enabled: true
    time_window_minutes: 10  # 时间窗口（分钟）
    max_reviews: 50          # 窗口内最大评论数

  user_product_dedup:
    enabled: true            # 用户-商品连续去重（K-core之前）

  kcore:
    enabled: true
    k: 5                     # K-core阈值
    broadcast_threshold: 200000  # 广播阈值，超过此值时不使用广播join

# 输出配置
output:
  format: json              # json | parquet | csv

# Spark配置
spark:
  master: local[*]          # local[*] 或 spark://host:7077
  memory: 4g                # driver内存
  driver_cores: 2           # driver CPU核心数
  executor_cores: 2         # executor CPU核心数（仅cluster模式生效）
  executor_memory: 4g       # executor内存（仅cluster模式生效）
  executor_numbers: 1       # executor数量（仅cluster模式生效）
  partitions: 8             # shuffle分区数
  local_dir: /tmp/spark-tmp # shuffle临时目录
```

## 代码结构

```
data_cleaning/
├── data_cleaning.py           # 主入口
├── config.yaml                # 默认配置文件
├── config_loader.py           # 配置加载模块
├── spark_manager.py           # Spark会话管理（单例模式）
├── data_loader.py             # 数据加载器
├── data_saver.py              # 数据保存器
├── pipeline.py                # 清洗流程管理器
├── meta_cleaner.py            # 元数据清洗器（包含 also_buy/also_view 清理）
├── summary.py                 # 汇总统计生成器
└── filters/                   # 过滤器模块
    ├── __init__.py
    ├── base_filter.py              # 抽象基类
    ├── field_completeness_filter.py
    ├── outlier_filter.py
    ├── quality_filter.py
    ├── spam_filter.py
    ├── time_filter.py
    ├── text_length_filter.py
    ├── deduplicate_filter.py       # reviewText 去重
    ├── user_product_dedup_filter.py # 用户-商品连续去重
    ├── burst_review_filter.py      # 突发评论过滤
    └── kcore_filter.py             # K-core 过滤（支持广播优化）
```

### 核心类说明

| 类名                 | 职责                                       |
|--------------------|------------------------------------------|
| `SparkManager`     | Spark 会话管理（单例模式），支持自定义临时目录               |
| `DataLoader`       | 加载评论和元数据，支持 amazon_new 和 amazon_old 两种格式 |
| `DataSaver`        | 保存清洗结果，支持 json/parquet/csv 格式            |
| `CleaningPipeline` | 管理过滤器执行流程，记录统计信息                         |
| `BaseFilter`       | 过滤器抽象基类                                  |
| `MetaCleaner`      | 清洗元数据，只保留评论中存在的商品，清理 also_buy/also_view  |
| `SummaryGenerator` | 生成清洗汇总报告并保存为 JSON                        |

## 新增过滤器的注意事项

### 1. 创建新的过滤器类

在 `filters/` 目录下创建新的过滤器类，继承 `BaseFilter`：

```python
# filters/my_custom_filter.py
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from .base_filter import BaseFilter


class MyCustomFilter(BaseFilter):
    """自定义过滤器说明"""

    def __init__(self, param1: str = "default"):
        super().__init__("自定义过滤器名称")
        self.param1 = param1

    def filter(self, df: DataFrame) -> DataFrame:
        """实现具体的过滤逻辑"""
        # 在此实现过滤逻辑
        return df.filter(...)
```

### 2. 注册过滤器

在 `filters/__init__.py` 中导出：

```python
from .my_custom_filter import MyCustomFilter

__all__ = [
    ...
    "MyCustomFilter",
]
```

### 3. 在流程中集成

在 `data_cleaning.py` 的 `build_pipeline_from_config` 函数中添加：

```python
# 步骤X: 自定义过滤
if cleaning_config.get('my_custom', {}).get('enabled', True):
    cfg = cleaning_config['my_custom']
    pipeline.add_filter(MyCustomFilter(
        param1=cfg.get('param1', 'default')
    ))
```

### 4. 在配置文件中添加

在 `config.yaml` 中添加配置项：

```yaml
cleaning:
  my_custom:
    enabled: true
    param1: value
```

### 5. 注意事项

- **继承 BaseFilter**：所有过滤器必须继承 `BaseFilter` 并实现 `filter` 方法
- **命名规范**：过滤器类名以 `Filter` 结尾，文件名使用下划线命名
- **配置化**：尽量将参数暴露到构造函数，支持通过配置文件调整
- **日志输出**：`BaseFilter` 的 `filter` 方法会被 `CleaningPipeline` 自动包装日志
- **性能考虑**：避免在过滤器中进行多次 `count()`，珍惜 Spark 的惰性计算
- **线程安全**：Spark DataFrame 是不可变的，过滤器不会产生副作用

## 输出说明

### 数据输出

清洗后的数据保存在输出目录：

```
output/
├── reviews_cleaned/      # 清洗后的评论数据
│   └── part-*.json
├── meta_cleaned/         # 清洗后的元数据
│   └── part-*.json
└── cleaning_report.json  # 清洗报告
```

### 清洗报告 (cleaning_report.json)

```json
{
  "summary": {
    "original_reviews": 51311621,
    "final_reviews": 4556528,
    "reviews_kept_percent": 8.88,
    "original_meta": 1000,
    "final_meta": 800,
    "meta_kept_percent": 80.0,
    "unique_users": 366808,
    "unique_products": 157105
  },
  "pipeline_stats": [
    {
      "step": 1,
      "filter_name": "字段完整性过滤",
      "removed_count": 13825,
      "removed_rate": 0.03
    },
    ...
  ]
}
```

## 内存优化

### K-core 过滤优化

K-core 过滤采用迭代算法，可能产生大量 shuffle。系统提供以下优化：

1. **广播阈值**：当有效用户/商品数量超过阈值时，自动改用 sort-merge join
2. **缓存管理**：每次迭代后释放中间结果，减少内存占用
3. **配置调整**：

```yaml
spark:
  partitions: 4           # 减少 shuffle 分区
  local_dir: /path/to/large/disk  # 使用大磁盘作为临时目录
  memory: 8g              # 增加 driver 内存

kcore:
  broadcast_threshold: 200000  # 调整广播阈值
```

### Spark 临时目录

可配置 `spark.local_dir` 更改 shuffle 临时目录，避免默认 `/tmp` 磁盘空间不足：

```yaml
spark:
  local_dir: /data/spark-tmp  # 确保目录存在且有足够空间
```

## 输出示例

```
============================================================
亚马逊数据集数据清洗
============================================================
评论输入: /data/reviews.json
元数据输入: /data/meta.json
输出目录: /output/cleaned
数据源: amazon_new
已加载默认配置文件: /opt/recommand/data_cleaning/config.yaml

加载数据...
   评论: 51,311,621 条
   元数据: 1,000 条

共 10 个过滤步骤

============================================================
步骤1: 字段完整性过滤
============================================================
   过滤前记录数: 51,311,621
   过滤后记录数: 51,297,796
   移除记录: 13,825 (0.03%)

...

============================================================
步骤10: K-core 过滤 (k=5)
============================================================
   过滤前记录数: 12,259,202

   迭代 1:
      有效用户: 437,218, 有效商品: 345,208
      过滤后: 4,556,528

   迭代 2:
      有效用户: 366,808, 有效商品: 157,105
      过滤后: 3,200,000

============================================================
数据清洗汇总
============================================================

   评论数据:
      原始: 51,311,621
      最终: 3,200,000
      保留: 6.24%

   元数据:
      原始: 1,000
      最终: 800
      保留: 80.00%

   唯一用户数: 366,808
   唯一商品数: 157,105

------------------------------------------------------------
   各步骤过滤详情:
------------------------------------------------------------
   步骤  过滤器                            移除记录            移除率
------------------------------------------------------------
   1     字段完整性过滤                        13,825           0.03%
   ...

============================================================
   报告已保存: /output/cleaned/cleaning_report.json
============================================================
数据清洗完成!
============================================================
```

## 许可证

MIT License