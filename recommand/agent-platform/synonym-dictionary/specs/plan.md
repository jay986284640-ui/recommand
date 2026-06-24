# Implementation Plan: ES 检索同义词词表生成

**Branch**: `003-synonym-dictionary` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

> 本 plan 在 001 增强管线(`agent-platform/data-pipeline/feature_extraction/ai_enhance/`)产出的
> `item_features_ai.jsonl` 基础上,设计"ES 同义词词表生成"独立子包。
> 现有代码**不动**,只追加 `synonym/` 子包 + 1 个入口 `run_build_synonyms.py`。

---

## Summary

| 能力 | 接入位置 | 触发方式 | 产出来源 |
|------|----------|----------|----------|
| ES 同义词词表 | `synonym/` 新增子模块 | 独立 `run_build_synonyms.py`,手动 / 调度 | `item_features_ai.jsonl` + 品牌词典 + LLM + embedding → 合并 → `synonyms_solr.txt` |

---

## Technical Context

**Language/Version**: Python 3.11+(沿用)
**Spark**: 3.5.3(本子包不直接用,只读 001 产物 jsonl)
**新增依赖**:
- LLM SDK(沿用 001 的客户端,直接复用)
- `sentence-transformers`(本地 embedding 推理,`bge-small-zh` 模型)
- `scikit-learn`(余弦相似度 + 聚类)
- `pyyaml`(品牌词典 / 反义词对加载)

**Storage**:
- 主输出:`./synonyms_solr.txt`(ES 直接消费)
- 元信息:`./synonyms_meta.json`
- 统计:`./synonyms_stats.json`
- 失败日志:`./synonym_failures.jsonl`
- 反义词拒收:`./synonym_rejections.jsonl`

**Testing**:
- pytest + mock-llm 单元测试(沿用 001 的 mock-llm 服务)
- 集成测试:跑 50 个 item_features_ai fixture → 验证 3 源 + 合并 + ES Solr 格式
- 反义词测试:50 对反义词全部不合并(SC-004)

**Target Platform**: Linux 容器(沿用)
**Project Type**: 在 `data-pipeline/` 中追加 1 个子包 `synonym/` + 1 个新 `run_build_synonyms.py`

**Performance Goals**:
- 1 万 items × 3 源处理 < 30 min(SC-001)
  - LLM 抽取 ~ 5 min(50 req/min × 16 并发)
  - Embedding 推理 ~ 5 min(GPU)/ 15 min(CPU,本地推理)
  - 合并 + 输出 ~ 30s
- 品牌词典加载 < 1s(yaml 解析)

**Constraints**:
- 不动 001 增强管线(`ai_enhance/`)
- 不动 LP Agent envelope 协议
- 不动 ES 索引 mapping / analyzer(由 ES 运维负责)
- LLM 调用必须可降级(失败 → 仅输出规则 + embedding)
- Embedding 不可用时降级(失败 → 仅输出规则 + LLM)
- 输出 100% 无反义词合并(SC-004)
- 输出 100% 可被 ES `synonym_graph` filter 解析(SC-003)

**Scale/Scope**:
- item 总量:1w~10w SKU(沿用 001)
- 品牌词典初版 50+ 品牌,运营可持续扩量
- 目标同义词组数 200~2000(SC-005 ≤ 10000)

---

## Constitution Check

### I. Library-First ✅
- `synonym/` 是新顶层子包,独立可测
- 与 001 增强管线**单向依赖**:只读 `item_features_ai.jsonl`,不反写
- 3 源可独立运行 + 测试(rule / llm / embedding)

### II. CLI Interface ✅
- `run_build_synonyms.py --mode=full --config=... --item-features-ai=PATH`
- 与 001 `run_ai_enhance.py` / 002 `run_training_data.py` CLI 风格一致

### III. Test-First (NON-NEGOTIIBLE) ✅
- 4 个 US(US1~US4)+ 测试任务 11~13 个先于实现任务
- 关键测试:antonym 过滤(SC-004)、Solr 格式(SC-003)、品牌覆盖率(SC-002)

### IV. Integration Testing ✅
- 用 mock-llm 服务(沿用 001 的 `mock-llm-server`)
- 用真实 `bge-small-zh` 模型跑小 fixture(本地推理,无需 GPU)
- 集成测试 1 个:50 items fixture → 验证 3 源 + 合并 + ES Solr 格式

