# 训练数据生成 (兴业 O2O 三品类 SFT 语料) — v2.5

**目录**: `agent-platform/training-data-synonym/`
**业务对齐**: 兴业银行信用卡 O2O 推荐系统(门店 + 权益券)
**数据源**: **Hive 集群** `recommand_workspace.*` / `cdm.*`(业务表 schema 见 `/opt/recommand/recommand/tabale_structer.sql`,737 行,10 张表;**本工程不再解析 SQL,改在 `configs/tables.yaml` 声明表结构 + 列 + sensitive flags**)
**Spec**: v2.5 — Hive 直读 / 8 维商业属性 / 最多 5 轮对话 / `distance` 透传 + `consumable_type` 字典映射 / SFT 字典直采 / **Stage 0 字典扩量离线 CLI `extract-dictionary`** / **YAML 表配置取代 SQL DDL 解析** / **真实 LLM 客户端(OpenAI 兼容 HTTP)** / **字典取值静默 reject + 可观测**

## 用途

为 LP Agent **意图识别 + 提参** 模型微调生成 SFT 训练数据。给定 Hive 中三类商品(美团门店 / 自拓展门店 / 优惠券)的原始单据,流水线自动产出:
- 8 维商业属性标签(`category / consumable_type / merchant / avg_prc / distance / age / occasion / taste`)+ 3 族 `tag_source`
- 多轮对话样本(1~5 轮,默认 8 条/商品)
- 8 维 ground-truth `params`(`eq / in / contains / not_in` 四种 op)+ `intent` + `order_by`
- 字典校验 + 7 类清洗 + 8 项分布统计 + 按 item_id hash 划分 80/10/10
- 负样本(reject / pivot / unsatisfiable,默认 10%)

## 目录(per plan.md Project Structure v2.5)

```
training-data-synonym/
├── README.md                            # 本文档
├── pyproject.toml                       # Python 3.11+ 包配置 (T002)
├── requirements.txt                     # 依赖清单 (T003)
├── conftest.py                          # pytest fixtures (T005)
├── configs/
│   ├── tables.yaml                      # 表结构声明 (NEW v2.5) — 取代 tabale_structer.sql 解析
│   ├── dim_dictionary.yaml              # 8 维字典(merchant 82, occasion 13, taste 14)
│   ├── consumable_type_map.yaml         # category→吃/喝 映射
│   ├── brand_dictionary.yaml            # 60+ 品牌(变体 + canonical)
│   ├── intent_keywords.yaml             # 5 类 intent
│   ├── sentence_templates.yaml          # 句式骨架
│   ├── pipeline.yaml                    # 顶层配置(LLM provider / Stage 0/1/2/split/verify)
│   └── prompts/
│       ├── enrichment_v1.txt            # Stage 1 prompt
│       └── sft_v1.txt                   # Stage 2 prompt
├── training_data_synonym/               # Python 包
│   ├── data_model.py                    # 9 个 dataclass
│   ├── param_ops.py                     # ParamSpec + 字典校验
│   ├── common/
│   │   ├── config.py                    # YAML 配置加载
│   │   ├── tables_config.py             # v2.5 — load_tables_config() + field_contract 校验
│   │   ├── llm_client.py                # v2.5 — MockLLMClient + OpenAICompatClient
│   │   ├── logging.py
│   │   ├── exceptions.py
│   │   └── versioning.py
│   ├── sql_parser/parser.py             # DEPRECATED v2.5 — 保留兼容
│   ├── hive_reader/                     # HiveReader 抽象(extract_geo 不再做隐式 JOIN)
│   ├── enricher/
│   │   ├── pipeline.py                  # Stage 1 主流程
│   │   ├── llm_enricher.py              # v2.5.1 接入 name_inference fallback
│   │   ├── consumable_mapper.py         # v2.5.1 接入 name_inferred_category fallback
│   │   ├── name_inference.py            # NEW v2.5.1 — 规则文案检测 + 子串推断
│   │   ├── tag_schema.py
│   │   ├── distance_geo.py
│   │   ├── state.py
│   │   ├── failures.py
│   │   ├── writer.py
│   │   ├── cold_start.py
│   │   └── tables_meta_writer.py
│   ├── sft/                             # Stage 2
│   ├── postprocess/                     # 清洗 + 划分(待 Phase 5)
│   └── cli/                             # 顶层 CLI
├── scripts/
│   ├── demo.sh                          # 端到端 demo(走新 CLI 4 段)
│   ├── generate_training_data.py        # legacy 薄壳(不再被 demo 调用)
│   ├── verify.py                        # legacy SC verifier
│   ├── cleaner.py                       # legacy 7-rule cleaner
│   ├── mock_llm_client.py               # legacy heuristic mock
│   ├── sql_parser.py                    # legacy regex parser
│   └── seed_fixtures.py                 # fixture 种子生成器
├── tests/
│   ├── unit/{common,hive_reader,enricher,sft,postprocess,security}/
│   ├── contract/
│   ├── integration/
│   └── fixtures/
│       └── hive/                        # MockHiveReader 数据源 + empty_brand.jsonl / rule_text_coupon.jsonl (NEW v2.5.1)
└── docs/
    └── ALIGNMENT_cib_o2o.md
```

