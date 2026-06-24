# Contract: ES Solr 多向同义词格式 (solr_synonyms_format)

**Version**: `synonyms_v1` | **Date**: 2026-06-14
**Spec**: [../spec.md §5 FR-005](../spec.md)
**Target**: Elasticsearch 7.x+ `synonym_graph` token filter

---

## 概述

ES `synonym_graph` token filter 支持 2 种格式:
- **Solr 多向格式**(本 spec 采用):`星巴克, starbucks, STARBUCKS, 星吧克` ← 任一词检索都召回其他
- **WordNet 单向格式**:`星巴克 => starbucks, STARBUCKS` ← 只从主名映射

LP Agent 场景是"用户搜任一词召回所有同义商品",**选 Solr 多向格式**。

---

## 文件

| 文件 | 用途 |
|------|------|
| `synonyms_solr.txt` | 主输出(ES `synonym_graph` filter 直接消费) |
| `synonyms_meta.json` | 元信息(版本 / 生成时间 / 3 源贡献 / 模型版本) |
| `synonyms_stats.json` | 统计(组数 / 平均词数 / 品类覆盖 / 反义词拒收数) |

---

## Solr 格式规范

### 1. 1 行 1 组

```text
# 同义词词表 (synonyms_v1)
# Generated at: 2026-06-14T10:00:00Z
# Source distribution: rule=35%, llm=45%, embedding=20%
# Total groups: 234
星巴克, starbucks, STARBUCKS, 星吧克
咖啡, coffee, 拿铁, latte
肯德基, KFC, kfc, 肯打鸡
麦当劳, McDonald's, mcdonald, 麦当牢
瑞幸, luckin, luckin coffee, 瑞幸咖啡
喜茶, HEYTEA, heytea, 喜茶店
奈雪, nayuki, 奈雪茶
蜜雪冰城, 蜜雪, MIXUE, 蜜雪冰城店
一点点, 1點點, 1点點
汉堡, burger, 汉堡包
披萨, pizza, 匹萨
咖啡店, coffee shop, 咖啡馆
```

### 2. 编码规则

| 规则 | 说明 |
|------|------|
| **行分隔** | LF (`\n`) 或 CRLF (`\r\n`),ES 两种都接受 |
| **组分隔** | 英文逗号 + 空格 `, `(注意逗号后空格) |
| **注释** | `#` 开头的行,ES 跳过 |
| **空行** | 不允许(ES 视为空组,会报错) |
| **末尾换行** | 必须有最后 1 个 `\n` |
| **编码** | UTF-8(无 BOM) |
| **大小写** | 保留原样,ES analyzer 处理 |
| **空格** | 词内可含空格(短语),如 `"Mc Donald's"`(逗号分隔) |
| **特殊字符** | `,` / `#` / `\n` 不可在词内,需预处理剔除 |

### 3. 词内空格 / 引号

| 形式 | ES 行为 |
|------|---------|
| `星巴克 拿铁` | 视为 1 个 2-token 短语 |
| `Mc Donald's` | 视为 1 个 1-token 短语(单引号在 Solr 格式中不需转义) |
| `"星巴克 拿铁"`(带引号) | 视为字面量 1 个词(可能不符合预期) |

**建议**:词内含空格时**不**用引号包裹,让 ES analyzer 按 token 处理。

### 4. 长度限制

- **单词长度**:≤ 20 字符(超过截断,FR-004)
- **每组词数**:2~10(超过 10 拆组,FR-004)
- **总组数**:≤ 10000(超过按 source 优先级截断,SC-005)
- **文件大小**:≤ 10 MB(超过 ES 加载可能慢,建议切分)

### 5. 注释行

脚本自动在文件头生成:
```text
# 同义词词表 (synonyms_v1)
# Generated at: 2026-06-14T10:00:00Z
# Source distribution: rule=35%, llm=45%, embedding=20%
# Total groups: 234
# LLM model: claude-haiku-4-5
# Embedding model: bge-small-zh
```

---

## ES 集成示例

### 7.x index settings

```json
{
  "settings": {
    "analysis": {
      "filter": {
        "synonym_graph_filter": {
          "type": "synonym_graph",
          "synonyms_path": "synonyms_solr.txt",
          "updateable": true
        }
      },
      "analyzer": {
        "index_analyzer": {
          "type": "custom",
          "tokenizer": "ik_max_word",
          "filter": ["lowercase", "synonym_graph_filter"]
        },
        "search_analyzer": {
          "type": "custom",
          "tokenizer": "ik_max_word",
          "filter": ["lowercase", "synonym_graph_filter"]
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "item_title": {
        "type": "text",
        "analyzer": "index_analyzer",
        "search_analyzer": "search_analyzer"
      }
    }
  }
}
```

