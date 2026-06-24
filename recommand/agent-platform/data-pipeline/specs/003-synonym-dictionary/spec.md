# Spec: ES 检索同义词词表生成 (Synonym Dictionary)

**Branch**: `003-synonym-dictionary` | **Date**: 2026-06-14 | **Status**: Draft
**Project**: `agent-platform/data-pipeline/`
**Related**:
- [001-promo-recommend-agent](../../../../specs/001-promo-recommend-agent/spec.md) — LP Agent(ES 检索的最终消费者)
- [001-data-pipeline-enhancement](../001-data-pipeline-enhancement/spec.md) — `item_features_ai.jsonl` 数据源(7 维 AI 标签)
- [002-training-data-generator](../002-training-data-generator/spec.md) — 独立 spec,本 spec 不依赖

---

## 1. 概述

为 LP Agent 的 **Elasticsearch(ES)商品检索**生成同义词词表,解决"用户搜不到相关商品"的问题。

- **核心痛点**:用户搜"咖啡"找不到"拿铁 / latte";搜"肯德基"找不到"KFC / kfc";搜"星巴克"找不到"Starbucks / STARBUCKS"。
- **方案**:**3 源混合**(规则词典 + LLM 抽取 + embedding 聚类)→ 合并验证 → 输出 ES Solr 多向同义词格式
- **产出**:`synonyms_solr.txt`(ES `synonym_graph` filter 直接消费)+ `synonyms_meta.json`(版本追溯)

不动现有代码,只追加新子包 `synonym/` + 1 个入口 `run_build_synonyms.py`。

---

## 2. 背景与目标

### 2.1 背景

LP Agent 用 ES 做商品粗排 / 召回,当前痛点:

| 场景 | 现状 | 期望 |
|------|------|------|
| 用户搜"咖啡" | 只召回 `category=咖啡` 商品 | 同时召回 `latte / 拿铁 / espresso` 等 |
| 用户搜"KFC" | 找不到(ES 索引里是"肯德基") | 召回"肯德基" |
| 用户搜"星巴克" | 找到 1 个"星巴克 拿铁" | 召回"星巴克 / Starbucks / 星巴克臻选"等所有门店 |
| 用户搜"一点点" | 找不到(ES 是"1點點") | 召回"1點點" |
| 用户搜"奶茶" | 召回"喜茶 / 奈雪 / 蜜雪冰城" | 同上,但**不**误召回"咖啡店"(分类过滤) |

### 2.2 目标

- (G1) 自动构建**品牌 / 品类 / 拼写变体**同义词表
- (G2) 中英文双语(咖啡 ↔ coffee,星巴克 ↔ Starbucks)
- (G3) 拼写错误 / 缩写 / 别名("一点点" ↔ "1點點" ↔ "1点點")
- (G4) **100% 避免反义词合并**("好" 不 ↔ "坏",大 ↔ 小)
- (G5) 输出文件 ES 直接可读,无需手工改格式

### 2.3 非目标

- 不做查询改写(那是 LP Agent 运行时的事)
- 不改 ES 索引 mapping / analyzer 配置(由 ES 运维负责)
- 不做语义相似度(那是 embedding 召回的职责,本 spec 只生成字符串级同义词)
- 不替代人工运营词典(只补长尾)

---

## 3. 输入 / 输出

### 3.1 输入

| 来源 | 路径 | 用途 |
|------|------|------|
| `item_features_ai.jsonl` | 001 增强产物 | 抽 `item_title` / `item_description` / `ai_tags`,做 LLM 抽取 + embedding 聚类 |
| `configs/tag_dictionary.yaml` | 7 维字典 | 品类同义词基础(味/场/材/域/人/情/就) |
| `configs/brand_dictionary.yaml` | **新增**:预置品牌词表 | 50+ 常见品牌(中英文 / 拼音 / 拼写错误)按品类分组 |
| `configs/prompts/synonym_extraction_v1.txt` | **新增**:LLM 抽取 prompt | LLM 从 item_title 抽同义词 |

### 3.2 输出

| 路径 | 用途 |
|------|------|
| `synonyms_solr.txt` | **主产出**:ES `synonym_graph` filter 直接消费(Solr 多向格式) |
| `synonyms_meta.json` | 元信息:版本 / 生成时间 / 3 源贡献占比 / 模型版本 |
| `synonyms_stats.json` | 统计:词条数 / 平均每组词数 / 覆盖率 / 反义词合并数(应 = 0) |

