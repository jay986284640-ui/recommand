# 训练数据生成 (兴业 O2O 三品类 SFT 语料) — v2.5.2

**目录**: `agent-platform/training-data/`
**业务对齐**: 兴业银行信用卡 O2O 推荐系统
**数据源**: Hive / CSV / Spark,通过 `configs/tables.yaml` 声明表结构和 LLM 推断字段
**Spec**: v2.5.2 — **配置驱动 LLM 推断** / **表可任意扩展** / OpenAI 兼容 HTTP 客户端

## 3-Stage Pipeline

```
┌──────────────────────────────────────────────────────────┐
│ Stage 1: extract-tags  全量标签抽取                       │
│   LLM 推断 category/taste/cuisine/occasion/consumable_type│
│   avg_prc 从原始列桶化,表字段透传                         │
│   → dim_dictionary_snapshot.yaml (约束集)                 │
│   → item_profile.jsonl (扁平格式)                         │
└───────────────────────┬──────────────────────────────────┘
                        ↓
┌───────────────────────┴──────────────────────────────────┐
│ Stage 2: enrich       实际标注数据                        │
│   字典约束 + reject 可观测                                │
│   → item_tags.jsonl + item_profile.jsonl                 │
└───────────────────────┬──────────────────────────────────┘
                        ↓
┌───────────────────────┴──────────────────────────────────┐
│ Stage 3: sft          合成 SFT 数据                       │
│   → sft_corpus.jsonl + train/val/test.jsonl              │
└──────────────────────────────────────────────────────────┘
```

## 配置文件

### `configs/tables.yaml` — 表声明 + LLM 推断配置

```yaml
_meta:
  llm_inference:                          # 声明哪些字段由 LLM 推断
    - { field: category, desc: 商业品类,如咖啡、快餐, multiple: false }
    - { field: taste,    desc: 口味标签,如甜、辣,     multiple: true  }
    - { field: cuisine,  desc: 菜系,如川菜、日料,     multiple: false }
    - { field: occasion, desc: 消费场景,如早餐、聚会,  multiple: false }
    - { field: consumable_type, desc: 吃或喝,food/drink/mixed, multiple: false }

  field_contract:    # 每种表类型要求提供的列(加载时校验)
    meituan_shop: { required: [id, name, category, price, lng, lat] }

tables:
  - db: recommand_workspace
    name: o2o_new_gut_shop_base_third
    role: meituan_shop
    columns:
      - { name: str_id,  type: VARCHAR, role: id }
      - { name: str_nm,  type: VARCHAR, role: name }
      - { name: cat_nm,  type: VARCHAR, role: category }
      - { name: avg_prc, type: VARCHAR, role: price }
      - { name: lng,     type: VARCHAR, role: lng }
      - { name: lat,     type: VARCHAR, role: lat }
    derived_fields:
      avg_prc: avg_prc                  # 非 LLM: 从原始列桶化
    sensitive: [crt_psn_id, updt_psn_id]
```

**扩展新表**:在 `tables` 下加一条,配 `columns` + `derived_fields`,`_meta.field_contract` 加一行 `role` 即可。**新增推断维度**:在 `_meta.llm_inference` 加一个 `{field, desc, multiple}` 条目,prompt 自动生成。

### `configs/pipeline.yaml` — 运行参数

```yaml
training_data:
  input:
    source: hive               # hive | mock | csv
    item_types: [meituan_shop] # 只跑哪种表
    sample_n_per_type:         # 留空=全量,填数字=采样
  enrichment:
    llm:
      provider: openai_compat
      model: deepseek-chat
      base_url: https://api.deepseek.com/v1
      api_key_env: LLM_API_KEY
      timeout_seconds: 60
      verify_ssl: true
      headers:                 # 自定义 header(可选)
        X-Workspace-Id: "ws-001"
    concurrency: 4             # LLM 并发数
```

## 全部 CLI 子命令

```bash
cd /opt/recommand/recommand/agent-platform/training-data
PYTHONPATH=.

# Stage 1: 全量标签抽取(LLM 推断 + 品牌频次统计)
python3 -m training_data.cli extract-tags \
    --tables-config configs/tables.yaml \
    --source hive --output-dir output/stage1 --frequency-min 1
# → dim_dictionary_snapshot.yaml + brands_diff.yaml

# Stage 2: 实际标注(字典约束)
python3 -m training_data.cli enrich \
    --tables-config configs/tables.yaml --source hive \
    --dict-snapshot output/stage1/dim_dictionary_snapshot.yaml \
    --output-dir output/stage2
# → item_tags.jsonl + item_profile.jsonl

# Stage 3: 合成 SFT 数据
python3 -m training_data.cli sft \
    --input output/stage2/item_tags.jsonl --output-dir output/stage3

# CSV 模式
python3 -m training_data.cli enrich \
    --tables-config configs/tables.yaml --source csv \
    --csv-dir /data/csv --csv-delimiter ',' --output-dir output/

# Jupyter (注入已有 SparkSession)
from training_data.enricher.pipeline import EnrichmentPipeline
from training_data.hive_reader.spark_reader import SparkHiveReader
pipeline = EnrichmentPipeline(
    config=cfg, tables_config_path="configs/tables.yaml",
    hive_reader=SparkHiveReader(spark_session=spark),  # 用 Jupyter 的 spark
    llm_client=llm, output_dir="output/stage2",
    constrain_to_dict=False,  # Stage 1 发散模式
)
```