**注意**:
- 用 `synonym_graph` 而非 `synonym`(graph 版本支持多 token 同义词,7.x 推荐)
- 索引和查询都用同一套 analyzer(本 spec A-006:只在索引时应用)
- `updateable: true` 支持热加载(运营更新 synonyms_solr.txt 后,ES 自动 reload,无需重建索引)

---

## 元信息 schema(`synonyms_meta.json`)

```json
{
  "_format_version": "synonyms_v1",
  "generated_at": "2026-06-14T10:00:00Z",
  "source_distribution": {
    "rule": 0.35,
    "llm": 0.45,
    "embedding": 0.20
  },
  "total_groups": 234,
  "total_tokens": 891,
  "antonym_rejected_count": 0,
  "llm_model": "claude-haiku-4-5",
  "embedding_model": "bge-small-zh",
  "truncated": false
}
```

字段说明:

| 字段 | 类型 | 说明 |
|------|------|------|
| `_format_version` | string | 固定 `"synonyms_v1"` |
| `generated_at` | string (ISO8601) | 生成时间(UTC) |
| `source_distribution` | object<float> | 3 源贡献占比,和 = 1.0(允许 ±0.01 误差) |
| `total_groups` | int | 实际写入的组数(可能 < 输入,被截断时记入 truncated) |
| `total_tokens` | int | 所有词的总 token 数 |
| `antonym_rejected_count` | int | 反义词拒收组数(应 = 0,SC-004) |
| `llm_model` | string | LLM 模型 ID |
| `embedding_model` | string | embedding 模型 ID(可空,降级时) |
| `truncated` | bool | true = 总组数超 10000,被截断 |

---

## 统计 schema(`synonyms_stats.json`)

```json
{
  "total_groups": 234,
  "avg_group_size": 3.8,
  "category_coverage": {
    "咖啡": 45,
    "快餐": 38,
    "奶茶": 62,
    "烘焙": 22,
    "便利店": 15,
    "其他": 52
  },
  "antonym_rejected_count": 0,
  "source_overlap": {
    "rule_llm": 0.12,
    "rule_embedding": 0.05,
    "llm_embedding": 0.18,
    "all_three": 0.03
  },
  "top_10_canonical": [
    "星巴克", "咖啡", "肯德基", "麦当劳", "瑞幸",
    "喜茶", "奶茶", "拿铁", "汉堡", "一点点"
  ]
}
```

字段说明:

| 字段 | 类型 | 说明 |
|------|------|------|
| `total_groups` | int | 总组数 |
| `avg_group_size` | float | 平均每组词数 |
| `category_coverage` | object<int> | 按品类统计的组数(基于 `BrandEntry.category` 或 LLM 推断) |
| `antonym_rejected_count` | int | 反义词拒收数(应 = 0) |
| `source_overlap` | object<float> | 3 源两两 / 三者交集比例,3 源合并有效性的指标 |
| `top_10_canonical` | array<string> | 出现频率最高的 10 个主名 |

---

## 兼容性约定

- ES 7.x+ 直接支持 Solr 格式
- ES 6.x 需用 `synonym`(非 graph),建议升级
- 升级 `_format_version`:`synonyms_v1` → `v2` 必须保留旧版解析能力
- 删除旧组:直接编辑 `synonyms_solr.txt`,ES `updateable: true` 自动 reload

---

## 校验示例

```bash
# 1. 解析每行(忽略 # 注释)
grep -v "^#" synonyms_solr.txt | head -10

# 2. 统计组数
grep -v "^#" synonyms_solr.txt | grep -v "^$" | wc -l

# 3. 检查无空行
awk 'NF==0 {print NR": empty line"}' synonyms_solr.txt

# 4. 检查无 # 注释中混入逗号
grep -E "^#.*," synonyms_solr.txt  # 应为空

# 5. ES 端验证:索引 100 个商品 + 20 个查询,召回率 ≥ 90%
curl -X GET "localhost:9200/items/_search?q=星巴克&analyzer=search_analyzer"
```

---

## 反例(不应出现在主输出)

```text
# ❌ 反例 1:反义词合并
好, 坏                              # 拒收,SC-004

# ❌ 反例 2:弱关联合并
咖啡, 茶                            # 拒收,品类不同

# ❌ 反例 3:单词过长
这里是一个非常非常长的商品名称单, 短名   # 截断或拒收,FR-004

# ❌ 反例 4:组内词数过多
a, b, c, d, e, f, g, h, i, j, k, l  # 拆组,FR-004

# ❌ 反例 5:空行
星巴克, starbucks

                                  ← 空行,不允许
咖啡, coffee
```

以上反例都应在 merger 阶段被 antomym_filter / 长度限制 / dedup 拒收,不进入 `synonyms_solr.txt`。
