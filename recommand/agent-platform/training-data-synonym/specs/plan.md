# Implementation Plan: 训练数据生成 (兴业 O2O 三品类 SFT 语料)

**Branch**: `training-data-synonym` | **Date**: 2026-06-23 | **Spec**: [./spec.md](./spec.md) (v2.5)

**Input**: Feature specification from `agent-platform/training-data-synonym/specs/spec.md`

**Status**: Phase 1 设计完成;Stage 0 字典抽取 CLI(US4)已实现;Stage 1+2 MVP 已交付;Phase 5/6 待执行。

---

## Summary

为 LP Agent 的 **提参模型** 微调生成 SFT 语料,流水线三阶段(Stage 0 离线 / Stage 1 在线 / Stage 2 在线):

- **Stage 0(US4,离线 ops)**:`extract-dictionary` CLI 从 Hive 抽取品牌/分类候选 → Levenshtein + Jaccard 双阈值聚类 → 频次过滤 → 输出 `dict_candidates/` 候选文件供人工 review 后 promote 进权威 yaml。
- **Stage 1(US1,在线)**:从 Hive 读取三类商品原始单据 → 补齐 **8 维商业属性标签**(`category / consumable_type / merchant / avg_prc / distance / age / occasion / taste`)→ 产出 `item_tags.jsonl`。其中 `distance` 仅做 lng/lat 透传(不进 LLM),`consumable_type` 由 `category` 字典映射(不进 LLM),其余 6 维走"源列优先 → LLM 兜底"。
- **Stage 2(US2,在线)**:基于 Stage 1 输出生成最多 5 轮对话 + ground-truth 8 维 `params` + `intent` + `order_by`。`params.distance` / `order_by` 字典直采(与 lng/lat 完全解耦),其余 7 维由 item 标签驱动,LLM 负责自然语言对齐。后接清洗 → 分布统计 → 80/10/10 划分。

技术路径:**Python 库 + CLI 入口**,LLM 走 mock(开发/CI)或 LP Agent 主 spec 的"大模型平台托管 API"(生产);Hive 走读侧 spark/pyhive 适配器,可在 CI 中 `--source=mock`。

---

## Technical Context

**Language/Version**: Python 3.11+(沿用 data-pipeline / 001-promo-recommend-agent)

**Primary Dependencies**:

- **必需**:`pyyaml`(字典 / 映射 / 配置)、`jsonschema`(契约校验)、`tenacity`(LLM 调用重试)、`hashlib + parquet`(增量指纹状态)。
- **Hive 读侧适配器(可插拔)**:抽象 `HiveReader` 接口,生产实现使用 PySpark Hive Catalog(沿用 data-pipeline 的 Spark 3.5.3 客户端)/ PyHive HiveServer2;CI 走 `MockHiveReader`(读 fixture jsonl)。具体后端选择见 `research.md` §D-002。
- **LLM 客户端**:复用 `agent-platform/data-pipeline` 既有的 `LLMClient` 抽象(同 001-data-pipeline-enhancement);开发 / CI 走 `MockLLMClient`(本地启发式,无网络)。
- **NOT used**:embedding 模型 / sentence-transformers / 外网 LLM(开发 + CI 期)。

**Storage**:

- 输入(Hive,只读):`recommand_workspace.*` 与 `cdm.*`(`tabale_structer.sql` DDL 权威)。
- Stage 1 输出:本地 `./item_tags.jsonl`(主)/ `./tag_enrichment_failures.jsonl`(失败)/ `./tag_enrichment_state.parquet`(增量指纹)/ `./tables_meta.json`(表角色映射)。
- Stage 2 输出:`./sft_corpus.jsonl`(主)/ `./sft_failures.jsonl` / `./cold_start_items.jsonl` / `./distribution_report.json` / `./cleaning_failures.jsonl` / `./train.jsonl` / `./val.jsonl` / `./test.jsonl` / `./summary.json`。

**Testing**:

