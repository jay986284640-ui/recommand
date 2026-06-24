# Contract: Stage 2 输出 Schema (`sft_corpus_v2`)

**Version**: `sft_corpus_v2` | **Date**: 2026-06-22
**Spec**: [../spec.md](../spec.md) (v2.4)
**Companion**: [item_tags_v2.md](./item_tags_v2.md) · [param_op_types_v2.md](./param_op_types_v2.md)
**Supersedes**: `training_data_format_v1.md`(v1 字段集;**不兼容**)

---

## 概述

`sft_corpus.jsonl` 是 Stage 2 的主输出,每行 1 个 LP Agent 训练样本(8 维 `params` ground-truth + 1~5 轮对话)。

本文档是 Stage 2 ↔ 下游训练管线的**生产契约**;违反即视为 break change。

---

## 文件清单

| 文件 | 用途 | 写入模式 |
|------|------|---------|
| `sft_corpus.jsonl` | Stage 2 主输出 | `overwrite`(全量) / `append`(增量) |
| `sft_failures.jsonl` | Stage 2 失败明细 | `append` |
| `cold_start_items.jsonl` | Stage 1 后 8 维全 null 的 item | `overwrite` |
| `cleaned_training_data.jsonl` | 清洗后样本(FR-017) | `overwrite` |
| `cleaning_failures.jsonl` | 清洗删除明细 | `append` |
| `distribution_report.json` | 8 项分布指标 + 警告 | `overwrite` |
| `train.jsonl` / `val.jsonl` / `test.jsonl` | 80/10/10 划分 | `overwrite`(3 文件) |
| `summary.json` | 全流程汇总 | `overwrite` |

---

## 主样本 schema(`sft_corpus.jsonl`)

```json
{
  "item_id": "mt-100234",
  "item_type": "meituan_shop",
  "intent": "search_item",
  "messages": [
    {"role": "user",      "content": "想喝咖啡,500 米以内有没有"},
    {"role": "assistant", "content": "附近 200 米有星巴克,需要看菜单吗"},
    {"role": "user",      "content": "好,下午想和同事一起,不要太甜的"}
  ],
  "params": {
    "category":         {"op": "in", "values": ["咖啡"]},
    "consumable_type":  {"op": "eq", "values": "drink"},
    "merchant":         null,
    "avg_prc":          null,
    "distance":         {"op": "in", "values": ["0-500"]},
    "age":              null,
    "occasion":         {"op": "in", "values": ["下午茶"]},
    "taste":            {"op": "not_in", "values": ["甜"]}
  },
  "order_by": "distance",
  "negative": false,
  "negative_type": null,
  "covered_dims": ["category", "consumable_type", "distance", "occasion", "taste"],
  "forced_coverage": false,
  "generated_at": "2026-06-22T10:05:00Z",
  "llm_model": "claude-haiku-4-5",
  "_format_version": "sft_corpus_v2"
}
```

---

## 字段详解

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `item_id` | string | ✅ | 同 `item_tags.jsonl.item_id` |
| `item_type` | string | ✅ | `meituan_shop / self_shop / coupon` |
| `intent` | string | ✅ | `search_item / use_coupon / pay / view_order / browse` |
| `messages` | array<MessageTurn> | ✅ | 长度 1~5,首条 `role=user`,末条不限 |
| `messages[].role` | string | ✅ | `user / assistant / system` |
| `messages[].content` | string | ✅ | 自然语言 UTF-8,**不含 tab / 控制字符 / 连续 ≥3 换行**;长度 ≥ 10 字 |
| `params` | object<8 dim> | ✅ | 8 个固定 key,顺序固定,缺失 → `null`(详见 `param_op_types_v2.md`) |
| `params.<dim>.op` | string | ✅(非 null) | `eq / in / contains / not_in`(本批) |
| `params.<dim>.values` | string \| string[] | ✅(非 null) | 跟 `op` 对应 |
| `order_by` | string \| null | ✅ | `distance / price / rating / time / null` |
| `negative` | boolean | ✅ | `true` = 负样本(默认 `false`) |
| `negative_type` | string \| null | ✅ | `null` / `reject` / `pivot` / `unsatisfiable`;`negative=true` 时 MUST 非 null |
| `covered_dims` | array<string> | ✅ | 该样本 params 实际覆盖的维度列表;用于 SC-005 自检 |
| `forced_coverage` | boolean | ✅ | `true` = FR-011 强制补样(单 item 内兜底覆盖遗漏维) |
| `generated_at` | string(ISO8601) | ✅ | UTC |
| `llm_model` | string | ✅ | |
| `_format_version` | string | ✅ | 固定 `"sft_corpus_v2"` |

