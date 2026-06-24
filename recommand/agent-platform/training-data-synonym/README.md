# 训练数据生成 (兴业 O2O 三品类 SFT 语料) — v2.5

**目录**: `agent-platform/training-data-synonym/`
**业务对齐**: 兴业银行信用卡 O2O 推荐系统(门店 + 权益券)
**数据源**: **Hive 集群** `recommand_workspace.*` / `cdm.*`(schema 见 `/opt/recommand/recommand/tabale_structer.sql`,737 行,10 张表)
**Spec**: v2.5 — Hive 直读 / 8 维商业属性 / 最多 5 轮对话 / `distance` 透传 + `consumable_type` 字典映射 / SFT 字典直采 / **Stage 0 字典扩量离线 CLI `extract-dictionary`**

## 用途

为 LP Agent **意图识别 + 提参** 模型微调生成 SFT 训练数据。给定 Hive 中三类商品(美团门店 / 自拓展门店 / 优惠券)的原始单据,流水线自动产出:
- 8 维商业属性标签(`category / consumable_type / merchant / avg_prc / distance / age / occasion / taste`)+ 3 族 `tag_source`
- 多轮对话样本(1~5 轮,默认 8 条/商品)
- 8 维 ground-truth `params`(`eq / in / contains / not_in` 四种 op)+ `intent` + `order_by`
- 字典校验 + 7 类清洗 + 8 项分布统计 + 按 item_id hash 划分 80/10/10
- 负样本(reject / pivot / unsatisfiable,默认 10%)

## 目录(per plan.md Project Structure v2.4)

```
training-data-synonym/
├── README.md                            # 本文档
├── pyproject.toml                       # Python 3.11+ 包配置 (T002)
├── requirements.txt                     # 依赖清单 (T003)
├── conftest.py                          # pytest fixtures (T005)
├── configs/
│   ├── dim_dictionary.yaml              # 8 维字典 (T024)
│   ├── consumable_type_map.yaml         # category→吃/喝 映射 (T025)
│   ├── brand_dictionary.yaml            # 60+ 品牌
│   ├── intent_keywords.yaml             # 5 类 intent (T010)
│   ├── sentence_templates.yaml          # 句式骨架 (T011)
│   ├── pipeline.yaml                    # 顶层配置 (T026)
│   └── prompts/
│       ├── enrichment_v1.txt            # Stage 1 prompt (T008)
│       └── sft_v1.txt                   # Stage 2 prompt (T009)
├── training_data_synonym/               # Python 包 (T001)
│   ├── data_model.py                    # 9 个 dataclass (T012)
│   ├── param_ops.py                     # ParamSpec + 字典校验 (T013)
│   ├── sql_parser/parser.py             # DDL 解析 (T014)
│   ├── hive_reader/                     # HiveReader 抽象 (T015/T016)
│   │   ├── base.py
│   │   ├── mock_reader.py
│   │   ├── spark_reader.py              # (Phase 3, T044)
│   │   └── pyhive_reader.py             # (Phase 3, T045)
│   ├── enricher/                        # Stage 1
│   │   ├── tag_schema.py
│   │   ├── consumable_mapper.py
│   │   ├── distance_geo.py
│   │   ├── llm_enricher.py
│   │   ├── state.py
│   │   ├── failures.py
│   │   ├── writer.py
│   │   ├── pipeline.py
│   │   ├── tables_meta_writer.py
│   │   └── cold_start.py
│   ├── sft/                             # Stage 2 (Phase 4)
│   ├── postprocess/                     # 清洗 + 划分 (Phase 5)
│   ├── common/                          # config / logging / llm_client / exceptions
│   └── cli.py                           # 顶层 CLI (Phase 3+5)
├── scripts/                             # legacy 兼容薄壳
│   ├── generate_training_data.py
│   ├── demo.sh
│   └── verify_quickstart.sh             # (Phase 6, T099)
├── tests/
│   ├── unit/{sql_parser,hive_reader,enricher,sft,postprocess,security}/
│   ├── contract/
│   ├── integration/
│   └── fixtures/
│       ├── hive/                        # MockHiveReader 数据源 (T018)
│       └── llm/                         # MockLLMClient 录像
└── docs/
    └── ALIGNMENT_cib_o2o.md
```