## v2.5 重要变更

### 1. YAML 表配置取代 SQL 解析

旧:`parse_sql(tabale_structer.sql)` 解析 SQL DDL 推断表结构(脆弱、无法表达 sensitive 等意图)。

新:`configs/tables.yaml` 显式声明 `db / name / role / columns / type / sensitive`。
加载:`load_tables_config(path) -> list[TableMeta]`(校验:db+name 唯一 / role 合法 / columns 非空 / name+type 非空)。

```yaml
- db: recommand_workspace
  name: o2o_new_gut_shop_base_third
  role: meituan_shop
  partition_keys: [etl_dt]
  columns:
    - { name: str_id,  type: VARCHAR, sensitive: false }
    - { name: crt_psn_id, type: VARCHAR, sensitive: true }
    # ...
```

CLI:`--tables-config configs/tables.yaml`(默认)。`--sql <path>` 作为 deprecated alias 保留,
会发 stderr warning 并触发 `parse_sql` 兼容路径。`EnrichmentPipeline.__init__` 同时接受
`tables_config_path=...`(新)和 `sql_path=...`(legacy)。

### 2. 真实 LLM 客户端(OpenAI 兼容 HTTP)

`common/llm_client.py` 在 `MockLLMClient` 之外新增 `OpenAICompatClient`(POST `/chat/completions`,
Bearer Token,tenacity 重试 3× exp 0.1–1.0s,按 T097 契约每调用 emit 一行 JSON 日志含
`item_id / latency_ms / token_in / token_out / outcome`)。可选依赖:

```bash
pip install -e .[llm]   # 安装 httpx>=0.27
export OPENAI_API_KEY=sk-...
python -m training_data_synonym.cli enrich \
    --provider openai_compat --model claude-haiku-4-5 \
    --tables-config configs/tables.yaml \
    --source mock --fixture-dir tests/fixtures/hive \
    --output-dir ./out
```

`--provider` / `--api-key` / `--base-url` / `--max-tokens` 为全局 CLI flags(优先级 CLI > env > yaml)。

### 3. 字典取值静默 reject + 可观测

LLM 返回字典外值时:dim 仍被置 None(避免污染主产物),但同时:
- `logger.warning("dict_rejected", extra={stage, item_id, dim, rejected_values, allowed_count})`
- `LLMEnricher.rejection_count` / `ConsumableMapper.rejection_count` 累加
- `EnrichmentSummary.dict_rejected_count` 累加(全局统计)
- 每条 item 写一行 `EnrichmentFailure(error="dict_rejection")` 到 `tag_enrichment_failures.jsonl`
- `_self_check` 用真实计数算 `dict_pass_rate = 1 - dict_rejected_count / llm_calls`(原硬编码 1.0 已移除)

