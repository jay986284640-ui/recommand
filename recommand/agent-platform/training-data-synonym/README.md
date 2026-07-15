# 训练数据生成管线 — v2.5.2

**业务对齐**: 兴业银行信用卡 O2O 推荐系统
**数据源**: CSV / Hive,通过 `configs/tables.yaml` 声明表结构和 LLM 推断字段
**模型**: OpenAI 兼容 API（DeepSeek 等）

## 3-Stage Pipeline

```
Stage 1: extract-tags     LLM 自由推断 → item_profile.jsonl + dim_dictionary_snapshot.yaml
Stage 2: enrich           字典约束标注 → item_tags.jsonl + item_profile.jsonl
Stage 3: sft              SFT 语料合成 → train.jsonl(80%) + test.jsonl(20%)

generate-synonyms         同义词词表 → ext_dict.txt + ext_synonyms.txt
```

## 快速开始

```bash
cd agent-platform/training-data-synonym
export OPENAI_API_KEY="sk-xxx"

# Stage 1: 标签抽取
python -m training_data.cli extract-tags \
    --source csv --output-dir output/stage1 \
    --frequency-min 1 --provider openai_compat

# Stage 2: 字典约束标注
python -m training_data.cli enrich \
    --source csv --output-dir output/stage2 \
    --dict-snapshot output/stage1/dim_dictionary_snapshot.yaml \
    --provider openai_compat

# Stage 3: SFT 语料合成
python -m training_data.cli sft \
    --input output/stage2/item_profile.jsonl \
    --output-dir output/sft \
    --count-per-item 8 --provider openai_compat

# 同义词生成
python -m training_data.cli generate-synonyms \
    --dict-snapshot output/stage1/dim_dictionary_snapshot.yaml \
    --provider openai_compat

# 测试用（限制条数）
head -10 output/stage2/item_profile.jsonl > /tmp/test.jsonl
python -m training_data.cli sft --input /tmp/test.jsonl --max-items 10 --provider openai_compat
```

## 配置文件

### `configs/tables.yaml` — 表声明 + LLM 推断维度

```yaml
_meta:
  llm_inference:
    - field: category
      desc: 品类或菜系,如火锅、咖啡、川菜、日料
      multiple: false
    - field: brand
      desc: 品牌,如星巴克、麦当劳
      multiple: false
    - field: taste
      desc: 口味标签,如甜、辣、咸鲜
      multiple: true
    - field: occasion
      desc: 消费场景,如约会、聚餐
      multiple: true
    - field: consumable_type
      desc: 吃或喝,food/drink/mixed
      multiple: false

tables:
  - name: o2o_new_gut_shop_base_third
    role: meituan_shop
    item_id: str_id
    columns:
      - { name: str_id,  type: VARCHAR }
      - { name: str_nm,  type: VARCHAR, llm_input: true }
      - { name: cat_nm,  type: VARCHAR }
      - { name: avg_prc, type: VARCHAR }
```

### `configs/pipeline.yaml` — 运行参数

```yaml
training_data:
  input:
    source: csv
    csv_dir: ../../knowledge_database
    item_types: [meituan_shop]
  enrichment:
    batch_size: 50
    concurrency: 4
    llm:
      provider: openai_compat
      model: deepseek-v4-flash
      base_url: https://api.deepseek.com/v1
      timeout_seconds: 30
      max_tokens: 1024
  sft:
    tag_keys: [brand, category, taste, occasion, consumable_type, avg_prc, distance]
    concurrency: 4
    count_per_item: 8
    max_message_turns: 9
    llm:
      provider: openai_compat
      model: deepseek-v4-flash
      base_url: https://api.deepseek.com/v1
      timeout_seconds: 30
      max_tokens: 2048
```

**API Key 通过环境变量**: `export OPENAI_API_KEY="sk-xxx"`，不再写入配置文件避免 git 泄露。

## 全部 CLI 子命令

```bash
# Stage 1
python -m training_data.cli extract-tags --source csv --output-dir output/stage1 --provider openai_compat

# Stage 2
python -m training_data.cli enrich --source csv --output-dir output/stage2 \
    --dict-snapshot output/stage1/dim_dictionary_snapshot.yaml --provider openai_compat

# Stage 3 (SFT)
python -m training_data.cli sft --input output/stage2/item_profile.jsonl \
    --output-dir output/sft --count-per-item 8 --max-items 1000 --provider openai_compat

# 同义词
python -m training_data.cli generate-synonyms \
    --dict-snapshot output/stage1/dim_dictionary_snapshot.yaml --provider openai_compat

# 分割 + 校验
python -m training_data.cli split --input output/sft/train.jsonl --output-dir output/split
python -m training_data.cli verify --output-dir output/stage2

# 一键全流程
python -m training_data.cli all --source csv --output-dir output/e2e --provider openai_compat
```

## SFT 语料分布

| scenario_type | 占比 | 说明 |
|---------------|------|------|
| single_turn | 15% | 单轮简单查询 |
| single_multi_cond | 20% | 单轮多条件查询 |
| add_condition | 25% | 多轮新增条件 |
| modify_condition | 10% | 多轮修改条件 |
| remove_condition | 5% | 多轮删除条件 |
| negative_condition | 10% | 否定/排除 |
| reference_resolution | 5% | 指代消解 |
| intent_switch | 5% | 意图切换 |
| vague_query | 5% | 无意图模糊查询 |

输出: `train.jsonl`(80%) + `test.jsonl`(20%)，按 item_id md5 无泄漏分割。

## 同义词输出

| 文件 | 格式 | 用途 |
|------|------|------|
| `ext_synonyms.txt` | `凉茶, herbal tea, 草药茶` | ES synonym_graph |
| `ext_dict.txt` | 一行一词 | IK 分词词典 |

## 目录结构

```
agent-platform/training-data-synonym/
├── training_data/              # Python 包
│   ├── enricher/               # Stage 1/2: LLM 标签推断
│   ├── sft/                    # Stage 3: SFT 语料合成
│   ├── cli/                    # 命令行入口
│   ├── common/                 # LLM client / config / logging
│   ├── hive_reader/            # CSV/Hive 数据读取
│   └── data_model.py           # 数据模型
├── synonym-dictionary/         # 同义词生成
│   ├── synonym_builder/        # LLM 驱动同义词生成器
│   └── configs/prompts/        # 同义词 prompt
├── configs/
│   ├── tables.yaml             # 表声明 + LLM 推断配置
│   ├── pipeline.yaml           # 运行参数
│   └── prompts/                # Prompt 模板
└── output/                     # 产出目录
    ├── stage1/                 # dim_dictionary_snapshot.yaml
    ├── stage2/                 # item_tags.jsonl + item_profile.jsonl
    └── sft/                    # train.jsonl + test.jsonl
```

## 不依赖

- 0 网络（默认 mock 模式）
- 0 Spark（纯 Python CSV 读取）
- 0 embedding 模型

可选: `pip install httpx` 启用真实 LLM
