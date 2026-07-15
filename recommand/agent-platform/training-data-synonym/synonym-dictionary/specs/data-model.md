# Data Model: ES 检索同义词词表生成

**Version**: `v1` | **Date**: 2026-06-14
**Spec**: [./spec.md](./spec.md)
**Companion**: [./contracts/solr_synonyms_format.md](./contracts/solr_synonyms_format.md)

---

## 概述

ES 检索同义词子包(`synonym/`)涉及 **5 个核心实体 + 1 个统计实体**。
本数据模型定义 **Python dataclass** 形式(本子包用 pandas 读 `item_features_ai.jsonl` + 本地 embedding 推理,Spark 不直接用)。

---

## 实体 1:`SynonymGroup`(主输出元素)

| 字段 | Python 类型 | JSON 类型 | 必填 | 说明 |
|------|------------|-----------|------|------|
| `group_id` | `str` | string | ✅ | uuid(便于追踪) |
| `canonical` | `str` | string | ✅ | 主名(显示用,如"星巴克") |
| `variants` | `List[str]` | array | ✅ | 所有变体(含 canonical),如 `["星巴克", "Starbucks", "STARBUCKS", "星吧克"]` |
| `source` | `List[str]` | array | ✅ | 来源标记,候选 `["rule", "llm", "embedding"]`,可多选 |
| `confidence` | `float` | number | ✅ | 置信度 0~1(rule=1.0 / llm=0.8 / embedding=高置信 0.9 / 中置信 0.6) |
| `category` | `Optional[str]` | string\|null | ❌ | 品类(咖啡/快餐/奶茶/烘焙/便利店),用于统计覆盖 |
| `merged_from` | `Optional[List[str]]` | array | ❌ | 合并来源的 group_id 列表(3 源合并时记录) |

**约束**:
- `len(variants) >= 2`(无单元素组)
- `canonical in variants`
- `len(source) >= 1`,合并时取并集
- `confidence` 合并时取最大值

**dataclass 草图**:
```python
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class SynonymGroup:
    group_id: str
    canonical: str
    variants: List[str]
    source: List[str]  # ["rule", "llm", "embedding"]
    confidence: float = 1.0
    category: Optional[str] = None
    merged_from: Optional[List[str]] = None
```

---

## 实体 2:`SynonymEntry`(variant 元素)

| 字段 | Python 类型 | JSON 类型 | 必填 | 说明 |
|------|------------|-----------|------|------|
| `token` | `str` | string | ✅ | 单个词 |
| `lang` | `Literal["zh", "en", "mixed"]` | string | ✅ | 语言 |
| `length` | `int` | int | ✅ | 字符数(用于长度限制校验) |
| `is_canonical` | `bool` | boolean | ✅ | 是否主名 |

**dataclass 草图**:
```python
from typing import Literal

@dataclass
class SynonymEntry:
    token: str
    lang: Literal["zh", "en", "mixed"]
    length: int
    is_canonical: bool = False
```

---

## 实体 3:`BrandEntry`(规则词典元素)

`configs/dim_dictionary_snapshot.yaml.yaml` 的元素。

| 字段 | Python 类型 | YAML 类型 | 必填 | 说明 |
|------|------------|-----------|------|------|
| `canonical` | `str` | string | ✅ | 品牌主名 |
| `variants` | `List[str]` | list | ✅ | 品牌变体(含主名,通常 2~10 个) |
| `category` | `str` | string | ✅ | 品类:咖啡/快餐/奶茶/烘焙/便利店/其他 |

**约束**:
- `len(variants) >= 2`
- `canonical in variants`
- 变体去重,无空字符串

**dataclass 草图**:
```python
@dataclass
class BrandEntry:
    canonical: str
    variants: List[str]
    category: str

    def to_synonym_group(self, group_id: str) -> SynonymGroup:
        return SynonymGroup(
            group_id=group_id,
            canonical=self.canonical,
            variants=self.variants,
            source=["rule"],
            confidence=1.0,
            category=self.category,
        )
```

