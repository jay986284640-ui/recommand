# Tasks: 训练数据生成

**Branch**: `002-training-data-generator` | **Date**: 2026-06-14
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Project**: `agent-platform/data-pipeline/`

> 任务按 Spec Kit 规范:先测试后实现,每任务标 US、并发友好标 [P]。
> **不动现有代码**(包括 001 增强管线的 `ai_enhance/` 和 4 步管线主流程);只追加新模块 + 1 个入口 + 改 `common/config_loader.py` 加配置段。

---

## 总览

| 任务段 | 任务数 | 测试 | 实现 |
|--------|--------|------|------|
| Phase 1: Setup | 3 | 0 | 3 |
| Phase 2: Foundational | 5 | 0 | 5 |
| US1 (P1) 训练数据生成(含 清洗/平衡/划分 阶段 2) | 34 | 18 | 16 |
| Phase 3: Polish | 4 | 1 | 3 |
| **总任务数** | **46** | **19 (41%)** | **27** |

| 用户故事 | 任务数 |
|----------|--------|
| US1 (P1) 训练数据生成(LLM 1 段 + 7 维 params + 字典校验 + 多样性 + 负样本 + 清洗 + 平衡 + 划分) | 34 |
| no-story (Setup/Foundational/Polish) | 12 |

**MVP 范围** = Phase 1 + Phase 2 + US1 = **42 任务**

---

## 依赖图(完成顺序)

```
Phase 1 Setup (T001~T003)
   ↓
Phase 2 Foundational (T004~T008)  ← 共享配置 / 子包骨架 / prompt 模板
   ↓
   └── US1 (P1) 训练数据生成 (T009~T030k)
         ├── 阶段 1:LLM 生成 + 字典校验 (T009~T030)
         └── 阶段 2:数据清洗 + 平衡 + 划分 (T030a~T030k)  ← 依赖阶段 1
   ↓
Phase 3 Polish (T031~T034)
```

---

## Phase 1: Setup(项目结构)

- [ ] T001 [P] 创建 `feature_extraction/training_data/` 子包(`__init__.py` + 子目录)
- [ ] T002 [P] 创建 `tests/feature_extraction/training_data/` 测试子包
- [ ] T003 [P] 创建 `configs/prompts/training_data_v1.txt`(空文件占位,Phase 2 填内容)

---

## Phase 2: Foundational(共享基础设施)

> 这一阶段没有独立用户故事,但 US1 全部依赖。**先**写配置加载 + 复用 001 LLMClient + 字典加载。

- [ ] T004 [P] 在 `common/config_loader.py` 增加 `TrainingDataConfig` dataclass(enabled / mode / count_per_item / negative_ratio / max_message_turns / batch_size / timeout_seconds / temperature / model / prompt_template / output_path / failures_path / state_path),见 spec.md §10
- [ ] T005 [P] 在 `feature_extraction/training_data/__init__.py` 暴露 `TrainingDataPipeline`、`TrainingSample`、`ParamSpec` 三个公开符号
- [ ] T006 [P] 创建 `feature_extraction/training_data/llm_client.py`:`TrainingLLMClient` 类(继承 / 复用 001 `ai_enhance.llm_client.LLMClient`),加 `generate_training_sample(ai_features, dialogue_template, negative_type=None) -> dict` 方法,见 plan.md D-001
- [ ] T007 [P] 创建 `feature_extraction/training_data/param_schema.py`:`ParamSpec` dataclass + `OP_TYPES` 7 个常量(`eq` / `contains` / `in` / `not_in` / `gt` / `lt` / `between`)+ `validate_params(params, dictionary) -> (ok, errors)`,见 spec.md §5 FR-002, §6.3
- [ ] T008 [P] 创建 `configs/prompts/training_data_v1.txt`:**对话生成 + 提参 prompt**(系统提示 + 用户模板 `{ai_tags}` / `{dictionary_yaml}` / `{dialogue_template}` / `{negative_instruction}` + 输出 JSON schema 要求 + `op` 类型说明 + 5~8 套句式骨架 + 3 类负样本指令),见 spec.md §FR-001, §FR-005, §FR-006, plan.md D-002, D-003, D-005

---

## US1 (P1) — 训练数据生成

**Story Goal**:LLM 1 段调用产出多轮对话 + 7 维 params + 字典校验 + 多样性 + 负样本,落 `training_data_v1.jsonl`
**Independent Test**:50 items fixture → 400 行输出 + 100% 字典校验(SC-002)+ 100% `jq -c .` 解析(SC-004)+ 负样本 8~12%(SC-007)

