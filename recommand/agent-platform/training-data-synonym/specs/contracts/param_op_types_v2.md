# Contract: Param `op` 类型 v2 (`param_op_types_v2`)

**Version**: `v2` | **Date**: 2026-06-22
**Spec**: [../spec.md](../spec.md) (v2.4)
**Companion**: [item_tags_v2.md](./item_tags_v2.md) · [sft_corpus_v2.md](./sft_corpus_v2.md)
**Supersedes**: `param_op_types.md`(v1,7 维味标签;**不兼容**)

---

## 概述

`params` 字段中每个非 null 值都是 `ParamSpec` 结构:`{op, values}`。

本批(s2 8 维)实现前 4 个 op(`eq / in / contains / not_in`),后 3 个(`gt / lt / between`)留接口,字典校验**拒收**(不污染训练集)。

---

## 4 个本批实现 op ↔ 8 维映射

| dim | 允许 op | values 类型 | 字典候选值(节选) |
|-----|--------|------------|------------------|
| `category` | `in` | `array<string>` | 咖啡 / 快餐 / 奶茶 / 烘焙 / 便利店 / 中餐 / 西餐 / 日料 / 火锅 / 烧烤 / 甜品 / 水果 |
| `consumable_type` | `eq` | `string`(单值) | `food / drink / mixed / none` |
| `merchant` | `in` | `array<string>` | 60+ 品牌(星巴克 / 瑞幸 / 肯德基 / 麦当劳 / 喜茶 / 奈雪 ...)+ `brand_dictionary.yaml` 扩量 |
| `avg_prc` | `in` | `array<string>`(桶 ID) | `"0-30" / "30-50" / "50-100" / "100-200" / "200+"` |
| `distance` | `in` / `not_in` | `array<string>`(桶 ID) | `"0-500" / "500-1000" / "1000-3000" / "3000+"` |
| `age` | `in` | `array<string>` | `"18-25" / "25-35" / "35-45" / "45-55" / "55+"` |
| `occasion` | `in` | `array<string>` | 早餐 / 午餐 / 下午茶 / 晚餐 / 夜宵 / 聚会 / 工作日 / 周末 / 节日 / 自取 / 外卖 / 堂食 |
| `taste` | `contains` / `not_in` | `array<string>` | 甜 / 咸 / 辣 / 麻 / 酸 / 苦 / 鲜 / 清淡 / 浓郁 / 冰 / 热 / 温 |

权威源:`configs/dim_dictionary.yaml` + `configs/brand_dictionary.yaml` + `configs/consumable_type_map.yaml`(运行时合并)。

---

## 4 个 op 详细定义

### `eq`(equal)

- **适用维度**:`consumable_type`(单值字段)
- **values 类型**:`string`(1 个候选值)
- **匹配语义**:`item.consumable_type == values`
- **示例**:
  ```json
  "consumable_type": {"op": "eq", "values": "drink"}
  ```
- **错误情形**:
  - `values` 是 array → `DictValidation`
  - `values` ∉ {food, drink, mixed, none} → `DictValidation`

### `in`

- **适用维度**:`category / merchant / avg_prc / distance / age / occasion`
- **values 类型**:`array<string>`(1~N 个候选值)
- **匹配语义**:`item.<dim> ∩ values ≠ ∅`(item 与 values 至少 1 个交集)
- **示例**:
  ```json
  "distance": {"op": "in", "values": ["0-500"]}
  "category": {"op": "in", "values": ["咖啡", "奶茶"]}
  ```
- **错误情形**:values 不是 array / 任一项不在字典候选集内 / 空数组 → `DictValidation`

### `contains`

- **适用维度**:`taste`(多值字段)
- **values 类型**:`array<string>`(1~N 个候选值)
- **匹配语义**:`values ⊆ item.taste`(item 包含 values 中所有值)
- **示例**:
  ```json
  "taste": {"op": "contains", "values": ["辣", "麻"]}
  ```
- **错误情形**:同 `in`

### `not_in`

- **适用维度**:`distance / occasion / target_audience / emotion_value / taste`(本批仅 `distance / taste`)
- **values 类型**:`array<string>`(1~N 个候选值)
- **匹配语义**:`item.<dim> ∩ values = ∅`(item 与 values 完全无交集,常用于"不要 X")
- **示例**:
  ```json
  "taste": {"op": "not_in", "values": ["甜"]}
  ```
- **错误情形**:同 `in`

### `gt` / `lt` / `between`(预留,本批不实现)

- 适用维度:暂未指定(可能用于 `avg_prc / distance` 数值化时启用,US5 扩展)。
- values 类型:`gt / lt → number`,`between → [min, max]`。
- 本批行为:LLM 输出带这 3 个 op → `DictValidation` 拒收,样本入 `sft_failures.jsonl`。

---

## 字典校验流程(`validate_params`)