**yaml 示例**:
```yaml
brands:
  - canonical: 肯德基
    variants: [肯德基, KFC, kfc, 肯打鸡, 肯德鸡, KFC宅急送]
    category: 快餐
  - canonical: 星巴克
    variants: [星巴克, Starbucks, starbucks, STARBUCKS, 星吧克, 星巴克咖啡]
    category: 咖啡
```

---

## 实体 4:`AntonymPair`(反义词对)

`configs/antonym_pairs.yaml` 的元素,用于 FR-004 合并时的反义词拒收。

| 字段 | Python 类型 | YAML 类型 | 必填 | 说明 |
|------|------------|-----------|------|------|
| `word_a` | `str` | string | ✅ | 反义词 1 |
| `word_b` | `str` | string | ✅ | 反义词 2 |
| `category` | `str` | string | ✅ | 反义类型:程度/温度/味道/方向/状态 |

**约束**:
- `word_a != word_b`
- 全小写比对(避免大小写漏检)
- 50+ 对预置

**dataclass 草图**:
```python
@dataclass
class AntonymPair:
    word_a: str
    word_b: str
    category: str  # 程度/温度/味道/方向/状态

    def matches(self, group: SynonymGroup) -> bool:
        """检查 group 是否含此反义词对"""
        variants_lower = {v.lower() for v in group.variants}
        return self.word_a.lower() in variants_lower and self.word_b.lower() in variants_lower
```

**yaml 示例**:
```yaml
antomym_pairs:
  - {word_a: 好,   word_b: 坏,   category: 状态}
  - {word_a: 大,   word_b: 小,   category: 程度}
  - {word_a: 热,   word_b: 冷,   category: 温度}
  - {word_a: 甜,   word_b: 咸,   category: 味道}
  - {word_a: 浓,   word_b: 淡,   category: 味道}
```

---

## 实体 5:`EmbeddingCluster`(embedding 聚类结果)

| 字段 | Python 类型 | JSON 类型 | 必填 | 说明 |
|------|------------|-----------|------|------|
| `cluster_id` | `str` | string | ✅ | uuid |
| `tokens` | `List[str]` | array | ✅ | 聚类内的所有词 |
| `avg_distance` | `float` | number | ✅ | 平均余弦距离(0=完全相同,1=完全不同) |
| `confidence` | `Literal["high", "medium", "low"]` | string | ✅ | < 0.15 高置信,0.15~0.30 中置信,> 0.30 低置信(不合并) |
| `category` | `Optional[str]` | string | ❌ | 推断的品类(由聚类中心词决定) |

**dataclass 草图**:
```python
from typing import Literal

@dataclass
class EmbeddingCluster:
    cluster_id: str
    tokens: List[str]
    avg_distance: float
    confidence: Literal["high", "medium", "low"]
    category: Optional[str] = None
```

**生成流程**:
```
item_title + item_description 拼接
  ↓ 分词(ik_max_word / jieba)
所有 token
  ↓ embedding 推理(bge-small-zh)
N 个 512 维向量
  ↓ 余弦相似度矩阵
  ↓ 阈值过滤(< 0.30)
  ↓ 连通分量
M 个聚类
```

---

## 实体 6:`SynonymStats`(统计输出)

`./synonyms_stats.json` 的元素,对应 spec §6 FR-006。

| 字段 | Python 类型 | JSON 类型 | 必填 | 说明 |
|------|------------|-----------|------|------|
| `total_groups` | `int` | int | ✅ | 总组数 |
| `avg_group_size` | `float` | number | ✅ | 平均每组词数 |
| `category_coverage` | `Dict[str, int]` | object | ✅ | 按品类的组数 |
| `antonym_rejected_count` | `int` | int | ✅ | 反义词拒收数(应 = 0) |
| `source_overlap` | `Dict[str, float]` | object | ✅ | 3 源两两 / 三者交集比例 |
| `top_10_canonical` | `List[str]` | array | ✅ | 出现频率最高的 10 个主名 |

