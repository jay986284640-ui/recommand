# 优惠推荐 Agent — 离线数据处理管线

本目录是从 `~/recommand_data_process/`(原通用数据集治理工具)改造并入 `agent-platform/` 的
**离线批处理数据管线**,为 [001-promo-recommend-agent](../../specs/001-promo-recommend-agent/spec.md)
的 LP Agent 提供 5 类训练/服务用特征。

## 4 步管线

```
[原始数据] → 适配器(Adapters) → [中间格式] → 数据质量稽核(Audit) → 数据清洗(Cleaning) → 数据标准化(Normalization) → 特征提取(Feature Extraction) → [5 类特征]
```

| 步骤 | 模块 | 输入 | 输出 | 阻塞主流程? |
|------|------|------|------|------------|
| **1. 数据质量稽核** | `audit/` | 中间格式 / 适配器输出 | `audit_report.json`(只读不写) | 否,只生成报告 |
| **2. 数据清洗** | `cleaning/` | 步骤 1 后的中间格式 | 清洗后 users/items/interactions | 是,真正改数据 |
| **3. 数据标准化** | `normalization/` | 步骤 2 后的清洗数据 | 标准化后 users/items/interactions | 是,真正改数据 |
| **4. 特征提取** | `feature_extraction/` | 步骤 3 后的标准化数据 | 5 类特征 parquet | 是,产出最终交付物 |

## 5 类产出特征

| 名称 | 路径字段 | 主要列 | 用途 |
|------|----------|--------|------|
| **商品特征** | `item_features` | item_id, content_type, interaction_count, buyer_count, avg_rating, is_cold | LP Agent 候选召回后的粗排 / 过滤 |
| **用户特征** | `user_features` | user_id, interaction_count, category_pref, content_type_pref, is_new_user | LP Agent 冷启动检测 / 个性化召回 |
| **用户交互历史** | `user_interaction_history` | user_id, sequence[struct], seq_length | LP Agent 长序列召回 / 重排 |
| **共购信息** | `co_purchase` | item_id, co_items[struct<related_item_id, co_count, co_weight>] | LP Agent 联想召回 / I2I 推荐 |
| **曝光日志** | `impression_log` | trace_id, user_id, item_id, position, rank_method, is_click, is_convert | 离线 AUC / 在线学习反馈(stub,待 LP 主流程回流) |

## 适配器(对接 LP Agent content_type 体系)

| 适配器名 | 对齐 content_type | 数据源 |
|----------|-------------------|--------|
| `meituan_coupon` | meituan_coupon | 美团门店券交易系统 |
| `self_operated_coupon` | self_operated_coupon | 自拓展门店券 |
| `local_payment` | local_payment | 本地优惠买单 |
| `external_coupon` | external_coupon | 第三方券源(点评/抖音/京东到家) |
| `amazon_old` / `amazon_new` | (实验用) | Amazon 公开数据集 |
| `netflix` | (实验用) | Netflix 公开数据集 |
| `kuairand` | (实验用) | KuaiRand 公开数据集 |

## 快速开始

```bash
# 一键跑完 4 步
python run_pipeline.py --config configs/datasets/meituan_coupon.yaml \
                       --output-dir ./pipeline_output

# 分步跑
python run_audit.py            --config configs/datasets/meituan_coupon.yaml
python run_cleaning.py         --config configs/datasets/meituan_coupon.yaml --output ./pipeline_output/cleaned
python run_normalization.py    --config configs/datasets/meituan_coupon.yaml --input  ./pipeline_output/cleaned --output ./pipeline_output/normalized
python run_feature_extraction.py --config configs/datasets/meituan_coupon.yaml --input ./pipeline_output/normalized
```

## 与 LP Agent(运行时)的关系

- 运行时:LP Agent 接收对话 → 实时调用 LLM 排序 + ES 召回 + 偏好过滤 → 给出推荐。
- 离线:本管线周期性(月/周)从交易库回流数据 → 产出 5 类特征 → 加载到 ES / Redis / OLAP。
- **数据契约**:
  - `item_features` → ES 索引(供 LP Agent 召回用)
  - `user_features` → Preference Store + 画像服务
  - `user_interaction_history` → ES(序列召回,稀疏存储)
  - `co_purchase` → ES(I2I 索引)
  - `impression_log` → OLAP(待 LP 主流程落盘 conversation_trace 后,做 AUC/转化分析)

## 项目结构