### Tests for User Story 1

- [ ] T009 [P] [US1] 单元测试:prompt 模板加载 + 字段注入(ai_tags / dictionary_yaml / dialogue_template / negative_instruction),在 `tests/feature_extraction/training_data/test_prompt.py` (FR-001)
- [ ] T010 [P] [US1] 单元测试:`ParamSpec` 7 个 op 类型序列化 / 反序列化,在 `tests/feature_extraction/training_data/test_param_schema.py` (FR-002, §6.3)
- [ ] T011 [P] [US1] 单元测试:`validate_params()` 7 维字典校验:合法 params → ok / 字典外值 → error / 多余字段 → error / 缺失字段 → null 补齐,通过(SC-002),在 `tests/feature_extraction/training_data/test_param_schema_validate.py`
- [ ] T012 [P] [US1] 单元测试:diversity 句式模板选择(seed=固定 → 结果固定;seed=不同 → 模板不同;100 次随机分布均匀),在 `tests/feature_extraction/training_data/test_diversity.py` (FR-005, SC-005)
- [ ] T013 [P] [US1] 单元测试:diversity 高频模板上限:100 条样本首句 n-gram 统计,最高频模板占比 ≤ 20%(SC-005),在 `tests/feature_extraction/training_data/test_diversity_freq.py`
- [ ] T014 [P] [US1] 单元测试:negative_sampler 3 类(reject / pivot / unsatisfiable)按权重分布,1000 次后比例在 [0.25, 0.45] 内(SC-007),在 `tests/feature_extraction/training_data/test_negative_sampler.py` (FR-006)
- [ ] T015 [P] [US1] 单元测试:state 增量 md5 指纹比对(新增 / 修改 / 未变 item 正确分类),在 `tests/feature_extraction/training_data/test_state.py` (FR-004)
- [ ] T016 [P] [US1] 单元测试:writer 字段顺序固定 + `_format_version: "training_data_v1"` + None → null,在 `tests/feature_extraction/training_data/test_writer.py` (FR-002, SC-004)
- [ ] T017 [P] [US1] 单元测试:pipeline 5 步编排(加载 → 增量比对 → 批量 LLM → 字典校验 → 写 jsonl),在 `tests/feature_extraction/training_data/test_pipeline.py` (FR-001~FR-006)
- [ ] T018 [P] [US1] 单元测试:pipeline 降级路径(LLM 第 1 次失败 → failures;JSON 解析失败 → failures;字典校验失败 → failures;主输出不被污染),在 `tests/feature_extraction/training_data/test_pipeline_degradation.py` (FR-003, SC-003)
- [ ] T019 [P] [US1] 集成测试:mock-llm 跑 50 items → 400 行输出 + 100% 字典校验(SC-002)+ 100% `jq -c .` 解析(SC-004)+ 负样本 8~12%(SC-007),在 `tests/feature_extraction/training_data/test_integration.py`

### Implementation for User Story 1