**dataclass 草图**:
```python
@dataclass
class SynonymStats:
    total_groups: int
    avg_group_size: float
    category_coverage: Dict[str, int]
    antomym_rejected_count: int
    source_overlap: Dict[str, float]
    top_10_canonical: List[str]
```

---

## 实体关系图

```
                   ┌─────────────────────┐
                   │ item_features_ai    │  (001 增强产物,只读)
                   │ .jsonl              │
                   └──────────┬──────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ↓                 ↓                 ↓
   ┌─────────────────┐ ┌──────────────┐ ┌──────────────────┐
   │ dim_dictionary_snapshot.yaml        │ │ LLM 抽取器   │ │ Embedding 聚类   │
   │ (yaml 加载)     │ │ (001 复用)   │ │ (bge-small-zh)   │
   │ → BrandEntry[]  │ │              │ │ → EmbeddingCluster[]
   └────────┬────────┘ └──────┬───────┘ └────────┬─────────┘
            │                │                   │
            ↓                ↓                   ↓
       SynonymGroup    SynonymGroup        SynonymGroup
            (rule)         (llm)             (embedding)
            │                │                   │
            └────────────────┼───────────────────┘
                             ↓
                   ┌─────────────────────┐
                   │ AntonymFilter       │ ← 加载 antomym_pairs.yaml
                   │ (50+ 反义词拒收)    │
                   └──────────┬──────────┘
                              ↓
                   ┌─────────────────────┐
                   │ SynonymMerger       │  3 源合并 + 去重
                   │ (D-007:合并去重)   │  + 长度限制 (FR-004)
                   └──────────┬──────────┘
                              ↓
                   SynonymGroup[] (200~2000)
                              ↓
              ┌───────────────┴───────────────┐
              ↓                               ↓
    ┌──────────────────┐            ┌──────────────────┐
    │ ESFormatter      │            │ Stats            │
    │ → ext_synonyms.txt            │ → synonyms_stats.json
    │ (FR-005, SC-003) │            │ (FR-006)         │
    └──────────────────┘            └──────────────────┘
                              ↓
                   ┌─────────────────────┐
                   │ ES synonym_graph    │  (LP Agent 检索时消费)
                   │ filter              │
                   └─────────────────────┘
```

---

## 数据流

```
1. 读取 ./item_features_ai.jsonl                       # 001 增强产物
   ↓
2. 加载 ./configs/dim_dictionary_snapshot.yaml.yaml              # 规则源
   → List[BrandEntry]
   ↓ brand_to_synonym_groups()
3. List[SynonymGroup] (rule)                          # 50+ 组
   ↓
4. LLM 抽取(批量 16 并发,每 item 1~5 组)
   → List[SynonymGroup] (llm)                         # 50~200 组
   ↓
5. Embedding 聚类(可选,bge-small-zh 本地推理)
   → List[SynonymGroup] (embedding)                   # 30~50 组
   ↓
6. AntonymFilter(加载 antomym_pairs.yaml)
   - 检查每组是否含反义词对
   - 命中 → 拒收,写 synonym_rejections.jsonl
   ↓
7. SynonymMerger 合并 3 源:
   - 完全相同 → 留 1,source = 并集
   - 有交集 → 合并为 1 组
   - 无交集 → 各自保留
   - 长度限制(单词 ≤ 20,组 ≤ 10,总 ≤ 10000)
   ↓
8. ESFormatter → ./ext_synonyms.txt                # Solr 多向格式
   ↓
9. MetaWriter → ./synonyms_meta.json                # 元信息
   ↓
10. Stats → ./synonyms_stats.json                   # 统计
```

---

## 不在本数据模型范围

- **ES 索引 mapping / analyzer**:由 ES 运维负责,本子包只生成词表文件
- **LP Agent envelope 协议**:由 LP Agent 运行时负责
- **001 / 002 产物的内部结构**:见 001 spec §6.1 / 002 spec §6.1