- pytest(单元 + 集成);所有外部依赖(Hive / LLM)替换为 mock,CI 100% 脱机。
- 关键集成测试:
  - `test_pipeline_end_to_end.py`:50 item × 8 sample → 验证 8 维字典合法、覆盖率、清洗留存、划分无泄露。
  - `test_distance_geo_passthrough.py`:三品类 shop_lng/lat 抽取 + `tag_source.distance` 标记(SC-002, FR-008b)。
  - `test_consumable_type_mapping.py`:`category → consumable_type` 映射命中率(FR-008c, SC-003)。
  - `test_distance_sampling.py`:SFT `params.distance` 与 `order_by` 字典采样耦合规则(FR-013b)。

**Target Platform**:

- 运行时:Linux 容器(沿用 data-pipeline 部署形态)。
- 开发 / CI:Linux / macOS,Python 3.11 + venv,无 Hive 集群依赖(`--source=mock`)。

**Project Type**:

- **Library + CLI**(对齐 Constitution Principles I / II)。本工程是 `agent-platform/training-data-synonym/` 子目录内的独立 Python 包,**不**改 `agent-platform/data-pipeline/`,**不**改 LP Agent envelope。

**Performance Goals**:

- 1 万 item × 8 sample = 8 万样本端到端 < 90 分钟(LLM 50 req/min × 16 并发,SC-010)。
- 增量 1% 重跑(100 item 新分区到达)< 8 分钟。
- Stage 1 Hive 读取(最近 1 个 `etl_dt` 分区,3 张核心表全量) < 5 分钟。
- 字典命中率 / 字典合法率 100%(SC-002),冷启动 item ≤ 1%。

**Constraints**:

- **不动**:`tabale_structer.sql` DDL、Hive 表结构、LP Agent envelope、`agent-platform/data-pipeline/` 现有代码。
- LLM 调用必须可降级(失败 → 写 failures + 继续),不阻塞主输出。
- Hive 调用必须可降级到 `MockHiveReader`,使工程在无 Hive 环境(CI / 本机)中可完整跑通。
- `params` 8 字段固定顺序写出,`distance` 永不进 LLM 推断,`consumable_type` 默认从 `category` 映射。
- 隐私字段黑名单(`MASTERCARD_CUST_ID` / `Crt_Psn_Id` / `Opr_Psn_Id` / `creator` / `updatePerson`)在 Hive 读入后立即剔除,不进 prompt / 输出。

**Scale/Scope**:

- item 总量:demo 100 item × 3 类 ≈ 300 item;全量 1w~10w SKU(沿用 LP Agent 主 spec 假设)。
- 单样本对话 1~5 轮(FR-010),默认 8 条/商品(可配 5~12)。
- 8 维 × 4 op(`eq / in / contains / not_in`) × 4 distance 桶 × 5 intent。
- 负样本 10% ± 0.02,3 种类型(`reject / pivot / unsatisfiable`)。

---

## Constitution Check

*Gate: must pass before Phase 0 research. Re-checked after Phase 1 design.*

### I. Library-First ✅

- `agent-platform/training-data-synonym/` 是独立 Python 包,**不**反向依赖 `data-pipeline/`。
- 子模块边界:`sql_parser` / `hive_reader` / `enricher` / `distance_geo` / `consumable_mapper` / `sft_generator` / `distance_sampler` / `cleaner` / `distribution_analyzer` / `splitter` / `writer`,每个均有明确单一职责。
- 与上游(Hive / 字典 yaml / LLM)接耦合点:抽象接口 + mock 实现,可独立测试。

### II. CLI Interface ✅

- 顶层入口 `python -m training_data_synonym.cli`(等价 `scripts/generate_training_data.py`):
  - `--source hive|mock --sql <path> --stage enrich|sft|all --mode full|incremental --etl-dt <YYYYMMDD>|latest_n=N --n-items-per-type <N> --output-dir <dir>`
