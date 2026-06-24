# Tasks: 训练数据生成 (兴业 O2O 三品类 SFT 语料)

**Input**: Design documents from `agent-platform/training-data-synonym/specs/`
**Prerequisites**: plan.md (required), spec.md (v2.4, required for US), research.md, data-model.md, contracts/{item_tags_v2, sft_corpus_v2, param_op_types_v2, hive_read_v1}.md, quickstart.md

**Tests**: Constitution Principle III requires test-first;test tasks are interleaved before implementation tasks for each user story.

**Organization**: Tasks grouped by user story (US1 = Stage 1 标签补全 / US2 = Stage 2 SFT 语料 / US3 = 划分);each story independently implementable, testable, deliverable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable(different files, no dependencies on incomplete tasks)
- **[Story]**: `[US1] / [US2] / [US3]` — only on user-story phase tasks
- **Path**: Exact file path under `agent-platform/training-data-synonym/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, package skeleton, config + linting.

- [ ] T001 Create Python package skeleton at `agent-platform/training-data-synonym/training_data_synonym/` with empty `__init__.py` per plan.md Project Structure
- [ ] T002 Create `agent-platform/training-data-synonym/pyproject.toml` declaring Python 3.11+ + deps `pyyaml, jsonschema, tenacity, pytest, hypothesis, ruff`
- [ ] T003 Create `agent-platform/training-data-synonym/requirements.txt` pinning `pyyaml>=6.0`, `jsonschema>=4.18`, `tenacity>=8.2`, `pytest>=7.4`, `pytest-cov`, `hypothesis>=6.82`, `ruff>=0.1`
- [ ] T004 [P] Configure ruff + black in `agent-platform/training-data-synonym/pyproject.toml` (line-length 100, target-version py311)
- [ ] T005 [P] Create `agent-platform/training-data-synonym/conftest.py` with shared fixtures (`tmp_output_dir`, `mock_llm_client`, `mock_hive_reader`)
- [ ] T006 [P] Create `agent-platform/training-data-synonym/tests/__init__.py` + 4 sub-package `__init__.py` (unit / contract / integration / fixtures)
- [ ] T007 Refresh `agent-platform/training-data-synonym/README.md` (8 维 + 3 品类 + Hive 数据源 + 5 轮对话;sync with spec v2.4)
- [ ] T008 [P] Add `configs/prompts/enrichment_v1.txt` Stage 1 prompt (per research.md D-010)
- [ ] T009 [P] Add `configs/prompts/sft_v1.txt` Stage 2 prompt (per research.md D-011)
- [ ] T010 [P] Add `configs/intent_keywords.yaml` 5 类 intent 关键词模板(per FR-015/016)
- [ ] T011 [P] Add `configs/sentence_templates.yaml` Stage 2 句式骨架 5~8 套(per FR-014)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure shared by ALL user stories. **No US work can begin until this phase is complete.**

- [ ] T012 [P] Implement `TableMeta / ColumnMeta / Role / TagOrigin` dataclasses in `agent-platform/training-data-synonym/training_data_synonym/data_model.py` (per data-model.md §实体 1 + §实体 5)
- [ ] T013 [P] Implement `ParamSpec` dataclass + `validate_params()` 7-step validator in `agent-platform/training-data-synonym/training_data_synonym/param_ops.py` (per data-model.md §实体 6 + contracts/param_op_types_v2.md)
- [ ] T014 Implement `SqlParser` in `agent-platform/training-data-synonym/training_data_synonym/sql_parser/parser.py` (DDL → TableMeta list,role inference rules per data-model.md §实体 1)
- [ ] T015 Define `HiveReadSpec / RawRecord` dataclasses in `agent-platform/training-data-synonym/training_data_synonym/hive_reader/base.py` (per data-model.md §实体 2,3)
- [ ] T016 Define `HiveReader` abstract base class + exception types (`ConnectionError / AccessDenied / EmptyPartitionSet / SchemaDriftError / DuplicateItemIdError / SensitiveLeakError`) in `agent-platform/training-data-synonym/training_data_synonym/hive_reader/base.py`
- [ ] T017 [P] Implement `MockHiveReader` in `agent-platform/training-data-synonym/training_data_synonym/hive_reader/mock_reader.py` (per contracts/hive_read_v1.md;reads fixture dir)
- [ ] T018 Seed mock fixtures in `agent-platform/training-data-synonym/tests/fixtures/hive/` (7 tables × 100 rows per research.md D-013): `o2o_new_gut_shop_base_third.jsonl` (50 有 lng/lat + 50 无), `o2o_new_gut_shop_base.jsonl`, `o2o_new_gut_shop_address.jsonl` (80% 覆盖), `o2o_new_gut_coupon_template.jsonl`, `o2o_new_gut_coupon_shop.jsonl` (70 张券绑定), `o2o_new_gut_shop_category_meituan.jsonl`, `o2o_new_gut_shop_category_mapping.jsonl`
- [ ] T019 Implement structured JSON-line logging in `agent-platform/training-data-synonym/training_data_synonym/common/logging.py` (per Constitution V;fields: `ts, level, stage, item_id, event, latency_ms, outcome`)
- [ ] T020 Implement config loader (yaml → dataclass) in `agent-platform/training-data-synonym/training_data_synonym/common/config.py` (loads `pipeline.yaml` + 3 dict yamls + computes `dict_version` md5)
- [ ] T021 [P] Define `LLMClient` abstract base + `MockLLMClient` in `agent-platform/training-data-synonym/training_data_synonym/common/llm_client.py` (per research.md D-012;retry 2x + exponential backoff)
- [ ] T022 [P] Implement `_format_version` constants module in `agent-platform/training-data-synonym/training_data_synonym/common/versioning.py` (`item_tags_v2`, `sft_corpus_v2`, `table_meta_v1`, `train_split_v1`, `distribution_report_v1`)
- [ ] T023 Define common exception hierarchy in `agent-platform/training-data-synonym/training_data_synonym/common/exceptions.py` (`PipelineError`, `StageError`, `ValidationError`, `ContractError`)
- [ ] T024 Update `agent-platform/training-data-synonym/configs/dim_dictionary.yaml` to 8 维 + add `_meta.version: 2.0` (per spec v2.4)
- [ ] T025 Add `agent-platform/training-data-synonym/configs/consumable_type_map.yaml` (per research.md D-007:drink/food/mixed + default:none + coupon_text_hints)
- [ ] T026 Add `agent-platform/training-data-synonym/configs/pipeline.yaml` 顶层配置 (per spec Configuration Snapshot:`input.hive`, `enrichment`, `sft`, `cleaning`, `distribution`, `split`)

**Checkpoint**: Foundation ready — `sql_parser`, `HiveReader` 抽象, mock 实现, dict yaml, LLMClient mock, 异常体系, 日志与配置 全部就绪;Stage 1 / Stage 2 可以并行启动。

---

## Phase 3: User Story 1 — Stage 1 标签补全 (Priority: P1) 🎯 MVP

**Goal**: 把 Hive 中三类商品原始单据补齐为 8 维商业属性标签,产出 `item_tags.jsonl`;`distance` 透传 + `consumable_type` 字典映射 + 其余 6 维 LLM 兜底。

**Independent Test**: `python -m training_data_synonym.cli enrich --source mock --n-items-per-type 100` 产出 ≥ 200 行 `item_tags.jsonl`,SC-002 / SC-003 自动化断言绿(字典合法率 100%、8 维平均覆盖 ≥ 7、`tag_source.distance ∈ {geo, missing}`、`tag_source.consumable_type ∈ {derived, ai, missing}`)。

### Tests for User Story 1 ⚠️ Write FIRST, ensure FAIL before implementation

- [ ] T027 [P] [US1] Contract test for `item_tags_v2.jsonl` schema in `agent-platform/training-data-synonym/tests/contract/test_item_tags_schema.py` (per contracts/item_tags_v2.md §字段详解 + §`tag_source` 三族枚举)
- [ ] T028 [P] [US1] Contract test for `HiveReader` interface in `agent-platform/training-data-synonym/tests/contract/test_hive_read_spec.py` (per contracts/hive_read_v1.md;8 个测试用例含 sensitive drop / 0 泄露 / namespace isolation)
- [ ] T029 [P] [US1] Unit test for SQL parser role inference in `agent-platform/training-data-synonym/tests/unit/sql_parser/test_parser.py` (覆盖 11 张表 + 边界:未知表 → UNKNOWN)
- [ ] T030 [P] [US1] Unit test for MockHiveReader in `agent-platform/training-data-synonym/tests/unit/hive_reader/test_mock_reader.py` (per contracts/hive_read_v1.md §"行为差异表";敏感列 drop / item_id namespace / geo 抽取 / partition filter)
- [ ] T031 [P] [US1] Unit test for `distance_geo` in `agent-platform/training-data-synonym/tests/unit/enricher/test_distance_geo.py` (per FR-008b;3 品类各自来源 + lng/lat 合法性 5 条规则)
- [ ] T032 [P] [US1] Unit test for `consumable_mapper` in `agent-platform/training-data-synonym/tests/unit/enricher/test_consumable_mapper.py` (per FR-008c;`category → consumable_type` 映射命中率 ≥ 90% + LLM 兜底 + 优惠券文本判定)
- [ ] T033 [P] [US1] Unit test for `tag_schema` validation in `agent-platform/training-data-synonym/tests/unit/enricher/test_tag_schema.py` (`tag == null ⇔ tag_source == missing` 不变式 + 三族枚举白名单)
- [ ] T034 [P] [US1] Unit test for incremental `state` in `agent-platform/training-data-synonym/tests/unit/enricher/test_state.py` (4 元组指纹比对,新分区到达 / 字典升级触发重算)
- [ ] T035 [P] [US1] Unit test for `llm_enricher` 6 维 LLM 兜底 in `agent-platform/training-data-synonym/tests/unit/enricher/test_llm_enricher.py` (降级路径:超时 / JSON 错 / 字典外 → null + failures 写入)
- [ ] T036 [P] [US1] Integration test for Stage 1 end-to-end in `agent-platform/training-data-synonym/tests/integration/test_stage1_end_to_end.py` (300 行 mock fixture → 完整 item_tags.jsonl + SC-002/003 自检)

### Implementation for User Story 1

- [ ] T037 [P] [US1] Implement `ItemTags / TagSource` dataclasses in `agent-platform/training-data-synonym/training_data_synonym/enricher/tag_schema.py` (per data-model.md §实体 4,5)
- [ ] T038 [P] [US1] Implement `consumable_mapper` in `agent-platform/training-data-synonym/training_data_synonym/enricher/consumable_mapper.py` (per FR-008c;load `consumable_type_map.yaml` + coupon_text_hints)
- [ ] T039 [P] [US1] Implement `distance_geo` in `agent-platform/training-data-synonym/training_data_synonym/enricher/distance_geo.py` (per FR-008b;3 品类 lng/lat 抽取 + 合法性 5 条规则 + `tag_source.distance = geo / missing`)
- [ ] T040 [US1] Implement `llm_enricher` 6 维 LLM 兜底 in `agent-platform/training-data-synonym/training_data_synonym/enricher/llm_enricher.py` (per FR-005/007;load `enrichment_v1.txt` + 字典子集注入 + 重试 2x + 失败写 failures)
- [ ] T041 [P] [US1] Implement `state` incremental fingerprint in `agent-platform/training-data-synonym/training_data_synonym/enricher/state.py` (per FR-006 + research.md D-003;parquet 4 元组 + read-modify-write)
- [ ] T042 [P] [US1] Implement `failures` writer in `agent-platform/training-data-synonym/training_data_synonym/enricher/failures.py` (per contracts/item_tags_v2.md §失败样本 schema)
- [ ] T043 [US1] Implement `writer` for `item_tags_v2.jsonl` in `agent-platform/training-data-synonym/training_data_synonym/enricher/writer.py` (固定 8 维字段顺序 + `_format_version = item_tags_v2` + raw_record 透传)
- [ ] T044 [US1] Implement `SparkHiveReader` in `agent-platform/training-data-synonym/training_data_synonym/hive_reader/spark_reader.py` (per contracts/hive_read_v1.md;生产 PySpark Catalog + 敏感列剔除 + etl_dt filter + SchemaDriftError 处理)
- [ ] T045 [P] [US1] Implement `PyHiveReader` in `agent-platform/training-data-synonym/training_data_synonym/hive_reader/pyhive_reader.py` (备选后端,无 Spark 环境)
- [ ] T046 [US1] Implement `EnrichmentPipeline` orchestrator in `agent-platform/training-data-synonym/training_data_synonym/enricher/pipeline.py` (编排:tables_meta → HiveReader.read_all_three_core → 增量指纹比对 → 6 维 llm_enricher 并行 + distance_geo + consumable_mapper → writer)
- [ ] T047 [P] [US1] Implement `tables_meta.json` writer in `agent-platform/training-data-synonym/training_data_synonym/enricher/tables_meta_writer.py` (per data-model.md §实体 1;overwrite)
- [ ] T048 [US1] Implement Stage 1 CLI subcommand in `agent-platform/training-data-synonym/training_data_synonym/cli.py` (`enrich` + `tables-meta` + `--source hive|mock` + `--n-items-per-type` + `--etl-dt-mode` 参数)
- [ ] T049 [US1] Wire `summary.json` partial in `agent-platform/training-data-synonym/training_data_synonym/common/summary.py` (Stage 1 字段:items_processed / llm_calls / dict_pass_rate / coverage / sc_pass)

**Checkpoint**: User Story 1 complete — `python -m training_data_synonym.cli enrich --source mock` 跑通,SC-001/002/003 全绿。

---

## Phase 4: User Story 2 — Stage 2 SFT 多轮对话语料生成 (Priority: P1)

**Goal**: 基于 Stage 1 输出生成最多 5 轮 SFT 训练样本;每 item 8 条样本合并覆盖全部非 null 维;`distance` / `order_by` 字典直采,与 lng/lat 解耦。

**Independent Test**: `python -m training_data_synonym.cli sft --input item_tags.jsonl --count-per-item 8` 产出 `sft_corpus.jsonl` ≥ 1600 行,SC-004/005/006/007 自动化断言绿(JSONL 解析 100%、单 item 全维覆盖 100%、负样本 10% ±2%、首句模板 ≤ 20%)。

### Tests for User Story 2 ⚠️ Write FIRST, ensure FAIL before implementation

- [ ] T050 [P] [US2] Contract test for `sft_corpus_v2.jsonl` schema in `agent-platform/training-data-synonym/tests/contract/test_sft_corpus_schema.py` (per contracts/sft_corpus_v2.md §字段详解 + 8 维顺序 + negative_type 不变式)
- [ ] T051 [P] [US2] Contract test for `param_op_types_v2` in `agent-platform/training-data-synonym/tests/contract/test_param_op_types.py` (8 维 × 4 op 映射 + 字典校验 7 步 + v1→v2 兼容降级)
- [ ] T052 [P] [US2] Unit test for `distance_sampler` in `agent-platform/training-data-synonym/tests/unit/sft/test_distance_sampler.py` (per FR-013b;`distance_param_ratio` / 4 桶等权 / `order_by` 5 类 / 双向耦合概率)
- [ ] T053 [P] [US2] Unit test for `negative_sampler` in `agent-platform/training-data-synonym/tests/unit/sft/test_negative_sampler.py` (per FR-013;3 类(reject/pivot/unsatisfiable)+ `negative_ratio=0.10` ±0.02)
- [ ] T054 [P] [US2] Unit test for `diversity` in `agent-platform/training-data-synonym/tests/unit/sft/test_diversity.py` (per FR-014;首句 n-gram 同模板占比 ≤ 20% + 5~8 套句式骨架)
- [ ] T055 [P] [US2] Unit test for `intent_assigner` in `agent-platform/training-data-synonym/tests/unit/sft/test_intent_assigner.py` (per FR-015/016;5 类 intent + 三品类倾向 + 每类占比 ≥ 3%)
- [ ] T056 [P] [US2] Unit test for `sample_planner` in `agent-platform/training-data-synonym/tests/unit/sft/test_sample_planner.py` (per FR-011;单 item N 条样本合并覆盖全部非 null 维 + `forced_coverage` 兜底)
- [ ] T057 [P] [US2] Unit test for `validator` in `agent-platform/training-data-synonym/tests/unit/sft/test_validator.py` (8 维字典校验 + messages 长度 [1,5] + `negative=true` ⇔ `negative_type` 非 null)
- [ ] T058 [P] [US2] Unit test for `llm_generator` in `agent-platform/training-data-synonym/tests/unit/sft/test_llm_generator.py` (ground-truth 注入对齐 + 距离表述 ↔ bucket 反向检测)
- [ ] T059 [P] [US2] Integration test for Stage 2 end-to-end in `agent-platform/training-data-synonym/tests/integration/test_stage2_end_to_end.py` (50 item × 8 sample → SC-004/005/006/007 全绿)

### Implementation for User Story 2

- [ ] T060 [P] [US2] Implement `SFTSample / MessageTurn / ParamSpec` dataclasses in `agent-platform/training-data-synonym/training_data_synonym/sft/sample.py` (per data-model.md §实体 6,7,8)
- [ ] T061 [P] [US2] Implement `distance_sampler` in `agent-platform/training-data-synonym/training_data_synonym/sft/distance_sampler.py` (per FR-013b;`distance_param_ratio` + 4 桶直采 + `order_by` 5 类 + 双向耦合概率约束)
- [ ] T062 [P] [US2] Implement `negative_sampler` in `agent-platform/training-data-synonym/training_data_synonym/sft/negative_sampler.py` (per FR-013;3 类 + `op=not_in` for reject + `order_by=null`)
- [ ] T063 [P] [US2] Implement `diversity` in `agent-platform/training-data-synonym/training_data_synonym/sft/diversity.py` (per FR-014;句式模板随机 + n-gram 检测 + `temperature += 0.1` 重试)
- [ ] T064 [P] [US2] Implement `intent_assigner` in `agent-platform/training-data-synonym/training_data_synonym/sft/intent_assigner.py` (per FR-015/016;5 类 + item_type 倾向 + 占比下限 + 长尾过采样)
- [ ] T065 [US2] Implement `sample_planner` in `agent-platform/training-data-synonym/training_data_synonym/sft/sample_planner.py` (per FR-011;`count_per_item` 默认 8 + 剩余维度跟踪 + `forced_coverage` 兜底追加)
- [ ] T066 [US2] Implement `validator` in `agent-platform/training-data-synonym/training_data_synonym/sft/validator.py` (8 维字典校验 + `negative_type` 不变式 + messages 长度 + control char / tab 拒绝)
- [ ] T067 [US2] Implement `llm_generator` in `agent-platform/training-data-synonym/training_data_synonym/sft/llm_generator.py` (per research.md D-011;ground-truth 注入 + `sft_v1.txt` prompt + DistanceAlignmentError 触发)
- [ ] T068 [US2] Implement `sft_failures` writer in `agent-platform/training-data-synonym/training_data_synonym/sft/failures.py` (per contracts/sft_corpus_v2.md §失败样本 schema;含 `target_params`)
- [ ] T069 [US2] Implement `writer` for `sft_corpus_v2.jsonl` in `agent-platform/training-data-synonym/training_data_synonym/sft/writer.py` (固定 8 维 params 顺序 + `_format_version = sft_corpus_v2` + `covered_dims` 累计)
- [ ] T070 [US2] Implement `SFTPipeline` orchestrator in `agent-platform/training-data-synonym/training_data_synonym/sft/pipeline.py` (sample_planner → distance_sampler → negative_sampler → diversity → intent_assigner → llm_generator → validator → writer,支持增量 `sft_state.parquet`)
- [ ] T071 [US2] Implement Stage 2 CLI subcommand in `agent-platform/training-data-synonym/training_data_synonym/cli.py` (`sft` + `--input` + `--count-per-item` + `--max-message-turns` + `--turn-distribution` + `--negative-ratio` + `--llm-source`)
- [ ] T072 [US2] Wire `summary.json` Stage 2 fields in `agent-platform/training-data-synonym/training_data_synonym/common/summary.py` (sft_total / sft_failures / forced_coverage_count / 8 维非 null 比例 / 5 轮分布)

**Checkpoint**: User Story 2 complete — `python -m training_data_synonym.cli sft` 跑通,SC-004/005/006/007 全绿;与 US1 端到端串联可输出 8 维 ground-truth 训练样本。

---

## Phase 5: User Story 3 — 训练/验证/测试集划分 (Priority: P2)

**Goal**: 把 SFT 语料按 `item_id` md5 hash 划 80/10/10,接清洗 → 分布统计 → 划分的完整后处理。

**Independent Test**: `python -m training_data_synonym.cli split` 产出 3 文件,体量比 80/10/10 ±2%,且 `item_id` 不跨集合(SC-009 0 泄露)。

### Tests for User Story 3 ⚠️ Write FIRST, ensure FAIL before implementation

- [ ] T073 [P] [US3] Contract test for split integrity in `agent-platform/training-data-synonym/tests/contract/test_split_integrity.py` (0 泄露自检 + 比例 ±2% + `_format_version=train_split_v1`)
- [ ] T074 [P] [US3] Unit test for `cleaner` 7 类规则 in `agent-platform/training-data-synonym/tests/unit/postprocess/test_cleaner.py` (per FR-017;text_hash 去重 / 消息过短 / 模板降频 / params 全 null / 控制字符 / 字段白名单 / 轮次异常)
- [ ] T075 [P] [US3] Unit test for `distribution` 8 项指标 in `agent-platform/training-data-synonym/tests/unit/postprocess/test_distribution.py` (per FR-018;intent / params / op / negative / 轮次 / 消息长度 / 字典覆盖率 / params 组合多样性)
- [ ] T076 [P] [US3] Unit test for `balancer` in `agent-platform/training-data-synonym/tests/unit/postprocess/test_balancer.py` (per FR-018;长尾 <3% 过采样 2x + 不平衡度 >5x 报警)
- [ ] T077 [P] [US3] Unit test for `splitter` in `agent-platform/training-data-synonym/tests/unit/postprocess/test_splitter.py` (per FR-019;`item_id` md5 hash 划分 + 0 泄露校验)
- [ ] T078 [P] [US3] Integration test for full pipeline end-to-end in `agent-platform/training-data-synonym/tests/integration/test_pipeline_end_to_end.py` (per quickstart.md 场景 5;50 item × 8 sample,SC-001~SC-011 全绿)

### Implementation for User Story 3

- [ ] T079 [P] [US3] Implement `DistributionReport` dataclass + analyzer in `agent-platform/training-data-synonym/training_data_synonym/postprocess/distribution.py` (per data-model.md §实体 9 + FR-018;8 项指标 + consumable_type 子指标 + `warnings`)
- [ ] T080 [P] [US3] Implement `cleaner` 7 类规则 in `agent-platform/training-data-synonym/training_data_synonym/postprocess/cleaner.py` (per FR-017 + contracts/sft_corpus_v2.md §清洗规则;text_hash md5 / 短消息阈值 / n-gram 降频 / 全 null 删 / control char 删 / 白名单 / 轮次异常)
- [ ] T081 [P] [US3] Implement `balancer` 自动过采样 in `agent-platform/training-data-synonym/training_data_synonym/postprocess/balancer.py` (per FR-018;长尾类 2x LLM 改写 + 不平衡度 >5x 报警 + `balancing_failures.jsonl`)
- [ ] T082 [US3] Implement `splitter` in `agent-platform/training-data-synonym/training_data_synonym/postprocess/splitter.py` (per FR-019;`item_id` md5 hash 80/10/10 + 0 泄露校验 + 可配比例)
- [ ] T083 [US3] Implement `summary.json` writer in `agent-platform/training-data-synonym/training_data_synonym/common/summary.py` (聚合两阶段 + 清洗 + 划分;含 SC 自检结果)
- [ ] T084 [P] [US3] Implement `cleaning_failures.jsonl` writer in `agent-platform/training-data-synonym/training_data_synonym/postprocess/cleaner.py` (per FR-017)
- [ ] T085 [P] [US3] Implement `cold_start_items.jsonl` writer in `agent-platform/training-data-synonym/training_data_synonym/enricher/cold_start.py` (Stage 1 后 8 维全 null 的 item 列表)
- [ ] T086 [US3] Implement `verify` CLI subcommand in `agent-platform/training-data-synonym/training_data_synonym/cli.py` (读 summary.json + 各阶段产物,自动对照 SC-001~SC-011,输出 human/json)
- [ ] T087 [US3] Implement `split` CLI subcommand in `agent-platform/training-data-synonym/training_data_synonym/cli.py` (`--input` + `--output-dir` + `--train/val/test-ratio`)
- [ ] T088 [US3] Implement `all` CLI subcommand in `agent-platform/training-data-synonym/training_data_synonym/cli.py` (编排 enrich → sft → split → verify,产出 `summary.json` + `verify_report.json`)
- [ ] T089 [US3] Wire 80/10/10 三文件 `_format_version=train_split_v1` + 0 泄露 assertion in `agent-platform/training-data-synonym/training_data_synonym/postprocess/splitter.py`

**Checkpoint**: User Story 3 complete — `python -m training_data_synonym.cli all` 跑通;SC-001~SC-011 verify 全绿。

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 跨 US 共享的收尾工作。

- [ ] T090 [P] Update `agent-platform/training-data-synonym/docs/ALIGNMENT_cib_o2o.md` 加入 `consumable_type` 段落 + Hive 数据源段落 + `distance` 解耦说明
- [ ] T091 [P] Add `agent-platform/training-data-synonym/scripts/migrate_v1_to_v2.py` v1→v2 迁移工具(per data-model.md §兼容性;`item_tags_v1 → item_tags_v2` + `sft_corpus_v1 → sft_corpus_v2`)
- [ ] T092 [P] Add `agent-platform/training-data-synonym/scripts/demo.sh` 一键 demo 脚本(spawn Stage 1 → Stage 2 → split,~1 min,per quickstart.md)
- [ ] T093 Add CI workflow `.github/workflows/test.yml`(per Constitution Principle III Test-First;`pytest` + `ruff check` + `black --check`,CI 100% 脱机 mock)
- [ ] T094 [P] Add performance benchmark script `agent-platform/training-data-synonym/scripts/benchmark.py`(SC-010 端到端 1 万 item × 8 sample < 90 分钟 验证)
- [ ] T095 [P] Add `agent-platform/training-data-synonym/tests/unit/security/test_sensitive_drop.py`(审计 `HiveReader.read()` 出口必无 sensitive 列;跨 US 守门)
- [ ] T096 [P] Add `agent-platform/training-data-synonym/tests/integration/test_real_spark_hive.py`(可选 / 标 `@pytest.mark.spark` 跳过;生产环境跑通)
- [ ] T097 [P] Add structured logging configuration `agent-platform/training-data-synonym/configs/logging.yaml`(per research.md D-012;每 LLM 调用一行 json:item_id / latency_ms / token_in/out / outcome)
- [ ] T098 [P] Add `agent-platform/training-data-synonym/CHANGELOG.md` v2.4 spec v2.4 / plan v2.4 实施变更记录
- [ ] T099 [P] Run quickstart.md 5 验证场景 in `agent-platform/training-data-synonym/scripts/verify_quickstart.sh` (per quickstart.md;tables-meta / enrich / sft / split / all+verify)
- [ ] T100 Run `/speckit-analyze` post-implementation to detect drift across spec / plan / code

---

## Phase 7: User Story 4 — 字典扩量离线 CLI (Priority: P3) 🛠️ ops (✅ implemented 2026-06-23)

**Goal**: 离线工具 `extract-dictionary` 从 Hive 抽品牌 / 分类候选 → 双阈值聚类 → 频次过滤 → diff 报告,供人工 promote 进权威 yaml。

**Independent Test**: `python -m training_data_synonym.cli extract-dictionary --source mock --frequency-min 1` 产出 `dict_candidates/` 6 个候选文件;`brands_diff.yaml` 含 `_meta` + `added/existing/removed` 三段;Stage 1/2 主流水线产物字节级哈希不变。

### Tests for User Story 4 ⚠️ Write FIRST, ensure FAIL before implementation

- [x] T101 [P] [US4] Unit test for `clean_brand` / `clean_category` (parens / suffix stripping) in `agent-platform/training-data-synonym/tests/unit/test_extract_dictionary.py`
- [x] T102 [P] [US4] Unit test for `levenshtein` + `jaccard_chars` (incl. max_dist early-exit) in `tests/unit/test_extract_dictionary.py`
- [x] T103 [P] [US4] Unit test for `normalize_brands` (merge close variants / freq sort / cross-script NOT merge) in `tests/unit/test_extract_dictionary.py`
- [x] T104 [P] [US4] Unit test for `normalize_categories` in `tests/unit/test_extract_dictionary.py`
- [x] T105 [P] [US4] Unit test for `diff_brands` / `diff_categories` (added/existing/removed partitioning) in `tests/unit/test_extract_dictionary.py`
- [x] T106 [P] [US4] Unit test for end-to-end `extract()` against mock fixtures in `tests/unit/test_extract_dictionary.py`
- [x] T107 [P] [US4] CLI integration test: `python -m training_data_synonym.cli extract-dictionary` produces 6 candidate files in `tests/unit/test_extract_dictionary.py`

### Implementation for User Story 4

- [x] T108 [P] [US4] Implement `clean_brand` / `clean_category` / `levenshtein` / `jaccard_chars` / `RawRow` / `aggregate_raw` / `normalize_brands` / `normalize_categories` / `diff_brands` / `diff_categories` in `agent-platform/training-data-synonym/training_data_synonym/cli/extract_dictionary.py`
- [x] T109 [US4] Implement `extract()` orchestrator + `click` CLI entry in `training_data_synonym/cli/extract_dictionary.py`
- [x] T110 [US4] Wire `extract-dictionary` subcommand into `agent-platform/training-data-synonym/training_data_synonym/cli/__init__.py`

**Checkpoint**: User Story 4 complete — `extract-dictionary` 离线工具就绪,**不污染** Stage 1/2 主流水线。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: 无依赖,可立即开始。
- **Phase 2 (Foundational)**: 依赖 Phase 1;**BLOCKS** 所有 US。
- **Phase 3 (US1)**: 依赖 Phase 2;无依赖其他 US(独立 MVP)。
- **Phase 4 (US2)**: 依赖 Phase 2 + US1 `item_tags.jsonl` schema(契约依赖,非代码 import 依赖 — US2 reader 校验 `_format_version=item_tags_v2`)。
- **Phase 5 (US3)**: 依赖 Phase 2 + US1 + US2(`split` 读 `sft_corpus.jsonl`);可与 US2 末期并行。
- **Phase 6 (Polish)**: 依赖所有目标 US 完成。

### User Story Dependencies(独立性)

- **US1 (P1, MVP)**: 独立可测 — 只需 mock fixtures + mock LLM。
- **US2 (P1)**: 契约依赖 US1 schema,但代码 import 不反向(`sft_corpus_v2.jsonl` reader 单独维护);可独立 mock 测试。
- **US3 (P2)**: 实际读取 US1 + US2 产物;但集成测可单独构造 mock `sft_corpus.jsonl` 验证 splitter / cleaner。

### Within Each User Story

1. 测试先行(⚠️ 标记)→ 必须先红后绿。
2. dataclass → parser/reader → service → writer → orchestrator → CLI。
3. 单元测试与契约测试可并行开发。
4. 集成测试最后跑(端到端验证 SC)。

### Parallel Opportunities

- Phase 1 所有 `[P]` 任务可并行(不同文件)。
- Phase 2 中 T012/T013/T017/T021/T022/T023/T024/T025/T026 可并行;T014/T015/T016/T018/T019/T020 是 Foundational 关键路径,须串行。
- US1 测试组(T027~T036)全部 `[P]` 可并行;实施组 T037~T039 / T041/T042/T043/T045/T047/T048 / T049 可并行,T040/T044/T046 是关键路径。
- US2 测试组(T050~T059)全部 `[P]` 可并行;实施组 T060~T064 / T068/T069 可并行,T065~T067/T070/T071 是关键路径。
- US3 测试组(T073~T078)全部 `[P]` 可并行;实施组 T079~T081/T084/T085 可并行,T082/T083/T086~T089 是关键路径。

---

## Parallel Execution Examples

### Phase 2 Foundational(关键路径 + 旁路并行)

```bash
# Critical path (串行)
T014 SqlParser → T015 HiveReadSpec → T016 HiveReader ABC