### 4. 字段契约 + 禁隐式 JOIN(v2.5.1)

- `configs/tables.yaml._meta.field_contract.<role>.required` 声明每种 role 必须暴露的字段
  (meituan_shop / self_shop / coupon 等),loader 在加载时校验,缺失字段抛 `TablesConfigError`
  阻止静默错误。
- 代码**不做跨表 JOIN**。任何字段组合(自拓展门店 + 地址表 → 经纬度;券 + 门店 → 绑定距离等)
  由上游 SQL 视图或 fixture pre-join 解决。例如 `extract_geo` 不再接受 `address_row` 参数,
  `self_shop` 表必须在 fixture / SQL 视图里直接含 `Lng`/`Lat`(本仓库 fixture 已用
  `scripts/` 预 join;生产由部署方维护)。
- 字段契约样例:
  ```yaml
  _meta:
    field_contract:
      meituan_shop:
        required: [id, name, brand, category, price, lng, lat]
        optional: [alt_price, alt_brand]
      self_shop:
        required: [id, name, brand, lng, lat]   # Lng/Lat 来自上游 SQL JOIN
      coupon:
        required: [id, name, desc]
  ```

### 5. 商品名称 fallback 推断(v2.5.1)

当原始字段(`Brnd_Nm` / `Cat_Nm` / `productDesc`)为空,或内容是券抢购规则文案
(满50减10 / 代金券 / 限时抢购 / 核销 / 优惠券)而非商品描述时,从 **商品名称**
(`Str_Nm` / `shopName` / `couponName`)按字典值做最长子串匹配推断 brand / category /
taste / occasion,并在 LLM 返回 None 时作为兜底。

- 模块:`training_data_synonym/enricher/name_inference.py`
- 公开函数:`compute_name_hints(raw, dim_dict, brand_values) -> dict`
- 规则文案识别(`is_rule_text`):任意匹配即**整体抑制**该 item 的所有推断(不误判)。
- 接线:
  - `LLMEnricher` 把 hints 注入 prompt(LLM 看到)→ LLM 返回 None 时替换(双重保护)
  - `ConsumableMapper` 当 `category=None` 时,用 name 推断 `category` 再查 mapping
- 可观测:`LLMEnricher.inferred_used_count` / `ConsumableMapper.inferred_count`,
  `logger.info("name_hint_used", ...)` 结构化日志。

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
python -m training_data_synonym.cli extract-tags \
  --tables-config configs/tables.yaml \
  --source hive --hive-metastore-uri thrift://localhost:9083 \
  --output-dir ./dict_candidates --frequency-min 10
# Review ./dict_candidates/brands_diff.yaml → 人工 promote 进 configs/*.yaml

# Stage 2 — 实际标注数据(8 维标签,字典约束 LLM)
python -m training_data_synonym.cli enrich \
  --tables-config configs/tables.yaml \
  --source hive --hive-metastore-uri thrift://localhost:9083 \
  --output-dir ./out --n-items-per-type 100
# 自动导出 ./out/dim_dictionary_snapshot.yaml (Stage2 → Stage3 桥梁)

# Stage 2 with Stage 1 snapshot constraint:
python -m training_data_synonym.cli enrich \
  --tables-config configs/tables.yaml --source hive \
  --dict-snapshot ./dict_candidates/dim_dictionary_snapshot.yaml \
  --output-dir ./out

# Stage 3 — 合成 SFT 数据(标签 → 多轮对话语料)
python -m training_data_synonym.cli sft \
  --input ./out/item_tags.jsonl \
  --output-dir ./out --count-per-item 8 --max-message-turns 5

# split — SFT 语料 → 80/10/10 split(SC-010 no-leak)
python -m training_data_synonym.cli split \
  --input ./out/sft_corpus.jsonl \
  --output-dir ./out

# verify — SC self-check
python -m training_data_synonym.cli verify --output-dir ./out

# 一键 3-Stage
python -m training_data_synonym.cli all --source hive \
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