- 文本 I/O:stdin/args → stdout(jsonl / json);错误 → stderr;支持 `--format human|json` 双格式输出 summary。
- 子命令辅助:`tables-meta`(只跑 SQL 解析)、`enrich`(只跑 Stage 1)、`sft`(只跑 Stage 2)、`split`(只跑划分)、`verify`(对照 SC 自检)。

### III. Test-First (NON-NEGOTIABLE) ✅

- `tasks.md` 拆分必须遵守:每个 FR 对应的实现任务**前置**契约测试 + 单元测试,先红后绿。
- 关键测试覆盖:
  - FR-001/002 → `test_sql_parser.py`(DDL → TableMeta)。
  - FR-003 → `test_hive_reader.py`(mock + 真 Hive 适配器抽象)。
  - FR-004/005/007 → `test_enricher.py`(6 维 LLM 兜底路径 + 失败降级)。
  - FR-008b → `test_distance_geo.py`(3 品类 lng/lat 抽取)。
  - FR-008c → `test_consumable_mapper.py`(`category → consumable_type` 命中率 + LLM 兜底)。
  - FR-009/010/011/012 → `test_sft_generator.py`(8 维 ground-truth + 覆盖率 + 顺序)。
  - FR-013/013b/014/015/016 → `test_negative_sampler.py` / `test_distance_sampler.py` / `test_diversity.py` / `test_intent_distribution.py`。
  - FR-017/018/019 → `test_cleaner.py` / `test_distribution.py` / `test_splitter.py`。
  - 端到端:`test_pipeline_end_to_end.py`(50 item × 8 sample,覆盖所有 SC)。

### IV. Integration Testing ✅

- Hive ↔ enricher:`HiveReadSpec` 契约测试(`contracts/hive_read_v1.md`)。
- enricher → SFT generator:`item_tags_v2.jsonl` schema 契约测试(`contracts/item_tags_v2.md`)。
- SFT generator → 训练管线:`sft_corpus_v2.jsonl` schema 契约测试(`contracts/sft_corpus_v2.md`)。
- Stage 1 ↔ Stage 2 增量状态文件:`tag_enrichment_state.parquet` schema 契约测试。

### V. Observability, Versioning & Simplicity ✅

- **Observability**:`summary.json` 汇报每阶段输入/输出条数 / LLM 调用次数 / 字典命中率 / 8 维覆盖率 / SC 通过情况;结构化日志(每个 LLM 调用一行 JSON,含 `item_id / latency_ms / token_in/out / outcome`)。
- **Versioning**:输出三类产物均带 `_format_version` 字段(`item_tags_v2` / `sft_corpus_v2` / `train_split_v1`);字典文件带 `_meta.version`,变更触发 Stage 1 增量重算。本次 spec v2.4 对应 `item_tags_v2` + `sft_corpus_v2`(若已有 v1 直接 superseded)。
- **Simplicity**:不引入 embedding、不引入向量库、不引入新的中间件;复用 `agent-platform/data-pipeline` 的 LLMClient 抽象与配置加载;字典 / 映射全部 yaml 外部化,字典变更不改代码。

**Constitution Check 状态**:✅ **通过**(Phase 0 之前)。`Complexity Tracking` 表空。

---

## Project Structure

### Documentation (this feature)

```text
agent-platform/training-data-synonym/specs/
├── spec.md                            # 已有(v2.4)
├── plan.md                            # 本文件(/speckit-plan 输出)
├── research.md                        # Phase 0 输出
├── data-model.md                      # Phase 1 输出
├── quickstart.md                      # Phase 1 输出
├── contracts/                         # Phase 1 输出
│   ├── item_tags_v2.md
│   ├── sft_corpus_v2.md
│   ├── param_op_types_v2.md
│   └── hive_read_v1.md
├── checklists/
│   └── requirements.md                # 已有(/speckit-clarify 维护)
└── tasks.md                           # Phase 2 输出(/speckit-tasks 生成)
```

### Source Code (project root: `agent-platform/training-data-synonym/`)