---

## `params` 字段顺序(固定)

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

---

## `intent` ↔ `item_type` 默认倾向(FR-016)

| item_type | intent 倾向(主) | 次要 |
|-----------|----------------|------|
| `meituan_shop` | `search_item` | `browse` |
| `self_shop` | `search_item` | `browse` |
| `coupon` | `use_coupon`, `pay` | `search_item` |

由 prompt 注入,非硬约束(每类占比下限 3%)。

---

## 负样本类型(`negative_type`)

| 取值 | 含义 | 用户表述举例 |
|------|------|------------|
| `reject` | 拒绝某条件 | "不要辣的"、"不要远的" |
| `pivot` | 切换意图 | "不看咖啡了,看奶茶" |
| `unsatisfiable` | 无满足项 | "附近没这种店" |

`negative=true` ⇒ `negative_type` MUST ∈ {reject, pivot, unsatisfiable};反向:`negative=false` ⇒ `negative_type = null`。

`params` 在负样本中仍正常填;`order_by = null`;`order_by=distance` 时 `params.distance` 通常以 `not_in` op 表达。

---

## 失败样本 schema(`sft_failures.jsonl`)

```json
{
  "item_id": "cpn-555555",
  "raw_response": "...LLM 原始输出...",
  "target_params": {
    "distance": {"op": "in", "values": ["0-500"]},
    "consumable_type": {"op": "eq", "values": "drink"}
  },
  "error": "JSONDecodeError",
  "error_detail": "Expecting value: line 1 column 1 (char 0)",
  "occurred_at": "2026-06-22T10:05:00Z"
}
```

| `error` 候选 | 含义 |
|-------------|------|
| `JSONDecodeError` | LLM 返回非 JSON |
| `MissingField` | 缺 `messages` / `params` / `intent` / `_format_version` |
| `DictValidation` | `params.<dim>.values` 不在字典候选集 / `op` 不属于本批 4 类 |
| `DistanceAlignmentError` | LLM 自然语言表述与 ground-truth `params.distance` 不一致(检测方法:关键词 / 模板匹配) |
| `CoverageFailure` | 同 item 累计达到 `count_per_item` 上限仍漏维度,且未触发 `forced_coverage` |
| `Timeout` | LLM 调用超时 |
| `Other` | 其他异常 |

---

## 清洗规则(`FR-017`,7 类)

| # | 规则 | 默认阈值 | always on |
|---|------|---------|-----------|
| 1 | 完全相同去重(text_hash md5 of `messages + params`) | — | ✅ |
| 2 | 消息过短过滤 | 任一 `content` < 10 字 | 默认 10 字,可配 | ✅ |
| 3 | 模板重复降频(n-gram 首句占比) | > 30% 触发降频到 ≤ 20% | ✅ |
| 4 | params 8 维全 null | 删除 | ✅ |
| 5 | 控制字符过滤(content 含连续 ≥ 3 换行 / tab / 控制字符) | 删除 | ✅ |
| 6 | params 字段不在 8 维白名单 | 删除 | ✅ |
| 7 | 对话轮次异常(messages 长度 ∉ [1, 5]) | 删除 | ✅ |

`text_hash` 计算口径:

```python
text_hash = md5(
    json.dumps(sample["messages"], sort_keys=True).encode() +
    json.dumps(sample["params"],   sort_keys=True).encode() +
    json.dumps({"intent": sample["intent"], "order_by": sample["order_by"]}, sort_keys=True).encode()
).hexdigest()
```

---

## 分布报告(`distribution_report.json`)