```python
def validate_params(params: Dict[str, Any], dictionary: Dict) -> Tuple[bool, List[str]]:
    errors = []

    # 1. 字段名白名单(8 维)
    allowed = {"category", "consumable_type", "merchant", "avg_prc",
               "distance", "age", "occasion", "taste"}
    for k in params.keys():
        if k not in allowed:
            errors.append(f"unexpected field: {k}")

    # 2. 缺失字段 → null 补齐(非 error)
    for k in allowed:
        params.setdefault(k, None)

    # 3. op 白名单
    IMPLEMENTED_OPS = {"eq", "in", "contains", "not_in"}
    for dim, spec in params.items():
        if spec is None:
            continue
        if spec["op"] not in IMPLEMENTED_OPS:
            errors.append(f"{dim}.op '{spec['op']}' not in implemented set")

    # 4. op 适用维度(本批)
    op_allowed = {
        "category":        {"in"},
        "consumable_type": {"eq"},
        "merchant":        {"in"},
        "avg_prc":         {"in"},
        "distance":        {"in", "not_in"},
        "age":             {"in"},
        "occasion":        {"in"},
        "taste":           {"contains", "not_in"},
    }
    for dim, spec in params.items():
        if spec is None:
            continue
        if spec["op"] not in op_allowed[dim]:
            errors.append(f"{dim}.op '{spec['op']}' not allowed for this dim")

    # 5. values 类型跟 op 对应
    for dim, spec in params.items():
        if spec is None:
            continue
        op = spec["op"]
        v = spec["values"]
        if op == "eq":
            if not isinstance(v, str):
                errors.append(f"{dim}.values must be str for op=eq")
        elif op in {"in", "contains", "not_in"}:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                errors.append(f"{dim}.values must be array<string> for op={op}")
            elif len(v) == 0:
                errors.append(f"{dim}.values empty array")

    # 6. values 字典校验
    for dim, spec in params.items():
        if spec is None:
            continue
        allowed_values = dictionary[dim]["values"]
        op = spec["op"]
        v = spec["values"]
        if op == "eq":
            if v not in allowed_values:
                errors.append(f"{dim}.values '{v}' not in dictionary")
        else:
            for item in v:
                if item not in allowed_values:
                    errors.append(f"{dim}.values[{item}] not in dictionary")

    return (len(errors) == 0, errors)
```

**调用时机**:`sft_failures.jsonl` 写之前必跑;任一 error → `error="DictValidation"`,`error_detail` 含所有 error 字符串。

---

## 正 / 负样本示例

### 正样本(8 维中 5 维被指定)

```json
{
  "intent": "search_item",
  "params": {
    "category":         {"op": "in", "values": ["咖啡"]},
    "consumable_type":  {"op": "eq", "values": "drink"},
    "merchant":         {"op": "in", "values": ["星巴克", "瑞幸"]},
    "avg_prc":          null,
    "distance":         {"op": "in", "values": ["0-500"]},
    "age":              null,
    "occasion":         {"op": "in", "values": ["下午茶"]},
    "taste":            null
  },
  "order_by": "distance",
  "negative": false
}
```

### 负样本(`reject`,distance 反向)

```json
{
  "intent": "search_item",
  "params": {
    "category":         null,
    "consumable_type":  {"op": "eq", "values": "food"},
    "merchant":         null,
    "avg_prc":          null,
    "distance":         {"op": "not_in", "values": ["3000+"]},
    "age":              null,
    "occasion":         null,
    "taste":            {"op": "not_in", "values": ["辣"]}
  },
  "order_by": null,
  "negative": true,
  "negative_type": "reject"
}
```

### 校验失败样本(字典外值)

```json
{
  "params": {
    "taste": {"op": "contains", "values": ["超级辣"]}    // ⛔ 字典外
  }
}
```

→ `DictValidation: taste.values[0] '超级辣' 不在字典候选值集合内`,样本入 `sft_failures.jsonl`。

---

## LP Agent 提参模型运行时消费

```python
def filter_items(items: List[Item], params: Dict[str, ParamSpec]) -> List[Item]:
    """LP Agent 提参模型按 op 过滤候选商品(运行时侧;本工程只产样本,不在此运行时执行)"""
    result = items
    for dim, spec in params.items():
        if spec is None:
            continue
        op = spec["op"]
        values = spec["values"]
        if op == "eq":
            result = [it for it in result if getattr(it, dim) == values]
        elif op == "contains":
            result = [it for it in result if all(v in getattr(it, dim, []) for v in values)]
        elif op == "in":
            result = [it for it in result if set(getattr(it, dim, [])) & set(values)]
        elif op == "not_in":
            result = [it for it in result if not (set(getattr(it, dim, [])) & set(values))]
        # gt/lt/between: 留接口,本批无样本携带
    return result
```

---

## v1 → v2 差异(迁移期参考)

| 维度 | v1(7 维口味) | v2(8 维商业属性) |
|------|--------------|-----------------|
| 字段集 | `taste / occasion / ingredient / cuisine_region / target_audience / emotion_value / party_size` | `category / consumable_type / merchant / avg_prc / distance / age / occasion / taste` |
| `distance` 语义 | 不存在 | 字典桶 ID(`0-500 / 500-1000 / ...`),与 lng/lat 解耦 |
| `consumable_type` 语义 | 不存在 | `food / drink / mixed / none`,op=`eq` |
| `merchant` 语义 | 不存在 | `in` op + `brand_dictionary.yaml` |
| `tag_source.distance` | 不存在 | `geo / missing`(不透传到 LLM) |
| `tag_source.consumable_type` | 不存在 | `derived / ai / missing` |

读 v1 样本的兼容方案:Stage 2 reader 在 `version == "training_data_v1"` 时,**忽略** `consumable_type`,**强制** `tag_source.distance = missing` 并把 `distance = null`;`order_by` 不变;其余字段按 v1 字典映射。