---

## 4. 用户故事

### US1 — 品牌规则词典(P1,基础)

> 作为 ES 索引构建方,我想有 50+ 预置品牌的同义词表(KFC/肯德基/Starbucks/星巴克等),品牌上线第一天就能正确召回。

**独立可测试**:加载 `configs/brand_dictionary.yaml`,产出 50+ 组同义词(SC-002 覆盖率),每组 ES Solr 格式合法。

**场景**:
- KFC / 肯德基 / 肯打鸡(常见错别字)→ 1 组
- 麦当劳 / McDonald's / 麦当牢(常见错别字)→ 1 组
- 星巴克 / Starbucks / 星吧克(常见错别字)→ 1 组
- 喜茶 / HEYTEA / heytea / 喜茶店 → 1 组
- 蜜雪冰城 / 蜜雪 / MIXUE → 1 组

### US2 — LLM 抽取(P1,扩展)

> 作为数据工程师,我想用 LLM 从 `item_title` 中抽长尾同义词(预置词典没覆盖到的),不靠人工补。

**独立可测试**:50 个商品 fixture → LLM 抽 50~200 组同义词,与品牌词典不重叠的长尾占比 ≥ 60%。

**场景**:
- "星巴克 拿铁 中杯" → 抽"中杯 / 中杯装 / grande"
- "一点点 波霸奶茶" → 抽"波霸 / 珍珠 / bubble"
- "麦当劳 巨无霸" → 抽"巨无霸 / big mac / Big Mac"
- 失败 → 写 `synonym_failures.jsonl`,不阻塞主流程

### US3 — Embedding 聚类(P2,补充)

> 作为 ES 索引构建方,我想用 embedding 找向量相似的词,补 LLM 漏掉的细粒度同义(如"拿铁"≈"latte coffee"≈"拿铁咖啡")。

**独立可测试**:1000 个 item_title embedding → 聚类后新增 30~50 组同义词,与 LLM 抽取重叠率 ≤ 30%。

**场景**:
- 拿铁 / latte / 拿铁咖啡 / latte coffee → 1 组(embedding 距离 < 0.2)
- 咖啡 / coffee / 咖啡饮品 / coffee drink → 1 组
- 汉堡 / burger / 汉堡包 → 1 组
- 距离 ≥ 0.3 → 不合并(避免"咖啡"和"茶"合并)

### US4 — 合并 + ES 输出(P1,核心)

> 作为数据工程师,我想把 3 源同义词合并去重,验证后输出 ES Solr 多向格式。

**独立可测试**:3 源各 50~200 组输入 → 合并去重 → 200~400 组输出,反义词合并数 = 0(SC-004)。

**场景**:
- 同一组词被多源覆盖 → 留 1 组,标记"merged_from": ["rule", "llm"]
- 反义词 / 弱关联("好"/"坏"、"大"/"小")→ **拒收**
- 不同源但有交集(如 rule 有"咖啡,coffee",LLM 有"咖啡,espresso")→ 合并为"咖啡,coffee,espresso"
- 输出 100% 可被 ES `synonym_graph` 解析(SC-003)

---

## 5. 功能性需求(FR)

### FR-001 品牌规则词典加载

- 输入:`configs/brand_dictionary.yaml`(新增,50+ 品牌按品类分组)
- 输出:`List[SynonymGroup]`,每组 1 个品牌 + 所有变体
- 加载:启动时一次性读,yaml 变更需重启或显式 reload
- 验证:每组至少 2 个词(否则拒收),无重复

**yaml schema**:
```yaml
brands:
  - canonical: 肯德基         # 主名(显示用)
    variants: [KFC, kfc, 肯打鸡, 肯德鸡, KFC宅急送]  # 所有变体
    category: 快餐             # 品类(用于后续分类过滤)
  - canonical: 星巴克
    variants: [Starbucks, starbucks, STARBUCKS, 星吧克, 星巴克咖啡]
    category: 咖啡
```

### FR-002 LLM 抽取

- 输入:`item_features_ai.jsonl` 一行 + prompt 模板
- 输出:1~N 组同义词(每组 2~5 词)
- 批量调用,batch_size 默认 16(可配)
- LLM temperature = 0.3(稳定为主,多样性为辅)
- 单条失败 → 写 `synonym_failures.jsonl`,继续其他