### V. Observability, Versioning, Simplicity ✅
- 监控指标:LLM 解析率 / 反义词拒收数 / 3 源贡献占比 / 总组数
- 输出格式版本化:每文件加 `_format_version: "synonyms_v1"`
- Simplicity:不引入新的中间件,沿用 LLM SDK + 本地 embedding

**Constitution Check 状态:通过**。Complexity Tracking 表空。

---

## Project Structure(增量)

```
agent-platform/data-pipeline/
├── synonym/                                 # 新增子包
│   ├── __init__.py
│   ├── brand_dictionary.py                  # 规则源(预置品牌词表加载)
│   ├── llm_extractor.py                     # LLM 抽取(item_title → 同义词)
│   ├── embedding_cluster.py                 # Embedding 聚类(向量相似度)
│   ├── merger.py                            # 3 源合并 + 反义词过滤
│   ├── es_formatter.py                      # Solr 多向格式输出
│   ├── stats.py                             # 统计 + 写 synonyms_stats.json
│   ├── antomym_filter.py                    # 反义词拒收
│   └── pipeline.py                          # SynonymPipeline 编排
├── configs/
│   ├── brand_dictionary.yaml                # 新增:50+ 品牌按品类分组
│   ├── antomym_pairs.yaml                   # 新增:50+ 反义词对
│   ├── tag_dictionary.yaml                  # 001 已有,本 spec 沿用
│   └── prompts/
│       ├── ai_enhance_v1.txt                # 001 已有
│       ├── training_data_v1.txt             # 002 已有
│       └── synonym_extraction_v1.txt        # 新增:LLM 抽取 prompt
├── tests/
│   └── synonym/                             # 新增测试子包
│       ├── test_brand_dictionary.py
│       ├── test_llm_extractor.py
│       ├── test_embedding_cluster.py
│       ├── test_merger.py
│       ├── test_antonym_filter.py
│       ├── test_es_formatter.py
│       ├── test_stats.py
│       ├── test_pipeline.py
│       └── test_integration.py
├── run_build_synonyms.py                    # 新增入口
└── run_pipeline.py                          # 现有(可选加 --skip-synonym 开关)
```

---

## Phase 0 — 关键技术决策

| ID | 决策点 | 选项 | 推荐 |
|----|--------|------|------|
| D-001 | 3 源混合策略 | 顺序(rule → llm → embedding) / 并行(3 源并发) | **顺序**:LLM 和 embedding 都需要 item_features_ai,顺序跑资源友好;并行也可以但收益小 |
| D-002 | 品牌词典 schema | 单层 dict / 分组(品类 + 品牌) | **分组(品类 + 品牌)**:便于按品类过滤;也便于运营按品类维护 |
| D-003 | LLM 抽取 prompt 范式 | 1 段(每商品 1 次) / batch(多商品 1 次) | **1 段**:LLM 1 段抽 1~5 组,简单可控;batch 难控制输出 |
| D-004 | Embedding 模型 | bge-small-zh / bge-base-zh / text2vec-base-chinese | **bge-small-zh**:小、快(91M 参数)、中文优化、本地推理 5min 跑完 1w items |
| D-005 | 反义词过滤 | 拒收 / 标记后人工 review | **拒收**(SC-004):宁缺毋滥,反义词合并召回错误更糟 |
| D-006 | ES 输出格式 | Solr 多向 / WordNet 单向 | **Solr 多向**:每组词互相等价,适合"搜任一召回"场景,符合用户预期 |
| D-007 | 3 源合并冲突处理 | 后者覆盖前者 / 合并去重 | **合并去重**:有交集则合并为 1 组,标记多源(`source: ["rule", "llm"]`);覆盖率更高,无信息丢失 |

---

## Phase 1 — 设计产物

### 1.1 新增数据模型(`data-model.md`,本 plan 简述)

| 实体 | 字段 | 来源 |
|------|------|------|
| `SynonymGroup` | group_id, canonical, variants[], source[], confidence(float), category?, merged_from? | 3 源合并后 |
| `SynonymEntry` | token(str), lang(zh/en), length(int) | 单词 |
| `BrandEntry` | canonical, variants[], category | 规则词典 |
| `AntonymPair` | word_a, word_b, category | 反义词对 |
| `EmbeddingCluster` | cluster_id, tokens[], avg_distance | 聚类 |
| `SynonymStats` | total_groups, avg_group_size, category_coverage, antomym_rejected_count, source_overlap, top_10_canonical | 统计 |

### 1.2 新增 contracts

