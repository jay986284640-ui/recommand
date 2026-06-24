# Contract: Stage 1 输出 Schema (`item_tags_v2`)

**Version**: `item_tags_v2` | **Date**: 2026-06-22
**Spec**: [../spec.md](../spec.md) (v2.4)
**Companion**: [param_op_types_v2.md](./param_op_types_v2.md) · [hive_read_v1.md](./hive_read_v1.md)
**Supersedes**: `training_data_format_v1.md`(v1,Stage 1 的 7 维口味标签 schema;**不兼容**)

---

## 概述

`item_tags.jsonl` 是 Stage 1 的主输出,每行 1 个商品的 8 维标签 + 来源标记。**任何字段集变更必须 bump 版本号**(本版 v2)。

本文档是 Stage 1 ↔ Stage 2 / 下游训练管线的**生产契约**;违反即视为 break change。

---

## 文件清单

| 文件 | 用途 | 写入模式 |
|------|------|---------|
| `item_tags.jsonl` | Stage 1 主输出 | `overwrite`(全量) / `append`(增量) |
| `tag_enrichment_failures.jsonl` | Stage 1 失败明细 | `append` |
| `tag_enrichment_state.parquet` | 增量指纹(4 元组) | `overwrite` |
| `tables_meta.json` | SQL 解析产物(Stage 1 启动时) | `overwrite` |

---

## 主样本 schema(`item_tags.jsonl`)

```json
{
  "item_id": "mt-100234",
  "item_type": "meituan_shop",
  "raw_record": {
    "Str_Id": "100234",
    "Str_Nm": "星巴克(南京西路店)",
    "Cat_Id_NEW": 5,
    "Avg_Prc": "45",
    "Lng": "121.456789",
    "Lat": "31.234567",
    "etl_dt": "20260620"
  },
  "tags": {
    "category": "咖啡",
    "consumable_type": "drink",
    "merchant": "星巴克",
    "avg_prc": "30-50",
    "distance": null,
    "age": "25-35",
    "occasion": "下午茶",
    "taste": ["甜"]
  },
  "tag_source": {
    "category": "raw",
    "consumable_type": "derived",
    "merchant": "raw",
    "avg_prc": "raw",
    "distance": "geo",
    "age": "ai",
    "occasion": "raw",
    "taste": "ai"
  },
  "enriched_at": "2026-06-22T10:00:00Z",
  "llm_model": "claude-haiku-4-5",
  "_format_version": "item_tags_v2"
}
```

---

## 字段详解

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `item_id` | string | ✅ | 命名空间隔离:`mt-<Str_Id>` / `self-<shopId>` / `cpn-<couponId>` |
| `item_type` | string | ✅ | `meituan_shop` / `self_shop` / `coupon` |
| `raw_record` | object | ✅ | Hive 原始列子集(**已剔除敏感列**);键名 = DDL 列名全小写;包含 `etl_dt` |
| `raw_record.shop_lng` / `shop_lat` | float? | ❌ | 透传到 raw_record 顶层(便于 Stage 1 后续或下游运行时使用) |
| `tags` | object | ✅ | 8 个固定字段,**顺序固定**(见下);值缺失 → `null` |
| `tags.category` | string? | ❌ | `dim_dictionary.category.values` 之一 |
| `tags.consumable_type` | string? | ❌ | `food / drink / mixed / none` |
| `tags.merchant` | string? | ❌ | `dim_dictionary.merchant.values` 之一(可经 `brand_dictionary.yaml` 扩量) |
| `tags.avg_prc` | string? | ❌ | 桶 ID:`"0-30" / "30-50" / "50-100" / "100-200" / "200+"` |
| `tags.distance` | null | ✅ | **本字段始终 null**;`distance` 与 lng/lat 解耦(SFT 阶段字典直采) |
| `tags.age` | string? | ❌ | 桶 ID:`"18-25" / "25-35" / "35-45" / "45-55" / "55+"` |
| `tags.occasion` | string? | ❌ | `dim_dictionary.occasion.values` 之一 |
| `tags.taste` | string[]? | ❌ | `dim_dictionary.taste.values` 子集(可空数组不允许) |
| `tag_source` | object | ✅ | 8 维每维来源标记(见下) |
| `enriched_at` | string(ISO8601) | ✅ | UTC,Stage 1 完成时间 |
| `llm_model` | string | ✅ | 用的 LLM 模型 ID(便于按版本切片) |
| `_format_version` | string | ✅ | 固定 `"item_tags_v2"` |

---

## `tags` 字段顺序(固定)

```text
1. category
2. consumable_type
3. merchant
4. avg_prc
5. distance
6. age
7. occasion
8. taste
```

顺序在 writer 写盘时固定,便于人读 + Stage 2 拼 batch。

---

## `tag_source` 三族枚举语义

| 字段 | 允许取值 | 永不取 |
|------|---------|--------|
| `tag_source.category` | `raw / ai / missing` | — |
| `tag_source.consumable_type` | `derived / ai / missing` | `raw` / `geo` |
| `tag_source.merchant` | `raw / ai / missing` | — |
| `tag_source.avg_prc` | `raw / ai / missing` | — |
| `tag_source.distance` | `geo / missing` | `raw` / `ai` |
| `tag_source.age` | `raw / ai / missing` | — |
| `tag_source.occasion` | `raw / ai / missing` | — |
| `tag_source.taste` | `raw / ai / missing` | — |

