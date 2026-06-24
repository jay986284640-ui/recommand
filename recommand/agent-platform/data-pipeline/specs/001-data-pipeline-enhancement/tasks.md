# Tasks: 数据处理管线增强

**Branch**: `001-data-pipeline-enhancement` | **Date**: 2026-06-14
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Project**: `agent-platform/data-pipeline/`

> 任务按 Spec Kit 规范:先测试后实现,每任务标 US、并发友好标 [P]。
> **不动现有代码**:只追加新模块 + 改 writer 输出格式 + 加配置开关。

---

## 总览

| 任务段 | 任务数 | 测试 | 实现 |
|--------|--------|------|------|
| Phase 1: Setup | 4 | 0 | 4 |
| Phase 2: Foundational | 6 | 0 | 6 |
| US2 (P1) JSONL 输出 | 10 | 5 | 5 |
| US1 (P1) AI 特征增强(含 party_size 第 7 维) | 23 | 12 | 11 |
| US3 (P2) 实时特征处理 | 20 | 10 | 10 |
| Phase 6: Polish | 8 | 2 | 6 |
| **总任务数** | **71** | **29 (41%)** | **42** |

| 用户故事 | 任务数 |
|----------|--------|
| US1 (P1) AI 特征增强(6 维 + 1 维 party_size) | 23 |
| US2 (P1) JSONL 输出 | 10 |
| US3 (P2) 实时特征处理 | 20 |
| no-story (Setup/Foundational/Polish) | 18 |

**MVP 范围** = Phase 1 + Phase 2 + US2 + US1 = **43 任务**

---

## 依赖图(用户故事完成顺序)

```
Phase 1 Setup (T001~T004)
   ↓
Phase 2 Foundational (T005~T010)  ← 共享 Config 段 / writers / Spark 双 session
   ↓
   ├── US2 (P1) JSONL 输出 (T011~T020)
   │      ↓
   │   ├── US1 (P1) AI 特征增强 (T021~T038)   ← 复用 writers/jsonl_writer
   │      ↓
   │   └── US3 (P2) 实时特征处理 (T039~T058)   ← 复用 writers/jsonl_writer
   ↓
Phase 6 Polish (T059~T066)
```

---

## Phase 1: Setup(项目结构)

- [ ] T001 [P] 创建 `feature_extraction/ai_enhance/` 子包(`__init__.py` + 子目录)
- [ ] T002 [P] 创建 `streaming/` 子包(`__init__.py` + 子目录)
- [ ] T003 [P] 创建 `configs/prompts/` 子目录
- [ ] T004 [P] 创建 `tests/feature_extraction/ai_enhance/` 与 `tests/streaming/` 测试子包

---

## Phase 2: Foundational(共享基础设施)

> 这一阶段没有独立用户故事,但所有 US 都依赖。**先**写配置加载 + jsonl 写入器骨架。

