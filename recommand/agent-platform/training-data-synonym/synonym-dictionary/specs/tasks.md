# Tasks: ES 检索同义词词表生成

**Branch**: `003-synonym-dictionary` | **Date**: 2026-06-14
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Project**: `agent-platform/data-pipeline/`

> 任务按 Spec Kit 规范:先测试后实现,每任务标 US、并发友好标 [P]。
> **不动现有代码**(001 增强 / 002 训练数据生成 / 4 步管线);只追加新子包 + 1 个入口 + 改 `common/config_loader.py`。

---

## 总览

| 任务段 | 任务数 | 测试 | 实现 |
|--------|--------|------|------|
| Phase 1: Setup | 3 | 0 | 3 |
| Phase 2: Foundational | 5 | 0 | 5 |
| US1 (P1) 品牌规则词典 | 6 | 3 | 3 |
| US2 (P1) LLM 抽取 | 6 | 3 | 3 |
| US3 (P2) Embedding 聚类 | 6 | 3 | 3 |
| US4 (P1) 合并 + ES 输出 | 12 | 6 | 6 |
| Phase 5: Polish | 4 | 1 | 3 |
| **总任务数** | **42** | **16 (38%)** | **26** |

| 用户故事 | 任务数 |
|----------|--------|
| US1 (P1) 品牌规则词典 | 6 |
| US2 (P1) LLM 抽取 | 6 |
| US3 (P2) Embedding 聚类 | 6 |
| US4 (P1) 合并 + ES 输出(含反义词过滤) | 12 |
| no-story (Setup/Foundational/Polish) | 12 |

**MVP 范围** = Phase 1 + Phase 2 + US1 + US2 + US4 = **29 任务**(跳过 US3 embedding 可选)

---

## 依赖图(完成顺序)

```
Phase 1 Setup (T001~T003)
   ↓
Phase 2 Foundational (T004~T008)  ← 共享配置 / 子包骨架 / 反义词词典 / 品牌词典
   ↓
   ├── US1 (P1) 品牌规则词典 (T009~T014)
   ├── US2 (P1) LLM 抽取 (T015~T020)
   ├── US3 (P2) Embedding 聚类 (T021~T026)  ← 可选,降级时跳过
   └── US4 (P1) 合并 + ES 输出 (T027~T038)  ← 依赖 US1~US3
   ↓
Phase 5 Polish (T039~T042)
```

---

## Phase 1: Setup(项目结构)

- [ ] T001 [P] 创建 `synonym/` 子包(`__init__.py` + 子目录)
- [ ] T002 [P] 创建 `tests/synonym/` 测试子包
- [ ] T003 [P] 创建 `configs/prompts/synonym_extraction_v1.txt`(空文件占位,Phase 2 填内容)

---

## Phase 2: Foundational(共享基础设施)

> 这一阶段没有独立用户故事,但所有 US 都依赖。**先**写配置加载 + 反义词词典 + 品牌词典。

- [ ] T004 [P] 在 `common/config_loader.py` 增加 `SynonymConfig` dataclass(enabled / mode / rule / llm / embedding / merger / output 5 段),见 spec.md §10
- [ ] T005 [P] 在 `synonym/__init__.py` 暴露 `SynonymPipeline`、`SynonymGroup`、`SynonymMerger` 三个公开符号
- [ ] T006 [P] 创建 `synonym/llm_extractor.py`:`LLMExtractor` 类(继承 / 复用 001 `ai_enhance.llm_client.LLMClient`),加 `extract_synonyms(ai_features) -> List[SynonymGroup]` 方法
- [ ] T007 [P] 创建 `configs/brand_dictionary.yaml`:**50+ 品牌**按品类分组(咖啡 / 快餐 / 奶茶 / 烘焙 / 便利店),见 plan.md D-002
- [ ] T008 [P] 创建 `configs/antonym_pairs.yaml`:**50+ 反义词对**(好/坏/大/小/热/冷/甜/咸/浓/淡...)

---

## US1 (P1) — 品牌规则词典

**Story Goal**:加载 50+ 预置品牌同义词,品牌上线第一天就能正确召回
**Independent Test**:加载 `configs/brand_dictionary.yaml`,产出 50+ 组同义词,每组 ES Solr 格式合法(SC-002)

### Tests for User Story 1

- [ ] T009 [P] [US1] 单元测试:brand_dictionary 加载 yaml 解析 + 字段校验(canonical / variants / category),在 `tests/synonym/test_brand_dictionary.py` (FR-001)
- [ ] T010 [P] [US1] 单元测试:50+ 品牌覆盖率(SC-002):fixture 含 20 个常见品牌(KFC/Starbucks/喜茶/瑞幸...),19+ 命中(95% 覆盖率)
- [ ] T011 [P] [US1] 单元测试:每组至少 2 个词(无单元素组),无重复,无空变体

### Implementation for User Story 1