## 一键 Demo

```bash
bash scripts/demo.sh
# 10 门店 × 8 样本,30s 内跑通
```

## 全部 CLI 子命令

```bash
# Stage 0 — 字典扩量(US4 离线 ops 工具,每季度跑 1 次)
python -m training_data_synonym.cli extract-dictionary \
  --source mock --fixture-dir tests/fixtures/hive \
  --output-dir ./dict_candidates --frequency-min 10
# Review ./dict_candidates/brands_diff.yaml → 人工 promote 进 configs/*.yaml + bump version

# Stage 1 — Hive → 8 维标签
python -m training_data_synonym.cli enrich \
  --source mock --fixture-dir tests/fixtures/hive \
  --output-dir ./out

# Stage 2 — 标签 → 5 轮 SFT 语料
python -m training_data_synonym.cli sft \
  --input ./out/item_tags.jsonl \
  --output-dir ./out_sft --count-per-item 8

# 完整端到端
python -m training_data_synonym.cli all --source mock ...
```

## 单脚本使用

```bash
python scripts/generate_training_data.py \
    --sql /opt/recommand/recommand/tabale_structer.sql \
    --dim-dict configs/dim_dictionary.yaml \
    --brand-dict configs/brand_dictionary.yaml \
    --output-dir /tmp/training_output \
    --n-items 100 \
    --count-per-item 8 \
    --negative-ratio 0.1
```

## 产物

| 文件 | 用途 |
|------|------|
| `training_data_v1.jsonl` | 原始生成 |
| `training_data_failures.jsonl` | LLM 解析 / 字典校验失败 |
| `training_data_cleaned.jsonl` | 7 类清洗后 |
| `cleaning_failures.jsonl` | 清洗删除 |
| `cleaning_report.json` | 7 类规则触发统计 |
| `distribution_report.json` | 8 分布指标 |
| `train.jsonl` / `val.jsonl` / `test.jsonl` | 80/10/10 划分 |
| `summary.json` | SC 校验汇总 |

## 验证结果(10 门店 × 8 样本)

| SC | 状态 |
|----|------|
| SC-002 字典校验 | ✅ |
| SC-004 JSONL 解析 | ✅ |
| SC-005 模板多样性 | ✅ |
| SC-007 负样本比例 | ✅ |
| SC-008 留存 ≥ 85% | ✅ (98.7%) |
| SC-009 分布指标 | ✅ |
| SC-010 无泄露 | ✅ |

## 7 维 param schema

| 字段 | op | 示例 |
|------|----|------|
| `category` | in | `{"op": "in", "values": ["咖啡"]}` |
| `merchant` | in | `{"op": "in", "values": ["星巴克"]}` |
| `avg_prc` | in | `{"op": "in", "values": ["30-50"]}` |
| `distance` | in | `{"op": "in", "values": ["500-1000"]}` |
| `age` | in | `{"op": "in", "values": ["25-35"]}` |
| `occasion` | in | `{"op": "in", "values": ["下午茶"]}` |
| `taste` | contains / not_in | `{"op": "contains", "values": ["甜", "冰"]}` |

## 不依赖

- ✅ 0 网络(全部本地启发式)
- ✅ 0 LLM API(mock-llm 100% 本地)
- ✅ 0 Spark(纯 Python)
- ✅ 0 embedding 模型

## 相关

- 同义词词表:`../synonym-dictionary/`
- 离线数据管线:`../data-pipeline/`
- 002 spec(已在 `specs/` 子目录下,本地完整保留)