- [ ] T020 [P] [US1] 实现 `feature_extraction/training_data/prompt.py`:`load_prompt(path) -> PromptTemplate` + `render(ai_tags, dictionary_yaml, dialogue_template, negative_instruction) -> messages`,**prompt 含 5~8 套句式骨架 + 3 类负样本指令 + 7 维字典子集 + `op` 类型说明**,见 spec.md §FR-001, §FR-005, §FR-006, plan.md D-001, D-002, D-003, D-005
- [ ] T021 [P] [US1] 实现 `feature_extraction/training_data/diversity.py`:`DIALOGUE_TEMPLATES` 常量(5~8 套首句骨架,如"我想喝 X" / "X 怎么样" / "推荐个 X" / "附近有 X 吗" / "X 求推荐")+ `pick_template(seed=None) -> str`,见 spec.md §FR-005, plan.md D-007
- [ ] T022 [P] [US1] 实现 `feature_extraction/training_data/negative_sampler.py`:`NEGATIVE_TYPES` 3 个常量(reject / pivot / unsatisfiable)+ 各自 prompt 指令片段 + `sample_negative_type(seed=None) -> str`,见 spec.md §FR-006, plan.md D-005
- [ ] T023 [P] [US1] 实现 `feature_extraction/training_data/state.py`:`TrainingDataState` 类(读 / 写 parquet,`compute_ai_tags_md5(ai_tags) -> str`,`diff_incremental(items) -> (new_items, modified_items)`),见 spec.md §FR-004
- [ ] T024 [US1] 实现 `feature_extraction/training_data/writer.py`:`write_training_data_jsonl(samples, output_path, mode='overwrite')`,字段固定顺序(item_id, intent, messages, params, order_by, negative, generated_at, llm_model, _format_version),None → null,见 spec.md §6.1
- [ ] T025 [US1] 实现 `feature_extraction/training_data/llm_client.py`:`TrainingLLMClient` 类,加 `generate_training_sample()`:调 001 复用 LLMClient + 用 prompt.py 渲染 + `structured output` 模式保证 JSON 合法,见 plan.md D-001
- [ ] T026 [US1] 实现 `feature_extraction/training_data/pipeline.py`:`TrainingDataPipeline.run(spark=None)` 编排 **9 步**:加载 `item_features_ai.jsonl` → 增量 md5 比对 → 批量 LLM 调用(每 item 跑 `count_per_item` 次,负样本按 `negative_ratio` 注入)→ 字典校验 → **清洗(FR-007)→ 分布统计(FR-008)→ 自动平衡(FR-008)→ 划分(FR-009)→ 写 jsonl + 3 split**,见 spec.md §FR-001~FR-009
- [ ] T027 [US1] 实现 `run_training_data.py` 入口:`--mode=full|incremental --count=N --config=... --item-features-ai=PATH --skip-cleaning --skip-balancing --skip-split`,见 spec.md §10, §FR-004
- [ ] T028 [US1] 改 `configs/datasets/*.yaml` 增加 `training_data` 段(默认 enabled=false,需显式开)
- [ ] T029 [US1] 改 `common/config_loader.py` 在主 `Config` dataclass 加 `training_data: TrainingDataConfig` 字段(含 cleaning / balancing / split 三段配置)
- [ ] T030 [P] [US1] 性能基线脚本:`scripts/benchmark_training_data.py` 测 100 items × 8 条 = 800 样本耗时,作为 SC-001 回归门(SC-001)

### 阶段 2:数据清洗(FR-007)

> 在主 pipeline (T026) 跑完 LLM 生成后,接 cleaner/balancer/splitter。

- [ ] T030a [P] [US1] **数据清洗测试** — 单元测试:7 类规则单元测试(text_hash 去重 / 消息过短 / 模板降频 / params 全 null / 控制字符 / 字典外 / 轮次异常),在 `tests/feature_extraction/training_data/test_cleaner.py` (FR-007)
- [ ] T030b [P] [US1] **数据清洗测试** — 单元测试:留存率校验 SC-008(50% < 留存 < 85% → 报警,< 50% → 报警 + exit 1),在 `tests/feature_extraction/training_data/test_cleaner_retention.py` (SC-008)
- [ ] T030c [P] [US1] **数据平衡测试** — 单元测试:8 个分布指标统计 + warnings 列表 + 阈值判断,在 `tests/feature_extraction/training_data/test_distribution.py` (FR-008, SC-009)
- [ ] T030d [P] [US1] **数据平衡测试** — 单元测试:自动过采样(长尾类 < 3% → 复制 + LLM 改写 1 次,共 2x),在 `tests/feature_extraction/training_data/test_balancer.py` (FR-008, D-009)
- [ ] T030e [P] [US1] **数据集划分测试** — 单元测试:按 item_id hash 划分 80/10/10,泄露校验 SC-010,在 `tests/feature_extraction/training_data/test_splitter.py` (FR-009, SC-010)
- [ ] T030f [P] [US1] **数据集划分测试** — 单元测试:val/test 真实数据优先(SC-011),在 `tests/feature_extraction/training_data/test_splitter_real_data.py` (SC-011)
- [ ] T030g [P] [US1] **集成测试升级** — 50 items fixture → 400 行 + 100% 字典校验 + 留存率 ≥ 85% + 8 指标达标(SC-002, SC-004, SC-008, SC-009),在原 `tests/feature_extraction/training_data/test_integration.py` 加断言

- [ ] T030h [P] [US1] 实现 `feature_extraction/training_data/cleaner.py`:`DataCleaner` 类,实现 7 类规则 + `apply(samples) -> (cleaned, dropped)` + 留存率校验(SC-008),见 spec.md §FR-007, plan.md D-008
- [ ] T030i [P] [US1] 实现 `feature_extraction/training_data/distribution.py`:`DistributionAnalyzer` 类,实现 8 指标统计 + 写 `distribution_report.json`,见 spec.md §FR-008
- [ ] T030j [P] [US1] 实现 `feature_extraction/training_data/balancer.py`:`DataBalancer` 类,实现自动过采样(长尾类 < 3% → 2x)+ 平衡动作日志,见 spec.md §FR-008, plan.md D-009
- [ ] T030k [P] [US1] 实现 `feature_extraction/training_data/splitter.py`:`DataSplitter` 类,实现按 item_id hash 划分 80/10/10 + 泄露校验(SC-010)+ 真实数据优先(SC-011),见 spec.md §FR-009, plan.md D-010