- [ ] T012 [P] [US1] 实现 `synonym/brand_dictionary.py`:`load_brand_dictionary(path) -> List[BrandEntry]`(FR-001)
- [ ] T013 [P] [US1] 实现 `synonym/brand_dictionary.py`:`brand_to_synonym_groups(brands) -> List[SynonymGroup]`,每品牌 1 组,variants 全展开
- [ ] T014 [US1] 实现 `synonym/pipeline.py` 中 `_step_rule()` 方法,加载规则词典 + 转换为 SynonymGroup 列表

---

## US2 (P1) — LLM 抽取

**Story Goal**:用 LLM 从 item_title 抽长尾同义词(预置词典没覆盖到的)
**Independent Test**:50 items fixture → LLM 抽 50~200 组同义词,与品牌词典不重叠的长尾占比 ≥ 60%

### Tests for User Story 2

- [ ] T015 [P] [US2] 单元测试:prompt 模板加载 + 字段注入(ai_features / dictionary_yaml),在 `tests/synonym/test_llm_extractor.py` (FR-002)
- [ ] T016 [P] [US2] 单元测试:LLM 客户端降级(mock-llm 不可用 → 抛降级异常,主流程不阻塞),在 `tests/synonym/test_llm_extractor_degradation.py` (FR-002 降级)
- [ ] T017 [P] [US2] 单元测试:LLM 输出 JSON 解析(合法 → SynonymGroup 列表;非法 → failures + 跳过),在 `tests/synonym/test_llm_extractor_parse.py` (FR-002)

### Implementation for User Story 2

- [ ] T018 [P] [US2] 实现 `synonym/prompt.py`:`load_prompt(path) -> PromptTemplate` + `render(ai_features, dictionary_yaml)`,**含 5 类提示约束**(只输出字典子集 / 拼写变体 / 中英文;不输出反义词 / 弱关联;每组 2~5 词;每商品最多 5 组)
- [ ] T019 [P] [US2] 实现 `synonym/llm_extractor.py`:`LLMExtractor.extract_synonyms(ai_features) -> List[SynonymGroup]`,调 001 复用 LLMClient + 解析 + 字典校验(FR-002)
- [ ] T020 [US2] 实现 `synonym/pipeline.py` 中 `_step_llm()` 方法,批量调用 LLM(16 并发)+ 失败写 `synonym_failures.jsonl`

---

## US3 (P2) — Embedding 聚类

**Story Goal**:用 embedding 找向量相似的词,补 LLM 漏掉的细粒度同义
**Independent Test**:1000 个 item_title embedding → 聚类后新增 30~50 组同义词,与 LLM 重叠率 ≤ 30%

### Tests for User Story 3

- [ ] T021 [P] [US3] 单元测试:embedding 模型加载(`bge-small-zh`)+ 推理 1 个句子得 512 维向量,在 `tests/synonym/test_embedding_cluster.py` (FR-003)
- [ ] T022 [P] [US3] 单元测试:余弦相似度 + 距离阈值(≥ 0.85 合并,< 0.85 不合并)
- [ ] T023 [P] [US3] 单元测试:embedding 服务降级(模型加载失败 → 抛降级异常,主流程跳过),在 `tests/synonym/test_embedding_cluster_degradation.py` (FR-003 降级)

### Implementation for User Story 3

- [ ] T024 [P] [US3] 实现 `synonym/embedding_cluster.py`:`EmbeddingClusterer` 类,加载 `bge-small-zh` + 算所有 token 的 embedding + 余弦聚类(FR-003)
- [ ] T025 [P] [US3] 实现 `synonym/embedding_cluster.py`:`cluster_to_synonym_groups(clusters) -> List[SynonymGroup]`,高置信(< 0.15)直接合并,中置信(0.15~0.30)二次 LLM 确认
- [ ] T026 [US3] 实现 `synonym/pipeline.py` 中 `_step_embedding()` 方法,降级时跳过 + 写 `synonyms_meta.json` 标记

---

## US4 (P1) — 合并 + ES 输出(核心)

**Story Goal**:3 源同义词合并去重,反义词过滤,输出 ES Solr 多向格式
**Independent Test**:3 源各 50~200 组输入 → 合并去重 → 200~400 组输出,反义词合并数 = 0(SC-004)

### Tests for User Story 4

- [ ] T027 [P] [US4] 单元测试:antonym 过滤 50 对反义词全部不合并(SC-004,最重要),在 `tests/synonym/test_antonym_filter.py`
- [ ] T028 [P] [US4] 单元测试:3 源合并去重(完全相同 → 留 1,多源标记;有交集 → 合并;无交集 → 各自保留),在 `tests/synonym/test_merger.py` (FR-004, D-007)
- [ ] T029 [P] [US4] 单元测试:长度限制(单词 ≤ 20 字,组大小 ≤ 10,总数 ≤ 10000,SC-005)
- [ ] T030 [P] [US4] 单元测试:es_formatter Solr 多向格式(1 行 1 组,逗号分隔,头部注释,末尾 `\n`,无空行),在 `tests/synonym/test_es_formatter.py` (FR-005, SC-003)
- [ ] T031 [P] [US4] 单元测试:es_formatter 输出 100% 可被 `jq` 解析 + Solr 解析器兼容(SC-003)
- [ ] T032 [P] [US4] 单元测试:stats 统计 + 写 `synonyms_stats.json`(total_groups / avg_group_size / category_coverage / antomym_rejected_count / source_overlap / top_10_canonical),在 `tests/synonym/test_stats.py` (FR-006)