# Parallel side-quests
T012 Data model dataclasses
T013 ParamSpec validator
T017 MockHiveReader
T018 Seed fixtures
T019 Structured logging
T020 Config loader
T021 LLMClient
T022 Versioning constants
T023 Exception hierarchy
T024 dim_dictionary.yaml
T025 consumable_type_map.yaml
T026 pipeline.yaml
```

### User Story 1 (Stage 1)

```bash
# All US1 tests in parallel
T027 contract test item_tags_v2
T028 contract test hive_read_v1
T029 unit test sql_parser
T030 unit test mock_reader
T031 unit test distance_geo
T032 unit test consumable_mapper
T033 unit test tag_schema
T034 unit test state
T035 unit test llm_enricher
T036 integration test stage1 end-to-end

# Implementation critical path
T037 TagSource/ItemTags dataclass
T014 (done in Phase 2) sql_parser
T046 EnrichmentPipeline orchestrator
T044 SparkHiveReader (or T017 MockHiveReader for CI)
T040 llm_enricher
T039 distance_geo
T038 consumable_mapper
T043 writer
T048 CLI subcommand
```

### User Story 2 (Stage 2)

```bash
# All US2 tests in parallel
T050 contract test sft_corpus_v2
T051 contract test param_op_types_v2
T052~T058 unit tests (8 个并行)
T059 integration test stage2 end-to-end

