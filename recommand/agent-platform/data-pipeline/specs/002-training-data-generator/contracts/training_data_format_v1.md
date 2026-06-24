# Contract: 训练数据 jsonl 格式 (training_data_v1)

**Version**: `training_data_v1` | **Date**: 2026-06-14
**Spec**: [../spec.md §6.1](../spec.md)

---

## 概述

LP Agent 的**意图识别模型** + **提参模型** 微调所用的训练样本,1 行 1 个样本。
本格式是 LP Agent 训练管道**直接消费**的契约;任何破坏字段顺序 / 字段类型 / `_format_version` 的改动都视为 break change。

---

## 文件

| 文件 | 用途 | 写入方式 |
|------|------|----------|
| `training_data_v1.jsonl` | 主产出(训练集) | `overwrite` 模式,全量重写 |
| `training_data_failures.jsonl` | 失败样本(LLM 解析 / 字典校验) | `append` 模式,排查用 |

---

## 主样本 schema

```json
{
  "item_id": "item-123",
  "intent": "search_item",
  "messages": [
    {"role": "user",      "content": "我想喝咖啡"},
    {"role": "assistant", "content": "为您推荐附近的咖啡门店"},
    {"role": "user",      "content": "有没有离我近一点的"}
  ],
  "params": {
    "taste":          null,
    "occasion":       null,
    "ingredient":     null,
    "cuisine_region": null,
    "target_audience":null,
    "emotion_value":  null,
    "party_size":     null
  },
  "order_by": "distance",
  "negative": false,
  "generated_at": "2026-06-14T10:00:00Z",
  "llm_model": "claude-haiku-4-5",
  "_format_version": "training_data_v1"
}
```

---

## 字段详解

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `item_id` | string | ✅ | 对应 `item_features_ai.jsonl` 的 `item_id` |
| `intent` | string | ✅ | 候选:`search_item` / `use_coupon` / `pay` / `view_order` / `browse` |
| `messages` | array<MessageTurn> | ✅ | 多轮对话(1~4 轮,3 轮为主),首条必为 `role=user` |
| `messages[].role` | string | ✅ | 候选:`user` / `assistant` / `system` |
| `messages[].content` | string | ✅ | 自然语言文本,UTF-8,**不含 tab / 控制字符** |
| `params` | object<7 维> | ✅ | 7 个固定字段,顺序固定(见下),缺失 → null 补齐 |
| `params.<dim>.op` | string | ✅(非 null 时) | 候选:`eq` / `contains` / `in` / `not_in` / `gt` / `lt` / `between` |
| `params.<dim>.values` | string \| array<string> \| null | ✅(非 null 时) | 跟 `op` 类型对应,详见 `param_op_types.md` |
| `order_by` | string \| null | ✅ | 候选:`distance` / `price` / `rating` / `time` / `null`(无序) |
| `negative` | boolean | ✅ | `true` = 负样本(用户拒绝 / 转移 / 不满足),占比 10% |
| `generated_at` | string (ISO8601) | ✅ | UTC,LLM 调用完成时间 |
| `llm_model` | string | ✅ | 用的 LLM 模型 ID(便于按版本切片) |
| `_format_version` | string | ✅ | 固定 `"training_data_v1"`,便于训练管道做 schema 兼容判断 |

---

## `params` 字段顺序(固定)

```text
1. taste
2. occasion
3. ingredient
4. cuisine_region
5. target_audience
6. emotion_value
7. party_size
```

顺序在 writer 写盘时固定,便于人读 + 训练时按列拼 batch。

---

## 字段值边界

- **None / null**:`params` 字段缺失 → `null`;`values` 缺失 → `null`(不写空数组)
- **空字符串**:不允许(LLM 输出空串会被字典校验拒)
- **nan / inf**:不允许(LLM 数字字段被校验拒,见 SC-002)
- **tab / 控制字符**:`messages[].content` 不允许
- **超出字典值**:不允许(字典校验失败 → failures)

---

## 失败样本 schema

```json
{
  "item_id": "item-456",
  "raw_response": "...LLM 原始输出...",
  "error": "JSONDecodeError",
  "error_detail": "Expecting value: line 1 column 1 (char 0)",
  "occurred_at": "2026-06-14T10:00:00Z"
}
```

| `error` 候选 | 含义 |
|--------------|------|
| `JSONDecodeError` | LLM 返回非 JSON |
| `MissingField` | 缺 `messages` / `params` / `intent` |
| `DictValidation` | `params` 字段值不在 7 维字典候选值集合内 |
| `Timeout` | LLM 调用超时(>15s) |
| `Other` | 其他异常 |

---

## 兼容性约定

- 训练管道读取时**先校验 `_format_version`**;不匹配则报警并按字段名 fallback(忽略未知字段,缺失字段用 null)
- 新增字段:`_format_version` 必须升级到 `v2`,旧版本样本仍可读
- 删除字段:需 1 个版本过渡期(`v1` 标 deprecated,`v2` 才删)

---

## 校验示例(jq)

```bash
# 1. 每行可解析
jq -c . training_data_v1.jsonl | head -3

# 2. 7 维 params 字段顺序
jq -c '.params | keys' training_data_v1.jsonl | head -3
# → ["taste","occasion","ingredient","cuisine_region","target_audience","emotion_value","party_size"]

# 3. 字典校验:所有 values 都在字典内
jq -r '.params | to_entries[] | select(.value != null) | "\(.key) \(.value.values | tostring)"' training_data_v1.jsonl | sort -u

# 4. 负样本比例
jq -s 'map(select(.negative == true)) | length / length' training_data_v1.jsonl
# → 0.1(±0.02)
```

---

## 示例:LP Agent 训练管道读取

```python
import json
from pathlib import Path

samples = []
for line in Path("training_data_v1.jsonl").read_text().splitlines():
    if not line.strip():
        continue
    sample = json.loads(line)
    assert sample["_format_version"] == "training_data_v1", f"Unknown version: {sample}"
    samples.append(sample)

# samples 是 list[dict],直接喂给 HuggingFace datasets / PyTorch DataLoader
```