### Implementation for User Story 4

- [ ] T033 [P] [US4] 实现 `synonym/antonym_filter.py`:`AntonymFilter` 类,加载反义词对 + `filter(groups) -> (kept, rejected)`,反义词拒收写 `synonym_rejections.jsonl`(FR-004, D-005)
- [ ] T034 [P] [US4] 实现 `synonym/merger.py`:`SynonymMerger` 类,3 源合并去重 + 长度限制 + 反义词过滤(FR-004)
- [ ] T035 [P] [US4] 实现 `synonym/es_formatter.py`:`format_solr(groups, output_path)`,1 行 1 组 + 头部注释(版本/时间/3 源贡献)+ 末尾 `\n`(FR-005)
- [ ] T036 [P] [US4] 实现 `synonym/stats.py`:`compute_stats(groups, source_distribution) -> SynonymStats`,写 `synonyms_stats.json`(FR-006)
- [ ] T037 [P] [US4] 实现 `synonym/pipeline.py` 中 `_step_merge()` 方法,4 步合并(规则 → LLM → embedding → 反义词过滤)
- [ ] T038 [US4] 集成测试:50 items fixture → 验证 3 源 + 合并 + ES Solr 格式 + 反义词不合并 + jq 解析 100%(SC-001~005 全部),在 `tests/synonym/test_integration.py`

---

## Phase 5: Polish & Cross-Cutting

- [ ] T039 [P] 更新根 `agent-platform/data-pipeline/README.md` 加"ES 同义词词表生成"章节 + 拓扑图(批 → AI 增强 → 同义词 → ES 索引 → LP Agent 检索)
- [ ] T040 [P] 文档:在 `contracts/solr_synonyms_format.md` 写 Solr 多向格式详细说明(对应 spec.md §5 FR-005)
- [ ] T041 [P] 文档:在 `contracts/brand_dictionary_schema.md` 写 `brand_dictionary.yaml` schema 详细说明
- [ ] T042 端到端集成测试:在 `tests/e2e/test_pipeline_with_synonym.py` 跑"批 → AI 增强 → 同义词生成"完整流程,30 min 内完成(SC-001)

---

## 任务统计

| Phase / US | 任务数 | 测试 | 实现 |
|------------|--------|------|------|
| Phase 1 Setup | 3 | 0 | 3 |
| Phase 2 Foundational | 5 | 0 | 5 |
| US1 (P1) 品牌规则词典 | 6 | 3 | 3 |
| US2 (P1) LLM 抽取 | 6 | 3 | 3 |
| US3 (P2) Embedding 聚类 | 6 | 3 | 3 |
| US4 (P1) 合并 + ES 输出 | 12 | 6 | 6 |
| Phase 5 Polish | 4 | 1 | 3 |
| **总任务数** | **42** | **16 (38%)** | **26** |

---

## 并行机会(Phase 1 / Phase 2)

```bash
# Phase 1: 3 个 mkdir 并行
mkdir -p synonym tests/synonym

# Phase 2: 5 个配置 / 子包骨架 / 词典 yaml 全部 [P] 并行

# US1~US3 阶段:3 个源(rule / llm / embedding)实现 + 测试可以并行开发
```

---

## 实施策略(增量交付)

1. **Setup + Foundational → Foundation ready**(8 任务,约 0.5 天)
2. **+ US1 品牌规则词典**(6 任务,约 0.5 天)
3. **+ US2 LLM 抽取**(6 任务,约 1 天)
4. **+ US4 合并 + ES 输出(不含 embedding)**(12 任务,约 1.5 天)
5. **+ US3 Embedding 聚类(可选,P2)**(6 任务,约 1 天)
6. **+ Phase 5 Polish → 文档 + 端到端基准**(4 任务,约 0.5 天)

**Total MVP(不含 US3):29 任务 / 约 4 天**  
**Total 完整(含 US3):42 任务 / 约 5~6 天**

---

## 验证清单(交付门)

- [ ] US1:50+ 品牌覆盖率 ≥ 80%(SC-002)
- [ ] US2:LLM 抽取降级正常,主流程不阻塞
- [ ] US3:embedding 降级正常,可跳过
- [ ] US4:**50 对反义词全部不合并(SC-004)**
- [ ] US4:输出 100% `jq -c .` 解析 + Solr 兼容(SC-003)
- [ ] US4:总组数 ≤ 10000,单词长度 ≤ 20 字符(SC-005)
- [ ] US1~US4:1 万 items × 3 源 < 30 min(SC-001)
- [ ] Constitution Check 通过(I~V 五项)
- [ ] 不动 001 `ai_enhance/` 任何代码
- [ ] 不动 002 `training_data/` 任何代码
- [ ] 不动 4 步管线任何代码