```text
agent-platform/training-data-synonym/
├── README.md                          # 已有
├── docs/
│   └── ALIGNMENT_cib_o2o.md           # 已有
├── configs/                           # 字典与映射
│   ├── dim_dictionary.yaml            # 8 维候选值(原 7 维 + consumable_type)
│   ├── consumable_type_map.yaml       # 新增 — category → food/drink/mixed/none
│   ├── brand_dictionary.yaml          # 已有
│   ├── intent_keywords.yaml           # 5 类 intent 模板词(新增,FR-015 用)
│   ├── prompts/
│   │   ├── enrichment_v1.txt          # Stage 1 LLM prompt(6 维兜底 + consumable_type 兜底)
│   │   └── sft_v1.txt                 # Stage 2 LLM prompt(8 维 + 5 轮对话 + 负样本注入)
│   └── pipeline.yaml                  # 顶层运行配置(对齐 spec.md Configuration Snapshot)
├── training_data_synonym/             # Python 包(库源码)
│   ├── __init__.py
│   ├── cli/                           # CLI 子包(Constitution Principle II)
│   │   ├── __init__.py                # 主入口 + tables-meta / enrich / sft / split / verify / all / extract-dictionary
│   │   ├── __main__.py                # `python -m training_data_synonym.cli` 入口
│   │   └── extract_dictionary.py      # US4 Stage 0 离线工具(SQL 抽取 + 规范化 + 频次 + diff)
│   ├── sql_parser/
│   │   ├── __init__.py
│   │   └── parser.py                  # 解析 tabale_structer.sql → TableMeta
│   ├── hive_reader/
│   │   ├── __init__.py
│   │   ├── base.py                    # HiveReader 抽象 + HiveReadSpec dataclass
│   │   ├── spark_reader.py            # PySpark Hive Catalog 实现(生产)
│   │   ├── pyhive_reader.py           # PyHive HiveServer2 实现(可选)
│   │   └── mock_reader.py             # MockHiveReader,读 tests/fixtures/hive/
│   ├── enricher/                      # Stage 1
│   │   ├── __init__.py
│   │   ├── pipeline.py                # EnrichmentPipeline(批量编排 + 增量比对)
│   │   ├── tag_schema.py              # 8 维 ParamSpec + tag_source 枚举 + 校验
│   │   ├── distance_geo.py            # FR-008b — lng/lat 透传抽取
│   │   ├── consumable_mapper.py       # FR-008c — category → consumable_type 映射 + LLM 兜底
│   │   ├── llm_enricher.py            # FR-005/007 — 6 维 LLM 兜底
│   │   ├── state.py                   # FR-006 — 增量 md5 指纹 + parquet 状态
│   │   ├── failures.py                # FR-007 — 失败明细写盘
│   │   └── writer.py                  # `item_tags_v2.jsonl` 写出
│   ├── sft/                           # Stage 2
│   │   ├── __init__.py
│   │   ├── pipeline.py                # SFTPipeline(批量 LLM + 覆盖率追踪)
│   │   ├── sample_planner.py          # FR-011 — 单 item 维度覆盖规划 + 强制补样
│   │   ├── distance_sampler.py        # FR-013b — distance / order_by 字典直采
│   │   ├── negative_sampler.py        # FR-013 — 3 类负样本
│   │   ├── diversity.py               # FR-014 — 句式多样性
│   │   ├── intent_assigner.py         # FR-015/016 — 5 类 intent + 三品类倾向
│   │   ├── llm_generator.py           # LLM 多轮对话生成(对齐 ground-truth)
│   │   ├── validator.py               # 8 维字典校验 + 5 轮上限
│   │   └── writer.py                  # `sft_corpus_v2.jsonl` 写出
│   ├── postprocess/                   # 清洗 / 分布 / 划分
│   │   ├── __init__.py
│   │   ├── cleaner.py                 # FR-017 — 7 类清洗
│   │   ├── distribution.py            # FR-018 — 8 项分布指标
│   │   ├── balancer.py                # FR-018 — 长尾过采样
│   │   ├── splitter.py                # FR-019 — 80/10/10 hash 划分
│   │   └── summary.py                 # FR-021 — summary.json
│   └── common/
│       ├── __init__.py
│       ├── config.py                  # 配置加载(pipeline.yaml + 字典)
│       ├── llm_client.py              # 复用 data-pipeline 的 LLMClient 抽象
│       ├── mock_llm_client.py         # 本地启发式 mock
│       └── logging.py                 # 结构化日志(json line)
├── scripts/                           # 已有(legacy demo 脚本,本批迁移到 training_data_synonym 包后保留为薄壳)
│   ├── generate_training_data.py      # 调用 training_data_synonym.cli
│   ├── sql_parser.py                  # 已有 — 保留兼容(实际逻辑迁入包)
│   ├── mock_llm_client.py             # 已有 — 同上
│   ├── cleaner.py                     # 已有
│   ├── verify.py                      # 已有
│   └── demo.sh                        # 一键 demo(10 门店,~1 min)
└── tests/
    ├── __init__.py
    ├── conftest.py                    # pytest fixtures(mock LLM / mock Hive / 临时输出目录)
    ├── unit/
    │   ├── sql_parser/
    │   │   └── test_parser.py
    │   ├── hive_reader/
    │   │   └── test_mock_reader.py
    │   ├── enricher/
    │   │   ├── test_tag_schema.py
    │   │   ├── test_distance_geo.py
    │   │   ├── test_consumable_mapper.py
    │   │   ├── test_llm_enricher.py
    │   │   └── test_state.py
    │   ├── sft/
    │   │   ├── test_sample_planner.py
    │   │   ├── test_distance_sampler.py
    │   │   ├── test_negative_sampler.py
    │   │   ├── test_diversity.py
    │   │   ├── test_intent_assigner.py
    │   │   └── test_validator.py
    │   └── postprocess/
    │       ├── test_cleaner.py
    │       ├── test_distribution.py
    │       ├── test_balancer.py
    │       └── test_splitter.py
    ├── contract/                      # Constitution IV — 契约测试
    │   ├── test_item_tags_schema.py
    │   ├── test_sft_corpus_schema.py
    │   ├── test_param_op_types.py
    │   └── test_hive_read_spec.py
    ├── integration/
    │   ├── test_stage1_end_to_end.py
    │   ├── test_stage2_end_to_end.py
    │   └── test_pipeline_end_to_end.py   # 全量(50 item × 8 sample,SC 自检)
    └── fixtures/
        ├── hive/                      # MockHiveReader 数据源
        │   ├── o2o_new_gut_shop_base_third.jsonl
        │   ├── o2o_new_gut_shop_base.jsonl
        │   ├── o2o_new_gut_shop_address.jsonl
        │   ├── o2o_new_gut_coupon_template.jsonl
        │   ├── o2o_new_gut_coupon_shop.jsonl
        │   └── o2o_new_gut_shop_category_meituan.jsonl
        └── llm/
            └── mock_responses.jsonl   # 离线 LLM 响应录像
```