**LLM 输出格式**(强制 JSON):
```json
{
  "synonym_groups": [
    {"canonical": "中杯", "variants": ["中杯装", "grande", "中杯大小"]},
    {"canonical": "波霸", "variants": ["珍珠", "bubble", "波霸珍珠"]}
  ]
}
```

**prompt 关键约束**:
- 输出**仅**字典子集 / 常见拼写变体 / 中英文翻译
- **不**输出反义词 / 弱关联("好"/"坏"、"咖啡"/"茶")
- 每组词数 2~5(过少无意义,过多可能是噪音)
- 1 个商品最多抽 5 组(过多可能 LLM 编造)

### FR-003 Embedding 聚类

- 输入:`item_features_ai.jsonl` 中 `item_title` + `item_description` 拼接
- 模型:本地 embedding(`bge-small-zh` 或 `text2vec-base-chinese`,可配)
- 聚类:把所有非停用词的 token 算 embedding,余弦相似度 ≥ 0.85 才合并
- 距离 < 0.15:高置信合并
- 0.15 ≤ 距离 < 0.30:中置信,需要 LLM 二次确认
- 距离 ≥ 0.30:不合并

**降级**:
- embedding 服务不可用 → 跳过本步骤,只输出规则 + LLM
- 聚类耗时 > 30 min → 中断,记录已聚类部分

### FR-004 合并 + 验证

3 源同义词合并规则:
1. **完全相同组** → 留 1 组,`source` 标记为多源(`["rule", "llm", "embedding"]`)
2. **有交集组** → 合并为 1 组,标记合并来源
3. **无交集组** → 各自保留

**反义词 / 弱关联过滤**:
- 维护 `configs/antonym_pairs.yaml`(预置 50+ 反义词对,如"好/坏"、"大/小"、"热/冷"、"甜/咸")
- 合并时检查:任一组含反义词对 → 拒收该组
- 拒绝原因 → 写 `synonym_rejections.jsonl`

**长度限制**:
- 单词长度 ≤ 20 字符
- 每组词数 2~10(超过 10 → 截断或拆组)
- 总组数 ≤ 10000(避免 ES synonym_graph filter 性能问题)

### FR-005 ES Solr 格式输出

ES `synonym_graph` filter 的 Solr 格式:

```
星巴克, starbucks, STARBUCKS, 星吧克
咖啡, coffee, 拿铁, latte
肯德基, KFC, kfc, 肯打鸡
```

**规则**:
- 1 行 1 组,逗号分隔
- 词内可含空格(短语),不用引号包裹
- 大小写敏感(由 ES analyzer 处理,不预处理)
- `#` 开头为注释行(脚本自动生成头部注释)
- 末尾留 `\n`,无空行

**文件**:`./synonyms_solr.txt`

**元信息文件** `synonyms_meta.json`:
```json
{
  "_format_version": "synonyms_v1",
  "generated_at": "2026-06-14T10:00:00Z",
  "source_distribution": {"rule": 0.35, "llm": 0.45, "embedding": 0.20},
  "total_groups": 234,
  "total_tokens": 891,
  "llm_model": "claude-haiku-4-5",
  "embedding_model": "bge-small-zh"
}
```

### FR-006 统计 + 监控

`synonyms_stats.json` 含:
- `total_groups` — 总组数
- `avg_group_size` — 平均每组词数
- `category_coverage` — 各品类覆盖(咖啡/快餐/奶茶/烘焙/便利店)
- `antonym_rejected_count` — 反义词拒收数(应 = 0)
- `source_overlap` — 3 源交集比例
- `top_10_canonical` — 出现频率最高的 10 个词

---

## 6. 数据契约

详见 [`contracts/solr_synonyms_format.md`](./contracts/solr_synonyms_format.md)

---

## 7. 成功标准(SC)

| ID | 标准 | 验证方式 |
|----|------|----------|
| SC-001 | 1 万 items × 3 源处理 < 30 min(LLM 50 req/min,embedding 30s 内) | `time python run_build_synonyms.py` |
| SC-002 | 预置品牌词表覆盖率 ≥ 80%(测试集含 20 个常见品牌,18+ 命中) | 写 20 个品牌 fixture,跑 brand_dictionary 验证 |
| SC-003 | 输出文件 100% 可被 ES `synonym_graph` filter 解析(ES 7.x 解析无错) | 跑 ES 集成测试,索引 100 个商品 + 20 个查询,召回率 ≥ 90% |
| SC-004 | **100% 无反义词合并**(SC-004 最重要):维护 50 对反义词,合并后 0 对被错误合并 | 跑 `antonym_test.py`,50 对全部应不合并 |
| SC-005 | 总组数 ≤ 10000,单词长度 ≤ 20 字符,符合 ES 性能规范 | 读 `synonyms_stats.json` 校验 |

