# Specification Quality Checklist: 训练数据生成 (兴业 O2O 三品类 SFT 语料)

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-06-22
**Feature**: [../spec.md](../spec.md)
**Iteration**: 2(v2 → v2.1,新增 Hive 数据源澄清)
**Verdict**: ✅ PASS(全部通过,含 2 项备注)

---

## Iteration 史

| Iter | Spec 版本 | 变更摘要 | 结论 |
|------|-----------|---------|------|
| 1 | v2 | 三品类 + 两阶段 + 5 轮对话首轮通过 | PASS |
| 2 | v2.1 | **客户原始单据存储在 Hive,Stage 1 从 Hive 读取**;A-002 / FR-001/003/006 / Edge Cases / Dependencies / Configuration Snapshot 全部刷新 | PASS |

---

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
  - **Note**:Configuration Snapshot 一节明确标记 *(informational)*,包含 Hive catalog / 模型 ID / batch_size / temperature 等开发期参数;主体规范(FR / SC / 用户故事)仍以行为契约为准,Hive 仅作为数据源类别提及,具体连接由部署方注入。
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
  - **Note**:含数据工程术语(jsonl / Hive 分区 / 字典校验 / hash 划分),已在 FR 描述处给出业务解释;若读者纯业务背景,可配合 README.md + ALIGNMENT_cib_o2o.md 阅读。
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
  - v2.1 把"原始单据存哪里"这一原本可能成为 NEEDS CLARIFICATION 的点 由用户答复确定为 **Hive**。
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
  - SC-010 含"LLM 50 req/min、16 并发"作为容量假设;SC-001 含"Hive 连通自检 100%",属于上游可用性假设,而非实现绑定。
- [x] All acceptance scenarios are defined
  - US1 6 场景(新增第 6 场景:Hive 连接失败时诊断退出)+ US2 6 场景 + US3 2 场景。
- [x] Edge cases are identified
  - 共 10 项边界:SQL 解析异常、**Hive 不可达 / 权限不足 / 分区不存在**、**Hive schema 漂移**、品类源缺失、模型不可用、券-门店关联缺失、字典外值、对话超长、生成不收敛、冷启动 item。
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified
  - A-001 ~ A-009;Dependencies 段已显式列出 Hive 集群(只读)与所需访问权限。

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
  - US1 = Stage 1(Hive 拉取 + AI 标签补全)、US2 = Stage 2(SFT 语料生成)、US3 = 训练集划分。
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification
  - Hive 仅作为"客户数据源"出现,具体 HiveServer2 / Spark Hive Catalog 选型留给 plan.md;Configuration Snapshot 段被显式隔离为 *(informational)*。

---

## Coverage Map (FR ↔ SC ↔ User Story)

| 范畴 | FR | SC | User Story |
|------|----|----|-----------|
| 表解析 (DDL) | FR-001/002 | SC-001 | US1 隐含前置 |
| **Hive 行级读取** | **FR-003** | **SC-001 Hive 自检** | **US1.1/US1.2/US1.6** |
| Stage 1 补全 | FR-004/005/007/008 | SC-002/003 | US1.1–US1.4 |
| Stage 1 增量(含新分区) | FR-006 | SC-010 增量耗时 | US1.5 |
| Stage 2 主流程 | FR-009/010/012 | SC-004 | US2.1/US2.4 |
| 全维度覆盖 | FR-011 | SC-005 | US2.1/US2.2 |
| 负样本 | FR-013 | SC-006 | US2.3 |
| 多样性 | FR-014 | SC-007 | US2.5 |
| 意图分布 | FR-015/016 | SC-005 全语料层 | US2.6 |
| 清洗 | FR-017 | SC-008 | (主流程内嵌) |
| 分布 / 平衡 | FR-018 | SC-005/006/007 | (主流程内嵌) |
| 划分 | FR-019 | SC-009 | US3.1/US3.2 |
| 性能 | FR-020 | SC-010 | (端到端跑通) |
| 三品类业务比例 | FR-001/008 | SC-011 | US2.6 |
| 观测降级 | FR-007/021/022 | SC-008 报警阈值 | Edge Cases |

> 表中无空格(每个 FR 都至少绑定 1 个 SC 或场景),覆盖完整。

---

## Notes

- **Items marked incomplete**: 无。
- **下一阶段就绪**:可直接进入 `/speckit-plan`(plan.md 的 Constitution Check 与 Project Structure 也需要同步刷新到 v2.1,因为 plan.md / data-model.md / contracts 仍是 v1 文案,且需补 Hive 读取相关组件)。
- **建议同步刷新的下游文档**(本命令不修改,留给后续 /speckit-plan 与 /speckit-tasks):
  1. `specs/plan.md` — 增 `scripts/hive_reader.py`(支持 `--source=hive|mock`),`Technical Context` 列出 Hive 接入栈与凭据来源。
  2. `specs/data-model.md` — 增 `TableMeta` / `HiveReadSpec` / `RawRecord` / `ItemTags` / `TagSource` / `SFTSample`(原 TrainingSample 改名) 等实体。
  3. `specs/contracts/training_data_format_v1.md` → `sft_corpus_v2.md`;字段集对齐 v2.1(`item_type` / `covered_dims` / `tag_source` 等新增项)。
  4. `specs/contracts/param_op_types.md` — 7 维更新为商业属性(category/merchant/avg_prc/distance/age/occasion/taste)。
  5. `specs/tasks.md` — 重新拆任务:US1 = Hive reader + DDL parser + tag enricher;US2 = SFT generator;US3 = splitter。