**Structure Decision**:

- **库 + CLI + 配置 + 测试**(Constitution Principle I/II 双满足)。
- 路径根:`agent-platform/training-data-synonym/`(已存在,本批扩展)。
- 既有 `scripts/*.py` 保留为兼容薄壳;实际逻辑迁入 `training_data_synonym/` 包,以满足 Library-First(Principle I)。
- `data-pipeline/`、`synonym-dictionary/`、`local-promo-agent/`、`main-agent/` **全部不动**。

---

## Phase 0 — Outline & Research

研究产物:[`./research.md`](./research.md)。

### Open questions(为研究项)

1. **Hive 读侧适配器选型**(D-002):PySpark Hive Catalog vs PyHive HiveServer2 vs Trino — 需要在"现有 data-pipeline 已用 PySpark / 一致性优先 / 内存占用"三维度评估。
2. **`distance_bucket_weights` 默认分布**(D-006):字典 4 桶等权(0.25 × 4) vs 偏置(近距偏高) — 取决于 LP Agent 真实意图分布;以"均衡为先"作 baseline。
3. **`consumable_type_map.yaml` 初始候选完整性**(D-007):覆盖 `dim_dictionary.category` 全部 12 个候选值 + 兜底分支。
4. **券文本 `consumable_type` 关键词词表**(D-008):FR-008c.5 优惠券文本判定的关键词种子集 + 与品类的优先级。
5. **`MockHiveReader` fixture 规模与代表性**(D-009):每张表 100 行 × 3 品类应该覆盖哪些边界(冷启动 / 多门店券 / 缺 lng/lat 等)。
6. **LLM prompt 模板设计**(D-010 / D-011):Stage 1(6 维兜底)与 Stage 2(8 维 + 5 轮对话 + 负样本注入)各自的 prompt 骨架与 few-shot 数量。
7. **structured output 与 retry 策略**(D-012):LLM JSON 输出失败时的重试 / 解析 / 字典校验降级链。

