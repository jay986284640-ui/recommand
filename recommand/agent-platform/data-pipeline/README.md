# 推荐数据处理工具

一套基于 Apache Spark 的通用推荐数据集治理工具，用于处理、清洗、标准化推荐系统数据。

## 功能概述

| 模块 | 功能 |
|------|------|
| **adapters** | 数据适配器，将异构数据源（Amazon、TikTok、Taobao等）转换为标准中间格式 |
| **processing** | 数据处理流程，包含清洗、标准化、序列构建 |
| **data_analysis** | 数据分析与可视化，支持多种分析器 |

## 数据流程

```
原始数据 -> Adapter (适配器) -> 中间格式 -> Pipeline (处理流程) -> 标准格式输出
                                                            │
                                                            ├─ users.json
                                                            ├─ items.json
                                                            ├─ interactions.json
                                                            ├─ user_sequences.json
                                                            └─ co_occurrence.json
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirments.txt
```

### 2. 运行适配器（将原始数据转换为中间格式）

```bash
python run_adapter.py --config config/datasets/amazon.yaml
```

或指定参数：

```bash
python run_adapter.py \
    --adapter amazon \
    --review-input /path/to/reviews.json \
    --meta-input /path/to/meta.json \
    --output ./intermediate
```

### 3. 运行数据处理管道（清洗、标准化、构建序列）

```bash
python run_pipeline.py --config config/datasets/amazon.yaml
```

或从中间格式处理：

```bash
python run_pipeline.py --input ./intermediate --output ./output
```

### 4. 运行数据分析

```bash
python -m data_analysis.main --config data_analysis/config.yaml
```

### 5. 运行测试

如无安装pytest包，先通过`pip install pytest`安装
```bash
pytest tests/
pytest tests/ --cov=processing --cov-report=term-missing  # 计算代码覆盖率
```

## 项目结构

```
.
├── run_adapter.py           # 适配器入口脚本
├── run_pipeline.py          # 处理流程入口脚本
├── requirments.txt          # 依赖
│
├── adapters/                # 数据适配器
│   ├── base.py              # 适配器基类
│   ├── factory.py           # 适配器工厂
│   └── amazon.py            # Amazon 数据适配器
│
├── processing/              # 数据处理模块
│   ├── config_loader.py     # 配置加载
│   ├── pipeline.py          # 统一处理流程
│   ├── spark_manager.py     # Spark 管理
│   ├── filters/             # 过滤器
│   │   ├── base_filter.py
│   │   ├── field_completeness_filter.py  # 字段完整性
│   │   ├── time_filter.py               # 时间过滤
│   │   ├── kcore_filter.py              # K-core 过滤
│   │   ├── deduplicate_filter.py        # 去重
│   │   ├── burst_review_filter.py       # 突发评论过滤
│   │   ├── rule_filter.py               # 规则过滤
│   │   └── ...
│   ├── normalizers/         # 文本标准化
│   │   ├── base_normalizer.py
│   │   ├── html_normalizer.py
│   │   ├── lowercase_normalizer.py
│   │   ├── regex_replace_normalizer.py
│   │   └── ...
│   └── writers/             # 数据写入
│
├── data_analysis/           # 数据分析模块
│   ├── main.py
│   ├── analyzer/            # 分析器
│   │   ├── rating_distribution.py
│   │   ├── user_review_count.py
│   │   ├── helpful_vote.py
│   │   └── ...
│   └── visualizer.py
│
└── config/
    └── datasets/
        └── amazon.yaml      # Amazon 数据集配置
```

## 配置说明

配置文件使用 YAML 格式，主要包含以下部分：

```yaml
# 数据源
data:
  adapter: amazon_old
  review_input: "/path/to/reviews.json"
  meta_input: "/path/to/meta.json"

# 清洗配置
cleaning:
  field_completeness: true
  required_fields: [user_id, item_id, timestamp]
  product_exists: true
  time: true
  years: 18
  deduplicate: true
  burst_review: true
  kcore: true
  kcore_k: 5

# 文本标准化
normalization:
  enabled: true
  df_config:
    items:
      - normalizer: html_normalizer
        columns: [item_title, item_description]
    interactions:
      - normalizer: html_normalizer
        columns: [review_text]

# 输出配置
output:
  dir: ./output
  format: json

# Spark 配置
spark:
  master: local[*]
  memory: 64g
  partitions: 32
```

## 处理流程

### 1. 数据适配 (Adapter)
- 将不同数据源转换为统一的中间格式
- 输出：users, items, interactions, co_occurrence

### 2. 数据清洗 (Filters)
- 字段完整性过滤
- 商品存在性过滤
- 时间过滤（保留最近 N 年）
- 去重
- 突发评论过滤
- K-core 过滤
- 规则过滤

### 3. 文本标准化 (Normalizers)
- HTML 标签清理
- Unicode 规范化
- 小写转换
- 特殊字符清理
- 正则替换/提取

### 4. 序列构建
- 按用户分组，按时间排序
- 构建用户行为序列

### 5. 数据分析
- 评分分布
- 用户/商品统计
- 有用投票分析
- 时间序列分析
- 等

## 输出格式

处理完成后输出以下文件：

| 文件 | 描述 |
|------|------|
| `users.json` | 用户数据 |
| `items.json` | 物品数据 |
| `interactions.json` | 交互数据 |
| `user_sequences.json` | 用户行为序列 |
| `co_occurrence.json` | 共现数据 |

## 开发

```bash
# 格式化和检查
python -m black .
python -m flake8 .
```