# Implementation critical path
T060 SFTSample/MessageTurn/ParamSpec dataclass
T065 sample_planner → T067 llm_generator → T066 validator
T061 distance_sampler (per FR-013b)
T070 SFTPipeline orchestrator
T069 writer
T071 CLI subcommand
```

---

## Implementation Strategy

### MVP First (User Story 1 Only — Stage 1)

1. ✅ Phase 1: Setup (T001~T011)
2. ✅ Phase 2: Foundational (T012~T026)
3. ✅ Phase 3: US1 (T027~T049) — Stage 1 标签补全
4. **STOP & VALIDATE**: `python -m training_data_synonym.cli enrich --source mock --n-items-per-type 50` 产出 ≥ 100 行 `item_tags.jsonl`;SC-001/002/003 全绿。
5. **Deploy/Demo**: 下游可提前消费 8 维标签(后续 Stage 2 不阻塞)。

### Incremental Delivery

1. Phase 1 + Phase 2 → Foundation ready。
2. + US1 → 8 维标签数据, **MVP 1** (标签补全独立可用)。
3. + US2 → SFT 训练样本, **MVP 2** (核心交付)。
4. + US3 → 80/10/10 划分, **MVP 3** (端到端)。
5. + Polish (Phase 6) → CI + benchmark + 文档 + v1→v2 迁移。

### Parallel Team Strategy

3 名开发者 + 1 名 reviewer:

1. **D1 / D2 / D3** 共同 Phase 1 + Phase 2 (1-2 天)。
2. Phase 2 完成 → 分流:
   - **D1**: US1 全栈(T027~T049)
   - **D2**: US2 全栈(T050~T072)
   - **D3**: US3 全栈(T073~T089)
3. **Reviewer**: US1 完成时 review → MVP 1 demo;US2 完成时 review → MVP 2 demo;US3 完成时 review → MVP 3 demo。
4. Phase 6 Polish 单人串行(D1)。

---

## Notes

- `[P]` 任务 = 不同文件,无依赖;同一 US 内同一文件 / 同一模块的任务不可标 `[P]`。
- `[Story]` 标签 = spec.md 的 US1 / US2 / US3(Stage 1 / Stage 2 / Split)。
- 每个 US 应独立可测 — 即用 mock fixtures + mock LLM 端到端跑通。
- 测试先行(⚠️ 标记) — 必须先红后绿;每个 FR 至少 1 个 unit + 1 个 contract。
- 提交节奏:每 task 或每逻辑组 1 commit。
- 在任何 checkpoint 停下独立验证 US。
- 避免:跨 US 反向 import、模糊任务描述、同文件冲突。

---

## Task Count Summary

| Phase | Tasks | Notes |
|-------|-------|-------|
| Phase 1 Setup | 11 (T001~T011) | package skeleton + 配置 + prompt + linting |
| Phase 2 Foundational | 15 (T012~T026) | data model + Hive reader 抽象 + mock + LLM 抽象 + dict yamls |
| Phase 3 US1 (Stage 1) | 23 (T027~T049) | 10 tests + 13 impls |
| Phase 4 US2 (Stage 2) | 23 (T050~T072) | 10 tests + 13 impls |
| Phase 5 US3 (Split) | 17 (T073~T089) | 6 tests + 11 impls |
| Phase 6 Polish | 11 (T090~T100) | docs + CI + benchmark + migration |
| **Phase 7 US4** | **10 (T101~T110)** | **字典扩量离线 CLI**(`extract-dictionary`);已实现 |
| **Total** | **110 tasks** | 100 from plan + 10 for US4 |

---

## Changelog

| Version | Date | Notes |
|---------|------|-------|
| v1 | 2026-06-14 | 初版:140 个任务,基于 v1 spec(7 维味标签)。 |
| v2 | 2026-06-22 | 重写对齐 spec v2.4 + plan v2.4 + 4 张 v2 契约:Stage 1 Hive 直读 / 8 维 / `distance` 透传 / `consumable_type` 映射 / SFT 字典直采;100 个任务按 6 phase 重组;每任务附 file path,可直接交给 LLM 执行。 |
| **v2.5** | 2026-06-23 | 新增 Phase 7 US4 字典扩量离线 CLI(T101~T110,10 个任务,已全部完成):`extract-dictionary` 离线工具与 Stage 1/2 主流水线解耦;tasks.md 总数 100 → 110。 |