### Decisions(已收敛)— 在 research.md 详述

| ID | 决策点 | 选项 | 推荐 |
|----|--------|------|------|
| D-001 | 子包架构 | 全独立 / 复用 data-pipeline 子模块 | **全独立**(Library-First) |
| D-002 | Hive 适配器 | PySpark / PyHive / Trino | **PySpark(生产)+ Mock(CI),PyHive 作可选后端** |
| D-003 | 增量指纹键 | `item_id + raw_md5` / `item_id + raw_md5 + etl_dt + dict_version` | **四元组**(覆盖新分区 + 字典升级) |
| D-004 | `distance` 路径 | LLM 推断 / 几何计算 / 透传 | **透传**(spec v2.4 决定) |
| D-005 | `consumable_type` 路径 | LLM 推断 / category 映射 + LLM 兜底 / 全 LLM | **映射 + 兜底**(spec v2.4 决定) |
| D-006 | SFT `distance` 来源 | 几何计算 / 字典直采 / 不填 | **字典直采**(spec v2.4 决定) |
| D-007 | 字典版本化 | 硬编码 / 外部 yaml | **外部 yaml**(沿用 001) |
| D-008 | 负样本类型 | 仅拒绝 / 三类(reject / pivot / unsatisfiable) | **三类**(spec v2.4 / FR-013) |
| D-009 | op 类型集合 | 4 个基础 / 4+3 完整 | **4 个基础**(`eq / contains / in / not_in`) |
| D-010 | 多样性控制 | 句式模板随机 / 温度 / 二者结合 | **二者结合**(FR-014, SC-007) |
| D-011 | 划分键 | 随机 / `item_id` hash | **`item_id` hash**(FR-019, SC-009) |
| D-012 | LLM 失败策略 | 重试 N 次 / 降级 null / 直接退出 | **重试 2 次后写 failures + 跳过**(FR-007, FR-022) |
| D-013 | mock Hive 实现 | 内联 fixture / fixture 目录 | **fixture 目录**(`tests/fixtures/hive/`) |
| D-014 | 离散 LLM 录像 | 不录 / 录全部 / 录关键 case | **录关键 case**(`tests/fixtures/llm/mock_responses.jsonl`) |
| D-015 | 字典扩量策略(US4 Stage 0)| 手工 yaml / SQL 抽取 / 第三方 ETL | **SQL 抽取 + 双阈值聚类**(`extract-dictionary` 离线 CLI) |
| D-016 | 品牌聚类指标 | 单一 Levenshtein / Levenshtein + Jaccard / 嵌入相似度 | **Levenshtein + char 2-gram Jaccard 双阈值** |
| D-017 | 跨脚本品牌处理 | 强制合并 / 强制分开 / 自适应 | **强制分开**(CJK vs Latin 不合并,避免误判) |
| D-018 | 离线 vs 在线治理 | 字典扩量走 Stage 1 / 字典扩量独立 CLI | **独立 CLI**,产物落到候选区,人工 promote |

---

## Phase 1 — Design Artifacts