## 不依赖(默认 mock 模式)

- ✅ 0 网络(MockLLMClient 本地)
- ✅ 0 Spark(纯 Python)
- ✅ 0 embedding

可选依赖:
- `pip install -e .[llm]` — httpx,启用真实 LLM
- `pip install -e .[spark]` — PySpark,启 Hive 直读

## 一键 Demo

```bash
bash scripts/demo.sh
# 默认 10 门店/类型 × 4 样本/商品,30s 内跑通 enrich → sft → split → verify
# set -uo pipefail(no -e)— mock LLM SC-003 不达标也跑完整链路
# 产物见 /tmp/training_data_demo/
```

## 3-Stage Pipeline

```
┌──────────────────────────────────────────────────────────┐
│ Stage 1: extract-tags  全量标签抽取                       │
│   从 Hive 抽取 brand/category 原始值 + 人工字典全量      │
│   → dim_dictionary_snapshot.yaml (8 维约束集)            │
└───────────────────────┬──────────────────────────────────┘
                        ↓
┌───────────────────────┴──────────────────────────────────┐
│ Stage 2: enrich       实际标注数据                        │
│   LLM 推断 8 维标签,字典约束,含 name_inference fallback  │
│   → item_tags.jsonl (300 行) + dim_dictionary_snapshot   │
└───────────────────────┬──────────────────────────────────┘
                        ↓
┌───────────────────────┴──────────────────────────────────┐
│ Stage 3: sft          合成 SFT 数据                       │
│   标签 → 多轮对话语料,字典校验 + 7 类清洗 + 80/10/10     │
│   → sft_corpus.jsonl + train/val/test.jsonl              │
└──────────────────────────────────────────────────────────┘
```

## 全部 CLI 子命令

```bash
# Stage 1 — 全量标签抽取(brand/category 从 Hive 抽取)
python -m training_data.cli extract-tags \
  --tables-config configs/tables.yaml \
  --source hive --hive-metastore-uri thrift://localhost:9083 \
  --output-dir ./dict_candidates --frequency-min 10
# Review ./dict_candidates/brands_diff.yaml → 人工 promote 进 configs/*.yaml

# Stage 2 — 实际标注数据(8 维标签,字典约束 LLM)
python -m training_data.cli enrich \
  --tables-config configs/tables.yaml \
  --source hive --hive-metastore-uri thrift://localhost:9083 \
  --output-dir ./out --n-items-per-type 100
# 自动导出 ./out/dim_dictionary_snapshot.yaml (Stage2 → Stage3 桥梁)

# Stage 2 with Stage 1 snapshot constraint:
python -m training_data.cli enrich \
  --tables-config configs/tables.yaml --source hive \
  --dict-snapshot ./dict_candidates/dim_dictionary_snapshot.yaml \
  --output-dir ./out

# Stage 3 — 合成 SFT 数据(标签 → 多轮对话语料)
python -m training_data.cli sft \
  --input ./out/item_tags.jsonl \
  --output-dir ./out --count-per-item 8 --max-message-turns 5

# split — SFT 语料 → 80/10/10 split(SC-010 no-leak)
python -m training_data.cli split \
  --input ./out/sft_corpus.jsonl \
  --output-dir ./out

# verify — SC self-check
python -m training_data.cli verify --output-dir ./out

# 一键 3-Stage
python -m training_data.cli all --source hive \
  --tables-config configs/tables.yaml \
  --hive-metastore-uri thrift://localhost:9083 \
  --output-dir ./e2e --n-items-per-type 50 --count-per-item 4
```

## 8 维 dim param schema

| 字段 | op | dict_values | 示例 |
|------|----|------|------|
| `category` | in | 12 | `{"op": "in", "values": ["咖啡"]}` |
| `consumable_type` | eq | 4(food/drink/mixed/none) | `{"op": "eq", "value": "drink"}` |
| `merchant` | in | 82 | `{"op": "in", "values": ["星巴克"]}` |
| `avg_prc` | in | 5 | `{"op": "in", "values": ["30-50"]}` |
| `distance` | in | 4 | `{"op": "in", "values": ["500-1000"]}` |
| `age` | in | 5 | `{"op": "in", "values": ["25-35"]}` |
| `occasion` | in | 13 | `{"op": "in", "values": ["下午茶"]}` |
| `taste` | contains / not_in | 14 | `{"op": "contains", "values": ["甜", "冰"]}` |

## 不依赖(默认 mock 模式)

- ✅ 0 网络(全部本地启发式)
- ✅ 0 LLM API(mock-llm 100% 本地)
- ✅ 0 Spark(纯 Python)
- ✅ 0 embedding 模型

可选依赖:
- `pip install -e .[llm]` — 装 httpx,启用 `--provider openai_compat` 真实 LLM 路径
- `pip install -e .[spark]` / `[hive]` — 生产 Hive 读取器(Spark / PyHive,留作 Phase 3 stub)

## 相关

- 同义词词表:`../synonym-dictionary/`
- 离线数据管线:`../data-pipeline/`
- v2.5 spec(在 `specs/` 子目录下):`spec.md` / `plan.md` / `data-model.md` / `quickstart.md`