---

## 8. 假设与依赖

- (A-001) `item_features_ai.jsonl` 已存在(001 增强产物)
- (A-002) ES 7.x+ 已部署,`synonym_graph` filter 已配置(由 ES 运维负责,本 spec 不涉及)
- (A-003) Embedding 服务可本地推理(无网络依赖,模型本地加载)
- (A-004) LLM 平台沿用 001 spec 的"大模型平台托管 API"
- (A-005) `configs/brand_dictionary.yaml` 由运营维护,初版 50+ 品牌,后续扩量
- (A-006) 同义词表只在**索引构建时**应用(query 时不应用),保证召回完整性

---

## 9. 边界与负面场景

| 场景 | 行为 |
|------|------|
| `item_features_ai.jsonl` 不存在 | `run_build_synonyms.py` 退出非 0,提示先跑 001 ai_enhance |
| LLM 整体不可用 | 仅输出规则 + embedding(FR-002 降级),`source_distribution` 记录 |
| Embedding 服务不可用 | 仅输出规则 + LLM(FR-003 降级) |
| 反义词被合并 | 写 `synonym_rejections.jsonl`,**不入主输出**(SC-004 保障) |
| 总组数 > 10000 | 按 `source` 优先级截断:rule > llm > embedding,`synonyms_meta.json` 标记"truncated" |
| ES 7.x 不兼容的 token(如特殊字符) | 写入前转义或丢弃,记入 `synonym_failures.jsonl` |

---

## 10. 配置开关

```yaml
synonym:
  enabled: true
  mode: full                       # full(本 spec 只支持 full)
  
  # === 规则源(US1) ===
  rule:
    enabled: true
    brand_dictionary_path: configs/brand_dictionary.yaml
    min_group_size: 2
  
  # === LLM 抽取(US2) ===
  llm:
    enabled: true
    batch_size: 16
    timeout_seconds: 15
    temperature: 0.3
    model: claude-haiku-4-5
    max_groups_per_item: 5
    prompt_template: configs/prompts/synonym_extraction_v1.txt
    failures_path: ./synonym_failures.jsonl
  
  # === Embedding 聚类(US3) ===
  embedding:
    enabled: true
    model: bge-small-zh            # 本地推理
    distance_threshold_high: 0.15  # 高置信合并
    distance_threshold_low: 0.30   # 低置信(不合并)
    max_runtime_seconds: 1800      # 30 min 超时
  
  # === 合并 + 验证(US4) ===
  merger:
    enabled: true
    antomym_pairs_path: configs/antonym_pairs.yaml
    rejections_path: ./synonym_rejections.jsonl
    max_total_groups: 10000
    max_group_size: 10
    max_token_length: 20
  
  # === 输出 ===
  output:
    synonyms_path: ./synonyms_solr.txt
    meta_path: ./synonyms_meta.json
    stats_path: ./synonyms_stats.json
```

---

## 11. 待澄清

- (Q1) 同义词表应用模式:索引时 / 查询时 / 双向?(已暂定:索引时,见 A-006)
- (Q2) Embedding 模型选择(本地推理 vs API)?(已暂定:本地 `bge-small-zh`,见 A-003)
- (Q3) 是否需要支持多语言(英文 / 日文 / 韩文)?(本 spec 只做中英文,后续 US 可加)

---

## 12. 相关文档

- 001 spec:`specs/001-promo-recommend-agent/spec.md`(LP Agent)
- 001 增强 spec:`specs/001-data-pipeline-enhancement/spec.md`(7 维 AI 标签源)
- 002 spec:`specs/002-training-data-generator/spec.md`(独立 spec)
- 品牌词典:`configs/brand_dictionary.yaml`(本 spec 新增)
- 反义词词典:`configs/antonym_pairs.yaml`(本 spec 新增)
- 输出格式:本 spec 目录 `contracts/solr_synonyms_format.md`
- 数据模型:本 spec 目录 `data-model.md`