**含义**:

- `raw`:从源表显式列直接抽取(无需 LLM)。
- `derived`:从其他维度确定性推导(仅 `consumable_type`,由 `category` 经 `consumable_type_map.yaml` 映射)。
- `geo`:从源表 lng/lat 透传成功,数据可用于下游 LP Agent 运行时(仅 `distance`)。
- `ai`:LLM 推断并落字典。
- `missing`:源数据缺失 / 越界 / 不可解析,tag 值为 `null`。

**不变式**:`tag == null` ⇔ `tag_source == missing`。

---

## `raw_record` 必剔除字段(A-008)

`HiveReader.read()` 出口 MUST 移除以下列:

- `MASTERCARD_CUST_ID`(`CDM_ADM_CUST_INFO_STAT_F`)
- `Crt_Psn_Id` / `Updt_Psn_Id` / `Opr_Psn_Id`(几乎所有 o2o 表)
- `creator` / `updatePerson`(`o2o_new_gut_coupon_template`)
- 配置 `sensitive_columns_blocklist` 中声明的其他列

任何泄露由单测 `test_hive_reader.py::test_sensitive_drop` 拦截。

---

## 失败样本 schema(`tag_enrichment_failures.jsonl`)

```json
{
  "item_id": "mt-999999",
  "raw_response": "...LLM 原始输出(若可获取)...",
  "error": "JSONDecodeError",
  "error_detail": "Expecting value: line 1 column 1 (char 0)",
  "occurred_at": "2026-06-22T10:00:00Z"
}
```

| `error` 候选 | 含义 |
|-------------|------|
| `JSONDecodeError` | LLM 返回非 JSON |
| `MissingField` | 缺 `messages` / `params` / `intent`(v1 语义);v2 缺 8 维任一字段名 |
| `DictValidation` | `tag_source.distance` 取了 `geo / missing` 之外的值,或 `consumable_type` 取了非枚举值,等等 |
| `Timeout` | LLM 调用超时(> 15s) |
| `GeoMissing` | `distance` 透传失败(lng/lat 缺失 / 越界),由 FR-008b 触发 |
| `Other` | 其他异常 |

---

## 状态表 schema(`tag_enrichment_state.parquet`)

| 字段 | 类型 | 说明 |
|------|------|------|
| `item_id` | string | 商品 ID |
| `raw_md5` | string | `raw_record` 字段级 md5(除 `etl_dt` 外) |
| `dict_version` | string | `dim_dictionary.yaml._meta.version` × `consumable_type_map.yaml._meta.version` 联合 md5 |
| `source_partition` | string | `etl_dt`(`YYYYMMDD`) |
| `enriched_at` | timestamp | 上次完成时间(UTC) |
| `llm_model` | string | 用的模型版本 |

**重算规则**(D-003):4 元组 `item_id + raw_md5 + dict_version + source_partition` 任一变化即重算。

---

## 兼容性约定

- **Stage 2 reader MUST**:`assert sample["_format_version"] == "item_tags_v2"`;不匹配则报 TypeError 并列出兼容方案。
- **Stage 2 reader MAY** 兼容 `item_tags_v1`(7 维):忽略缺失字段,`tag_source.distance` 强制视为 `missing`,`distance` 视为 null;反向不兼容(v2 reader 读 v1 → `tag_source.consumable_type` 缺字段报错)。
- 新增字段:`_format_version` 升到 `v3`,旧版本仍可读。
- 删除字段:需 1 个版本过渡期(`v2` 标 deprecated,`v3` 才删)。

---

## 校验示例(jq)

```bash
# 1. 每行可解析
jq -c . item_tags.jsonl | head -3

# 2. 8 维 tags 字段顺序
jq -c '.tags | keys' item_tags.jsonl | head -3
# → ["category","consumable_type","merchant","avg_prc","distance","age","occasion","taste"]

# 3. tag_source 合法性
jq -r '.tag_source.distance' item_tags.jsonl | sort -u
# → "geo"  "missing"   (不允许出现 "raw" / "ai")

jq -r '.tag_source.consumable_type' item_tags.jsonl | sort -u
# → "ai"  "derived"  "missing"

# 4. 不变式 (tag == null ⇔ tag_source == missing)
jq -r '.tags, .tag_source' item_tags.jsonl | jq -s '
  .[] | select(
    (.tags.distance == null and .tag_source.distance != "missing") or
    (.tags.distance != null and .tag_source.distance == "missing")
  )
' | head -3
# → 应为空

# 5. sensitive 列不应在 raw_record
jq -r '.raw_record | keys[]' item_tags.jsonl | grep -E "MASTERCARD|Crt_Psn|Opr_Psn|creator|updatePerson"
# → 应为空

# 6. 字典合法率(SC-002)
jq -r '.tags.merchant' item_tags.jsonl | grep -v null | sort -u | head
```

---

## 示例:Python reader

```python
import json
from pathlib import Path

samples = []
for line in Path("item_tags.jsonl").read_text().splitlines():
    if not line.strip():
        continue
    sample = json.loads(line)
    if sample["_format_version"] != "item_tags_v2":
        raise TypeError(f"Unknown version: {sample}")
    samples.append(sample)

# samples 是 list[dict],喂给 Stage 2 SFTGenerator
```