| 产物 | 路径 | 用途 |
|------|------|------|
| 数据模型 | [`./data-model.md`](./data-model.md) | 9 个实体 dataclass / JSON schema 总览 |
| 契约 — Stage 1 输出 | [`./contracts/item_tags_v2.md`](./contracts/item_tags_v2.md) | `item_tags_v2.jsonl` 行级 schema + tag_source 枚举三族 |
| 契约 — Stage 2 输出 | [`./contracts/sft_corpus_v2.md`](./contracts/sft_corpus_v2.md) | `sft_corpus_v2.jsonl` 行级 schema + `covered_dims` / `forced_coverage` 字段 |
| 契约 — Param `op` | [`./contracts/param_op_types_v2.md`](./contracts/param_op_types_v2.md) | 8 维 ↔ 4 op 映射 + 字典校验流程 |
| 契约 — Hive 读 | [`./contracts/hive_read_v1.md`](./contracts/hive_read_v1.md) | `HiveReader` 接口 + `HiveReadSpec` + mock 行为 |
| 快速验证 | [`./quickstart.md`](./quickstart.md) | 端到端 demo + SC 自检脚本 |

---

## Phase 1 后的 Constitution Check

| Principle | 状态 | 理由 |
|-----------|------|------|
| I. Library-First | ✅ | `training_data_synonym/` 是独立包,所有依赖单向,子模块边界清晰 |
| II. CLI Interface | ✅ | 顶层 `cli/__init__.py` + 7 个子命令(`tables-meta / enrich / sft / split / verify / all / extract-dictionary`)+ `--format human|json` |
| III. Test-First | ✅ | 4 类测试目录(unit / contract / integration / fixtures);tasks.md 必须先红后绿 |
| IV. Integration Testing | ✅ | 4 张契约 + 3 个 integration scenarios 全覆盖 |
| V. Observability, Versioning, Simplicity | ✅ | `_format_version` / `summary.json` / 结构化日志;无 embedding / 无中间件 |

**Phase 1 后状态**:✅ **通过**。`Complexity Tracking` 表保持空。

---

## Complexity Tracking

> 若 Constitution Check 失败需在此说明。

| 违反 | 为什么 | 更简单方案(被拒理由) |
|------|--------|---------------------|
| (空) | (空) | (空) |

---

## Next Steps

1. **Phase 2 — `/speckit-tasks`**:基于 spec v2.5 + 本 plan + 4 张契约,按 US1 / US2 / US3 切分任务,**每个 FR 至少 1 个契约测试 + 1 个实现任务**,先红后绿;预计任务数 ~110(US1 ~30 / US2 ~30 / US3 ~10 / US4 ~10 / 通用 ~10 / Polish ~10)。
2. **Phase 3 — `/speckit-implement`**:按 tasks.md 依赖序执行,每个 US 完成后跑 `verify` 子命令做 SC 自检。
3. **同步刷新**:`README.md` 表格(7 维 → 8 维)、`docs/ALIGNMENT_cib_o2o.md`(consumable_type)、`configs/dim_dictionary.yaml`(增 `consumable_type` 段)、`cli/extract_dictionary.py`(US4 离线工具)。

---

## Changelog

| Version | Date | Notes |
|---------|------|-------|
| v1 | 2026-06-14 | 初版:输入为 `item_features_ai.jsonl`(依赖 001-data-pipeline-enhancement),7 维口味标签,对话 1~4 轮。 |
| v2.4 | 2026-06-22 | 重写对齐 spec v2.4:Hive 直接读、三品类源表、8 维(含 `consumable_type`)、5 轮对话上限、`distance` 透传 + SFT 字典直采、FR-008b/c/013b 三个新 FR;子包结构与测试目录全部刷新。 |
| **v2.5** | 2026-06-23 | 新增 US4 字典扩量离线 CLI `extract-dictionary`(Stage 0):新增 D-015/D-016/D-017/D-018 决策;Project Structure 增 `cli/extract_dictionary.py`;与 Stage 1/2 主流水线解耦,产物落到 `dict_candidates/` 候选区。 |