- `contracts/solr_synonyms_format.md` — `synonyms_solr.txt` ES Solr 多向格式详细说明
- `contracts/brand_dictionary_schema.md` — `configs/brand_dictionary.yaml` schema 详细说明
- `contracts/antonym_pairs_schema.md` — `configs/antomym_pairs.yaml` schema 详细说明

### 1.3 复用 001 / 002

- `feature_extraction/ai_enhance/llm_client.py` 的 `LLMClient` 类(直接 import 复用,不改)
- `configs/tag_dictionary.yaml` 7 维字典(直接读,品类过滤时用)
- `feature_extraction/ai_enhance/tag_schema.py` 的 `load_dictionary()`

---

## Phase 1 后的 Constitution Check(预期)

✅ I. Library-First — 1 个新子包独立,3 源可独立测试  
✅ II. CLI Interface — 1 个新 `run_build_synonyms.py`  
✅ III. Test-First — tasks.md 先测后实(预计 11~13 个测试任务)  
✅ IV. Integration Testing — mock-llm + 真实 bge-small-zh 集成  
✅ V. Observability — 解析率 / 反义词拒收数 / 3 源贡献占比

---

## 关键文件清单(增量)

| 文件 | 类型 | 说明 |
|------|------|------|
| `synonym/__init__.py` | 新增 | 子包入口 |
| `synonym/brand_dictionary.py` | 新增 | `load_brand_dictionary(path) -> List[BrandEntry]` |
| `synonym/llm_extractor.py` | 新增 | `LLMExtractor` 调 001 复用 LLMClient + 抽同义词 |
| `synonym/embedding_cluster.py` | 新增 | `EmbeddingClusterer` 用 `bge-small-zh` + 余弦聚类 |
| `synonym/antomym_filter.py` | 新增 | `AntonymFilter` 加载反义词对 + 拒收 |
| `synonym/merger.py` | 新增 | `SynonymMerger` 3 源合并 + 去重 + 长度限制 |
| `synonym/es_formatter.py` | 新增 | `format_solr(groups, output_path)` Solr 多向格式 |
| `synonym/stats.py` | 新增 | `compute_stats(groups, output_path)` |
| `synonym/pipeline.py` | 新增 | `SynonymPipeline.run()` 编排 4 步 |
| `configs/brand_dictionary.yaml` | 新增 | 50+ 品牌按品类分组(咖啡/快餐/奶茶/烘焙/便利店) |
| `configs/antomym_pairs.yaml` | 新增 | 50+ 反义词对(好/坏/大/小/热/冷/甜/咸...) |
| `configs/prompts/synonym_extraction_v1.txt` | 新增 | LLM 抽取 prompt |
| `tests/synonym/test_brand_dictionary.py` | 新增 | yaml 加载 + 50+ 品牌覆盖率(SC-002) |
| `tests/synonym/test_llm_extractor.py` | 新增 | mock-llm 抽 50 items |
| `tests/synonym/test_embedding_cluster.py` | 新增 | bge-small-zh 聚类 + 距离阈值 |
| `tests/synonym/test_antonym_filter.py` | 新增 | 50 对反义词全部不合并(SC-004) |
| `tests/synonym/test_merger.py` | 新增 | 3 源合并 + 去重 + 长度限制 |
| `tests/synonym/test_es_formatter.py` | 新增 | Solr 格式 + jq 解析 100%(SC-003) |
| `tests/synonym/test_stats.py` | 新增 | 统计 + 写 `synonyms_stats.json` |
| `tests/synonym/test_pipeline.py` | 新增 | 4 步编排单元测试 |
| `tests/synonym/test_integration.py` | 新增 | 集成测试:50 items fixture → 验证全部 SC |
| `run_build_synonyms.py` | 新增 | 入口 |
| `common/config_loader.py` | 改 | 加 `SynonymConfig` dataclass |

---

## Complexity Tracking

| 违反 | 为什么 | 更简单方案(被拒理由) |
|------|--------|---------------------|
| (空) | (空) | (空) |

---

## Next Steps

1. **Phase 0 research.md** 在 D-001~D-007 7 个点收敛;`bge-small-zh` 模型选择实测
2. **Phase 1 design** `data-model.md` 增量 + `contracts/{solr_synonyms_format, brand_dictionary_schema, antomym_pairs_schema}.md`
3. **/speckit-tasks** 按 US1~US4 拆任务,测试 11~13 个先于实现
4. **/speckit-implement** 按任务执行