---

## Phase 3: Polish & Cross-Cutting

- [ ] T031 [P] 更新根 `agent-platform/data-pipeline/README.md` 加"训练数据生成"章节 + 拓扑图(批 → AI 增强 → 训练数据生成 → LP Agent 训练管道)
- [ ] T032 [P] 文档:在 `contracts/training_data_format_v1.md` 写训练数据 jsonl 格式约定 + 字段顺序(对应 spec.md §6.1)
- [ ] T033 [P] 文档:在 `contracts/param_op_types.md` 写 `op` 7 个类型的适用维度 + values 类型 + 示例(对应 spec.md §6.3)
- [ ] T034 端到端集成测试:在 `tests/e2e/test_pipeline_with_training_data.py` 跑"批 → AI 增强 → 训练数据生成"完整流程,30 min 内完成(SC-001)

---

## 任务统计

| Phase / US | 任务数 | 测试 | 实现 |
|------------|--------|------|------|
| Phase 1 Setup | 3 | 0 | 3 |
| Phase 2 Foundational | 5 | 0 | 5 |
| US1 (P1) 训练数据生成(阶段 1:LLM) | 22 | 11 | 11 |
| US1 (P1) 训练数据生成(阶段 2:清洗/平衡/划分) | 12 | 7 | 5 |
| Phase 3 Polish | 4 | 1 | 3 |
| **总任务数** | **46** | **19 (41%)** | **27** |

---

## 并行机会(Phase 1 / Phase 2)

```bash
# Phase 1: 3 个 mkdir 并行
mkdir -p feature_extraction/training_data tests/feature_extraction/training_data

# Phase 2: 5 个配置 / 子包骨架 / prompt 模板文件全部 [P] 并行

# US1 阶段 2:4 个新模块(cleaner / distribution / balancer / splitter)+ 4 个测试文件全部 [P] 并行
```

---

## 实施策略(增量交付)

1. **Setup + Foundational → Foundation ready**(8 任务,约 0.5 天)
2. **+ US1 阶段 1(测试先)→ Test → mock-llm 跑 50 items**(11 测试任务,约 1.5 天)
3. **+ US1 阶段 1(实现)→ Test → 验证 400 行 + 100% 字典校验**(11 实现任务,约 1.5 天)
4. **+ US1 阶段 2(测试先)→ Test → 验证清洗 + 平衡 + 划分**(7 测试任务,约 1 天)
5. **+ US1 阶段 2(实现)→ Test → 留存率 ≥ 85% + 8 指标达标 + 泄露校验**(5 实现任务,约 1 天)
6. **+ Phase 3 Polish → 文档 + 端到端基准**(4 任务,约 0.5 天)

**Total MVP: 46 任务 / 约 6~7 天**

---

## 验证清单(交付门)

- [ ] US1:1 万 item × 8 条 < 60min(SC-001)
- [ ] US1:`params` 100% 在 7 维候选值集合内(SC-002)
- [ ] US1:LLM JSON 解析成功率 ≥ 95%(SC-003)
- [ ] US1:输出 jsonl 100% `jq -c .` 解析(SC-004)
- [ ] US1:首句高频模板 ≤ 20%(SC-005)
- [ ] US1:增量 1% 重跑 < 5min(SC-006)
- [ ] US1:负样本占比 = `negative_ratio` ±0.02(SC-007)
- [ ] US1:**数据清洗后留存率 ≥ 85%**(SC-008);< 50% 报警
- [ ] US1:**数据分布 8 指标达标**(SC-009);警告 ≤ 2 个
- [ ] US1:**按 item_id 划分无数据泄露**(SC-010)
- [ ] US1:**val/test 真实数据占比 ≥ 50%**(SC-011,如有真实数据源)
- [ ] Constitution Check 通过(I~V 五项)
- [ ] 不动 001 `ai_enhance/` 任何代码
- [ ] 不动 4 步管线(`audit/` / `cleaning/` / `normalization/` / `feature_extraction/pipeline.py`)任何代码