- [ ] T005 [P] 在 `common/config_loader.py` 增加 `AiEnhanceConfig` dataclass(enabled / mode / batch_size / llm_timeout_seconds / llm_temperature / model / prompt_template / state_path / failures_path),见 spec.md §FR-001~FR-003
- [ ] T006 [P] 在 `common/config_loader.py` 增加 `StreamingConfig` dataclass(enabled / kafka_bootstrap / topic / consumer_group / trigger_interval / starting_offset / checkpoint_dir / output_dir / app_name / spark_master / spark_memory),见 spec.md §FR-006~FR-010
- [ ] T007 [P] 在 `common/config_loader.py` 增加 `output_format` 字段到 `FeatureExtractionConfig`,默认 `jsonl`
- [ ] T008 [P] 创建 `writers/jsonl_writer.py`:`write_dataframe_jsonl(df, output_dir, name, mode='overwrite')` 用 `.write.text()` + UDF 序列化,字段顺序固定
- [ ] T009 [P] 创建 `configs/prompts/ai_enhance_v1.txt`:**7 维** prompt 模板(系统提示 + 用户模板 `{title}` / `{description}` / `{content_type}` + 输出格式要求 + 字典子集约束 + **`party_size` 推断规则与 5 桶示例**),见 spec.md §FR-001, §FR-001a, §6.1
- [ ] T010 [P] 创建 `configs/tag_dictionary.yaml`:**7 维**字典(味/场/材/域/人/情/**就**),见 spec.md §6.1 取值表

---

## US2 (P1) — JSONL 输出格式

**Story Goal**:把 5 类特征 writer 统一为 jsonl,100% 可被 `jq -c .` 解析
**Independent Test**:跑完 `run_feature_extraction.py` 后,`features/*.jsonl` 全部能用 `jq -c .` 解析(SC-004),`features/*.parquet` 为空(SC-005)

### Tests for User Story 2

- [ ] T011 [P] [US2] 单元测试:jsonl_writer 写出的每行是合法 JSON,无 nan / inf,None → null,在 `tests/writers/test_jsonl_writer.py` (SC-004)
- [ ] T012 [P] [US2] 单元测试:jsonl_writer 字段顺序固定(业务字段在前,衍生字段在后),在 `tests/writers/test_jsonl_writer_field_order.py` (FR-005)
- [ ] T013 [P] [US2] 单元测试:jsonl_writer 处理 struct / array 嵌套(用 `user_interaction_history` 测 sequence),在 `tests/writers/test_jsonl_writer_nested.py` (FR-005)
- [ ] T014 [P] [US2] 单元测试:item_features writer 走 jsonl 分支产出 `item_features/`,在 `tests/feature_extraction/test_item_features_writer.py` (FR-004)
- [ ] T015 [P] [US2] 集成测试:跑完 `feature_extraction/pipeline.FeatureExtractionPipeline` 后目录里无 parquet(SC-005),在 `tests/feature_extraction/test_jsonl_pipeline.py`

### Implementation for User Story 2

- [ ] T016 [US2] 改 `feature_extraction/pipeline.py` `_write` 方法:根据 `config.feature_extraction.output_format` 路由到 `write_dataframe_jsonl` / 旧 parquet 路径(FR-004)
- [ ] T017 [US2] 改 `writers/feature_writer.py` 增加 `format='jsonl'` 分支调 `write_dataframe_jsonl`
- [ ] T018 [US2] 改 `common/config_loader.py` 默认 `FeatureExtractionConfig.output_format = "jsonl"`,文档中说明变更
- [ ] T019 [US2] 改 `configs/datasets/*.yaml` 增加 `feature_extraction.output_format: jsonl`
- [ ] T020 [US2] 端到端:在 `tests/e2e/test_pipeline_jsonl.py` 跑 `run_pipeline.py` 验证 5 类 jsonl 全部产出(SC-004, SC-005)

---

## US1 (P1) — AI 辅助特征增强

**Story Goal**:用 LLM 从 item_title/description 抽取 6 维标签,全量 + 增量两种模式
**Independent Test**:100 个 item 全量跑批 < 10 分钟(SC-001);增量模式 1% 增量 < 1 分钟(SC-002);失败率 < 1%(SC-003)

### Tests for User Story 1

- [ ] T021 [P] [US1] 单元测试:prompt 模板加载 + 字段注入(title / description / content_type),在 `tests/feature_extraction/ai_enhance/test_prompt.py` (FR-001)
- [ ] T022 [P] [US1] 单元测试:tag_dictionary 解析 + 7 维候选值集合约束(含 party_size 5 桶),在 `tests/feature_extraction/ai_enhance/test_tag_schema.py` (FR-001, FR-001b)
- [ ] T023 [P] [US1] 单元测试:LLM 客户端重试 + 超时(模拟 mock-llm 第 1 次失败,第 2 次成功),在 `tests/feature_extraction/ai_enhance/test_llm_client.py` (FR-003)
- [ ] T024 [P] [US1] 单元测试:LLM 返回非 JSON → 写 failures + 继续,在 `tests/feature_extraction/ai_enhance/test_llm_client_parse_fail.py` (FR-003)
- [ ] T025 [P] [US1] 单元测试:incremental 模式按 md5 指纹去重,在 `tests/feature_extraction/ai_enhance/test_enhancer_incremental.py` (FR-002)
- [ ] T026 [P] [US1] 单元测试:full 模式覆盖 state,在 `tests/feature_extraction/ai_enhance/test_enhancer_full.py` (FR-002)
- [ ] T027 [P] [US1] 单元测试:enhancer 写 `item_features_ai.jsonl` schema 与 spec §6.1 一致(含 `party_size` 字段),在 `tests/feature_extraction/ai_enhance/test_enhancer_output.py` (FR-001, FR-001a)
- [ ] T028 [P] [US1] 单元测试:enhancer 失败降级(LLM 整体挂)→ 写空标签(含 party_size="") + 退出非 0,在 `tests/feature_extraction/ai_enhance/test_enhancer_degradation.py` (FR-003)
- [ ] T029 [P] [US1] 性能测试:100 items 全量 < 10min(SC-001),在 `tests/feature_extraction/ai_enhance/test_perf_full.py`
- [ ] T029a [P] [US1] **party_size 专项** — 规则推断单元测试:title 含"双人套餐"→ 2 / "家庭装"→ 3-4 / "1 人食"→ 1,在 `tests/feature_extraction/ai_enhance/test_party_size_rules.py` (FR-001a, D-013)
- [ ] T029b [P] [US1] **party_size 专项** — LLM 兜底推断单元测试:description 含"按位"自助餐 → LLM 推断 1,在 `tests/feature_extraction/ai_enhance/test_party_size_llm_fallback.py` (FR-001a, D-013)
- [ ] T029c [P] [US1] **party_size 专项** — 桶归一单元测试:LLM 输出"2 人"/"两人"/"double"全部归一为 `"2"`,在 `tests/feature_extraction/ai_enhance/test_party_size_normalize.py` (D-014)
- [ ] T029d [P] [US1] **party_size 专项** — SC-010/011 验证:50 个混合 items 跑完,party_size 填充率 ≥ 95% + 100% 在 5 桶内,在 `tests/feature_extraction/ai_enhance/test_party_size_sc.py` (SC-010, SC-011)

### Implementation for User Story 1

- [ ] T030 [P] [US1] 实现 `feature_extraction/ai_enhance/tag_schema.py`:`TAG_DICTIONARY` 常量(**7 维**)+ `load_dictionary(path)` + `validate_tags(tags)` + `validate_party_size(value)`(FR-001, FR-001b)
- [ ] T031 [P] [US1] 实现 `feature_extraction/ai_enhance/prompt.py`:`load_prompt(path) -> PromptTemplate` + `render(title, description, content_type) -> messages`,**prompt 含 party_size 推断规则与 5 桶示例**(FR-001, FR-001a)
- [ ] T032 [US1] 实现 `feature_extraction/ai_enhance/llm_client.py`:`LLMClient` 类(批量 asyncio + semaphore=10 + 重试 + 超时 + 降级),对接大模型平台(FR-001, FR-003)
- [ ] T033 [US1] 实现 `feature_extraction/ai_enhance/state.py`:`EnhanceState` 类(读 / 写 / 增量比对 md5 指纹,持久化 parquet),见 spec.md §FR-002
- [ ] T033a [P] [US1] 实现 `feature_extraction/ai_enhance/party_size.py`:`PartySizeInferrer` 类,实现 **规则优先 + LLM 兜底 + 桶归一** 融合(D-013, D-014, FR-001a)
  - 规则表:title/description 正则匹配 → 桶(`1` / `2` / `3-4` / `5-8` / `9+`)
  - 规则无命中 → 调 LLMClient 走 prompt 推断
  - LLM 输出桶外值 → `normalize_to_bucket()` 归一(2 人 / 两人 / double / 2 → `2`)
  - LLM 仍失败 → 返回 `""`(空字符串)
- [ ] T034 [US1] 实现 `feature_extraction/ai_enhance/enhancer.py`:`AIEnhancer` 类(全量 / 增量模式调度,调用 LLMClient + PartySizeInferrer + 写失败日志),见 spec.md §FR-001, §FR-001a, §FR-002, §FR-003
- [ ] T035 [US1] 实现 `feature_extraction/ai_enhance/pipeline.py`:`AIEnhancePipeline` 编排 6 步:加载 items → 计算指纹 → 增量比对 → 批量 LLM(7 维)→ 解析 → 写 jsonl(FR-001~FR-003, FR-001a, FR-001b)
- [ ] T036 [US1] 实现 `run_ai_enhance.py` 入口:`--mode=full|incremental --batch-size=N --config=...` (FR-002, FR-003)
- [ ] T037 [US1] 改 `run_pipeline.py` 增加 `--skip-ai-enhance` 开关(默认开启)
- [ ] T038 [US1] 集成测试:用 mock-llm 跑 50 items,验证 `item_features_ai.jsonl` 行数 = 50,**7 维**字段齐全 + party_size 字段填充率 ≥ 95%,在 `tests/feature_extraction/ai_enhance/test_integration.py` (SC-003, SC-010)

---

## US3 (P2) — 实时特征处理

**Story Goal**:Kafka → Spark Streaming 微批(3-5min)→ 更新 user_interaction_history + user_features
**Independent Test**:塞 1 条 Kafka 事件,3-5 分钟后 2 个 jsonl 都有新条目(SC-006, SC-009)

### Tests for User Story 3

- [ ] T039 [P] [US3] 单元测试:RealtimeEvent schema 解析(用 jsonschema),在 `tests/streaming/test_event_schema.py` (FR-006, spec §6.2)
- [ ] T040 [P] [US3] 单元测试:dedup 按 event_id 去重(同事件被 producer 重发只计 1 次),在 `tests/streaming/test_dedup.py` (spec §9 负面场景)
- [ ] T041 [P] [US3] 单元测试:kafka_consumer 起始 offset 配置生效,在 `tests/streaming/test_kafka_consumer.py` (FR-006)
- [ ] T042 [P] [US3] 单元测试:interaction_updater 追加(不重写历史),在 `tests/streaming/test_interaction_updater.py` (FR-008)
- [ ] T043 [P] [US3] 单元测试:user_feature_updater upsert 行为(同 user_id 多次 → interaction_count 累加、last_seen_ts 取大),在 `tests/streaming/test_user_feature_updater.py` (FR-008)
- [ ] T044 [P] [US3] 单元测试:checkpoint 目录状态读 / 写,在 `tests/streaming/test_checkpoint.py` (FR-009)
- [ ] T045 [P] [US3] 单元测试:流任务空批(无 Kafka 事件)不报错且不写空文件,在 `tests/streaming/test_pipeline_empty.py` (spec §7 FR-007)
- [ ] T046 [P] [US3] 集成测试:用 Testcontainers Kafka 启动一个 topic,塞 3 条事件,验证 3 分钟后 jsonl 有对应条目,在 `tests/streaming/test_integration_kafka.py` (SC-006, SC-007)
- [ ] T047 [P] [US3] 故障恢复测试:流任务跑 1 批后 kill -9,重启从 checkpoint 续读不丢事件,在 `tests/streaming/test_integration_resume.py` (SC-007, SC-009)
- [ ] T048 [P] [US3] 资源隔离测试:流任务与离线批同时跑,各自 Spark UI 独立,资源不互相饿死,在 `tests/streaming/test_integration_isolation.py` (SC-008)

### Implementation for User Story 3

- [ ] T049 [P] [US3] 实现 `streaming/__init__.py` + `streaming/event_schema.py`:`RealtimeEvent` dataclass + jsonschema 校验(FR-006, spec §6.2)
- [ ] T050 [US3] 实现 `streaming/kafka_consumer.py`:`KafkaConsumer` 封装 Spark Structured Streaming `readStream.format("kafka")` + 配置(FR-006)
- [ ] T051 [US3] 实现 `streaming/dedup.py`:`dedup_by_event_id(stream_df, state_dir)` 用 groupBy + first,模拟流式状态去重(FR-006 + spec §9)
- [ ] T052 [US3] 实现 `streaming/interaction_updater.py`:`update_user_interaction_history(batch_df, batch_id, output_path)` 用 foreachBatch + 临时 parquet + atomic rename,append 模式(FR-008)
- [ ] T053 [US3] 实现 `streaming/user_feature_updater.py`:`update_user_features(batch_df, batch_id, output_path)` foreachBatch 内 drop-and-rewrite(upsert 语义)(FR-008)
- [ ] T054 [US3] 实现 `streaming/checkpoint.py`:`get_checkpoint_health(checkpoint_dir)` 读 Spark metadata,验证 offset 连续(FR-009, SC-009)
- [ ] T055 [US3] 实现 `streaming/pipeline.py`:`StreamingPipeline.run(spark)` 编排:read → dedup → foreachBatch 双写 → checkpoint 维护(FR-006~FR-010)
- [ ] T056 [US3] 实现 `run_streaming.py` 入口:`--config=...`,独立 SparkSession,trigger=3min,常驻运行(FR-007, FR-010)
- [ ] T057 [US3] 改 `common/spark_manager.py` 支持"独立 SparkSession"(不强制单例,显式 new_session 开关)
- [ ] T058 [US3] 加 Kafka lag / 流延迟 / checkpoint 滞后 3 个 Prometheus 指标(FR-009 间接,spec §7 SC-006)

---

## Phase 6: Polish & Cross-Cutting

- [ ] T059 [P] 更新根 `agent-platform/data-pipeline/README.md` 加 3 个新能力的章节(JSONL / AI 增强 / 实时流)+ 拓扑图
- [ ] T060 [P] 更新 `agent-platform/data-pipeline/requirements.txt` 加 `jsonschema`(可选)
- [ ] T061 端到端集成测试:在 `tests/e2e/test_full_pipeline_with_ai_and_streaming.py` 跑完整流程(批 + AI 增强 + 流),10 min 内完成(SC-001, SC-006)
- [ ] T062 [P] 性能基线脚本:`scripts/benchmark_pipeline.py` 测 100 items 全量 AI + 1000 事件流的总耗时,作为回归门
- [ ] T063 [P] 文档:在 `agent-platform/data-pipeline/specs/001-data-pipeline-enhancement/contracts/jsonl_format_v1.md` 写 jsonl 通用格式约定
- [ ] T064 [P] 文档:在 `contracts/ai_enhance_output.md` 写 ai_enhance 输出 jsonl schema 详细说明(含 `party_size` 单值字段 + 5 桶约定)
- [ ] T065 [P] 文档:在 `contracts/streaming_event.md` 写 Kafka 事件 schema 详细说明 + producer 端契约
- [ ] T066 [P] 文档:在 `agent-platform/data-pipeline/specs/001-data-pipeline-enhancement/quickstart.md` 写一键跑"批 + AI 增强 + 流"的端到端验证

---

## 任务统计

| Phase / US | 任务数 | 测试 | 实现 |
|------------|--------|------|------|
| Phase 1 Setup | 4 | 0 | 4 |
| Phase 2 Foundational | 6 | 0 | 6 |
| US2 (P1) JSONL | 10 | 5 | 5 |
| US1 (P1) AI 增强(含 party_size) | 23 | 12 | 11 |
| US3 (P2) 实时流 | 20 | 10 | 10 |
| Phase 6 Polish | 8 | 2 | 6 |
| **总任务数** | **71** | **29 (41%)** | **42** |

---

## 并行机会(Phase 1 / Phase 2)

```bash
# Phase 1: 4 个 mkdir 并行
mkdir -p feature_extraction/ai_enhance streaming configs/prompts tests/feature_extraction/ai_enhance tests/streaming

# Phase 2: 6 个配置 / 写出器 / 模板文件全部 [P] 并行
```

---

## 实施策略(增量交付)

1. **Setup + Foundational → Foundation ready**(10 任务,约 1 天)
2. **+ US2 (JSONL) → Test → 验证 jsonl 100% jq 解析**(10 任务,约 1-2 天)
3. **+ US1 (AI 增强) → Test → mock-llm 跑 50 items**(18 任务,约 3-4 天)
4. **+ US3 (实时流) → Test → Testcontainers Kafka 跑 3 事件**(20 任务,约 4-5 天)
5. **+ Phase 6 Polish → 文档 + 端到端基准**(8 任务,约 1 天)

**Total MVP: 66 任务 / 约 10-13 天**

---

## 验证清单(交付门)

- [ ] US1:100 items 全量 < 10min(SC-001),增量 1% < 1min(SC-002),失败 < 1%(SC-003)
- [ ] US1:**party_size 填充率 ≥ 95%**(SC-010)+ 100% 在 5 桶内(SC-011)
- [ ] US1:**party_size 推断对总 LLM 延迟影响 ≤ 5%**(SC-012)
- [ ] US2:`features/*.jsonl` 100% `jq -c .` 解析(SC-004),无 parquet 残留(SC-005)
- [ ] US3:3 条 Kafka 事件 5min 内进 user_interaction_history + user_features(SC-006)
- [ ] US3:Kafka 中间断网 1 分钟后恢复不丢(SC-007)
- [ ] US3:流任务与离线批同跑资源不饿死(SC-008)
- [ ] US3:kill -9 重启从 checkpoint 续读(SC-009)
- [ ] Constitution Check 通过(I~V 五项)