```
agent-platform/data-pipeline/
├── README.md
├── requirements.txt
├── configs/
│   └── datasets/                    # 各数据源 YAML
├── adapters/                        # 异构数据 → 中间格式
│   ├── base.py / factory.py
│   ├── meituan_coupon.py
│   ├── self_operated_coupon.py
│   ├── local_payment.py
│   ├── external_coupon.py
│   └── amazon.py / amazon23.py / netflix.py / kuairand.py
├── audit/                           # 步骤 1: 数据质量稽核
│   ├── metrics.py                   # 纯函数指标
│   ├── reporter.py                  # 写 audit_report.json
│   └── pipeline.py
├── cleaning/                        # 步骤 2: 数据清洗
│   ├── base_filter.py
│   ├── field_completeness_filter.py
│   ├── time_filter.py
│   ├── kcore_filter.py
│   ├── deduplicate_filter.py
│   ├── burst_review_filter.py
│   ├── user_item_dedup_filter.py
│   ├── quality_filter.py
│   ├── product_exists_filter.py
│   ├── rule_filter.py               # 声明式算子
│   ├── outlier_filter.py            # 新增
│   ├── spam_filter.py               # 新增
│   ├── text_length_filter.py        # 新增
│   └── pipeline.py
├── normalization/                   # 步骤 3: 数据标准化
│   ├── base_normalizer.py
│   ├── html_normalizer.py
│   ├── lowercase_normalizer.py
│   ├── special_char_normalizer.py
│   ├── unicode_normalizer.py
│   ├── whitespace_normalizer.py
│   ├── regex_replace_normalizer.py
│   ├── regex_extract_normalizer.py
│   └── pipeline.py
├── feature_extraction/              # 步骤 4: 特征提取
│   ├── item_features.py             # 商品特征
│   ├── user_features.py             # 用户特征
│   ├── user_interaction_history.py  # 用户行为序列
│   ├── co_purchase.py               # 共购信息
│   ├── impression_log.py            # 曝光日志(stub)
│   └── pipeline.py
├── writers/                         # 通用写出器
│   └── feature_writer.py
├── common/                          # 公共模块
│   ├── config_loader.py             # 4 步配置 + 适配器 + Spark
│   ├── spark_manager.py             # 单例 SparkSession
│   └── logging_config.py
├── tests/                           # 单元测试
│   ├── cleaning/                    # 11 个 filter 测试(从 processing/filters 迁)
│   ├── normalization/               # 7 个 normalizer 测试
│   ├── audit/                       # 稽核测试(新增)
│   ├── feature_extraction/          # 5 类特征测试(新增)
│   ├── fixtures/
│   └── conftest.py
├── run_audit.py
├── run_cleaning.py
├── run_normalization.py
├── run_feature_extraction.py
└── run_pipeline.py                  # 一键跑 4 步
```

## 配置示例

YAML 配置文件 (`configs/datasets/meituan_coupon.yaml`):

```yaml
data:
  adapter: meituan_coupon
  adapter_config:
    trade_input: /data/meituan/trade.parquet
    store_input: /data/meituan/store.parquet
    template_input: /data/meituan/template.parquet
    cooccurrence_input: /data/meituan/co_occurrence.parquet

audit:
  enabled: true
  output_dir: ./pipeline_output/audit
  outlier_rules:
    - field: amount
      min: 0
      max: 10000

cleaning:
  field_completeness: true
  required_fields: [user_id, item_id, timestamp]
  product_exists: true
  time: true
  years: 3
  deduplicate: true
  kcore: true
  kcore_k: 5
  burst_review: true
  outlier: true
  spam: true
  text_length: true
  min_text_length: 5

normalization:
  enabled: true
  df_config:
    items:
      - normalizer: html_normalizer
        columns: [item_title, item_description]
      - normalizer: unicode_normalizer
        columns: [item_title]
    interactions:
      - normalizer: whitespace_normalizer
        columns: [review_text]

feature_extraction:
  enabled: true
  output_dir: ./pipeline_output/features
  output_format: parquet
  item_features: true
  user_features: true
  user_interaction_history: true
  co_purchase: true
  impression_log: false       # 暂留空,待 LP 主流程落盘 conversation_trace 后开启
  max_seq_length: 200
  co_purchase_window_days: 30
  new_user_threshold: 3

output:
  dir: ./pipeline_output
  format: parquet

spark:
  master: local[*]
  memory: 4g
  partitions: 8
```

## 测试

```bash
pip install -r requirements.txt pytest
pytest tests/ -v
```

测试覆盖:
- 步骤 2: 11 个 filter 单元测试(沿用旧 processing/filters,导入路径已迁移)
- 步骤 3: 7 个 normalizer 单元测试(沿用旧 processing/normalizers)
- 步骤 1: 5 个 metrics + 1 个 pipeline 测试(新增)
- 步骤 4: 5 类特征提取测试(新增)
- 步骤 2 端到端: 1 个 pipeline 集成测试(新增)