| 指标 | 目标 | 不达标动作 |
|------|------|------------|
| 5 类 intent 比例 | 每类 ≥ 3% | 报警 + 过采样 |
| 8 维 params 非 null 比例 | 每维 ≥ 5% | 报警 + 过采样 |
| 4 op 比例 | `not_in` ≥ 3% | 报警 + 过采样 |
| 负样本比例 | `negative_ratio` ± 0.02 | 报警 |
| 对话轮次分布 | 1/2/3/4/5 = 10/20/35/25/10% ±5% | 报警 |
| 消息平均长度 | 20~80 字 | 报警 |
| 字典覆盖率 | 每个候选值至少 5 个样本 | 报警 |
| params 组合多样性 | 1000 样本 ≥ 200 唯一组合 | 报警 |

**`consumable_type` 子指标**:3~4 个值(`food / drink / mixed`,`none` 不计下限)每类 ≥ 5%。

完整 schema 见 `data-model.md` §实体 9。

---

## 划分(`train.jsonl` / `val.jsonl` / `test.jsonl`)

行级 schema 与 `sft_corpus.jsonl` 完全一致;按 `item_id` md5 hash % 100 划分:

```python
def split_key(item_id: str) -> str:
    h = int(hashlib.md5(item_id.encode()).hexdigest(), 16) % 100
    if h < 80:   return "train"
    elif h < 90: return "val"
    else:        return "test"
```

**约束**(SC-009):

- 默认 80/10/10;比例可配(`train_ratio / val_ratio / test_ratio`)。
- 任一 `item_id` MUST NOT 跨集合(0 泄露)。
- 0 泄露校验在 writer 出口必做,失败即报警 + 重写。

`_format_version` = `"train_split_v1"`。

---

## 兼容性约定

- 训练管线 reader MUST:`assert sample["_format_version"] == "sft_corpus_v2"`;不匹配则报 TypeError。
- 训练管线 reader 可降级读 `sft_corpus_v1`(忽略新增字段 `negative_type / covered_dims / forced_coverage`,7 维 `params` 中 `consumable_type` 视为缺失);反向不兼容。
- 新增字段:`_format_version` 升到 `v3`,旧版本仍可读。
- 删除字段:1 个版本过渡期。

---

## 校验示例(jq)

```bash
# 1. 每行可解析
jq -c . sft_corpus.jsonl | head -3

# 2. params 字段顺序(应固定 8 维)
jq -c '.params | keys' sft_corpus.jsonl | head -3
# → ["category","consumable_type","merchant","avg_prc","distance","age","occasion","taste"]

# 3. 字典合法率(merchant 必在 brand_dictionary)
jq -r '.params.merchant.values[]?' sft_corpus.jsonl | sort -u

# 4. 负样本类型与 negative 标志一致
jq -r 'select(.negative == true) | .negative_type' sft_corpus.jsonl | sort -u
# → "pivot"  "reject"  "unsatisfiable"

jq -r 'select(.negative == false) | .negative_type' sft_corpus.jsonl | sort -u
# → null

# 5. 强制补样数(SC-005 自检)
jq -s 'map(select(.forced_coverage == true)) | length' sft_corpus.jsonl

# 6. 单 item 覆盖率(SC-005 自检:同 item 样本集合并后是否覆盖该 item 全部非 null 维)
jq -s 'group_by(.item_id) | map({
  item_id: .[0].item_id,
  covered: (map(.covered_dims[]) | unique)
})' sft_corpus.jsonl | head

# 7. 0 数据泄露(SC-009)
diff <(jq -r '.item_id' train.jsonl | sort -u) \
     <(jq -r '.item_id' val.jsonl | sort -u)
# → 空
```

---

## 示例:Python reader

```python
import json
from pathlib import Path

samples = []
for line in Path("sft_corpus.jsonl").read_text().splitlines():
    if not line.strip():
        continue
    sample = json.loads(line)
    assert sample["_format_version"] == "sft_corpus_v2", f"Unknown version: {sample}"
    # order_by 与 params.distance 的弱一致性建议(非强制)
    if sample["params"]["distance"] is not None and sample["order_by"] == "distance":
        pass  # OK
    samples.append(sample)
```