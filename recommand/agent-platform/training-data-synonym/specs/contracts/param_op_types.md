# Contract: Param `op` 类型 (param_op_types)

**Version**: `v1` | **Date**: 2026-06-14
**Spec**: [../spec.md §6.3](../spec.md)
**Companion**: [training_data_format_v1.md](./training_data_format_v1.md)

---

## 概述

`params` 字段中每个非 null 值都是 `ParamSpec` 结构:`{op, values}`。
`op` 决定 `values` 的类型和匹配语义,LP Agent 提参模型运行时按 `op` 做参数过滤。

---

## 7 个 `op` 总览

| op | 适用维度 | values 类型 | 匹配语义 | 本批实现 |
|----|----------|------------|----------|----------|
| `eq` | `party_size` | string(单值) | 严格等于 | ✅ |
| `contains` | `taste` / `ingredient` / `cuisine_region` | array<string> | 候选值集合,任一匹配 | ✅ |
| `in` | `occasion` / `target_audience` / `emotion_value` | array<string> | 任一匹配 | ✅ |
| `not_in` | `occasion` / `target_audience` / `emotion_value` | array<string> | 全不匹配 | ✅ |
| `gt` | (预留) | number | 大于 | ⛔ 接口预留 |
| `lt` | (预留) | number | 小于 | ⛔ 接口预留 |
| `between` | (预留) | [min, max] | 区间 | ⛔ 接口预留 |

> 本 spec 实现前 4 个(`eq` / `contains` / `in` / `not_in`),后 3 个(`gt` / `lt` / `between`)留接口不实现,
> 字典校验逻辑直接拒绝带这 3 个 op 的样本(避免污染训练集)。

---

## 各 op 详细定义

### `eq`(equal)

- **适用维度**:`party_size`(单值字段)
- **values 类型**:`string`(1 个候选值,字典内)
- **匹配语义**:`item.party_size == values`
- **示例**:
  ```json
  "party_size": {"op": "eq", "values": "2"}
  ```
- **错误情形**:
  - `values` 是 array(单值字段不应有 array) → `DictValidation`
  - `values` 不在字典 5 桶(`1` / `2` / `3-4` / `5-8` / `9+`) → `DictValidation`

### `contains`

- **适用维度**:`taste` / `ingredient` / `cuisine_region`(多值字段)
- **values 类型**:`array<string>`(1~N 个候选值)
- **匹配语义**:`values ⊆ item.<dim>`(item 包含 values 中所有值)
- **示例**:
  ```json
  "taste": {"op": "contains", "values": ["辣", "麻"]}
  ```
- **错误情形**:
  - `values` 不是 array → `DictValidation`
  - `values` 任一项不在字典候选值集合内 → `DictValidation`

### `in`

- **适用维度**:`occasion` / `target_audience` / `emotion_value`(枚举类)
- **values 类型**:`array<string>`(1~N 个候选值)
- **匹配语义**:`item.<dim> ∩ values ≠ ∅`(item 与 values 至少 1 个交集)
- **示例**:
  ```json
  "occasion": {"op": "in", "values": ["午餐", "晚餐"]}
  ```
- **错误情形**:同 `contains`

### `not_in`

- **适用维度**:同 `in`
- **values 类型**:同 `in`
- **匹配语义**:`item.<dim> ∩ values = ∅`(item 与 values 完全无交集,常用于"不要 X")
- **示例**:
  ```json
  "occasion": {"op": "not_in", "values": ["夜宵"]}
  ```
- **错误情形**:同 `contains`

### `gt` / `lt` / `between`(预留,本批不实现)

- 适用维度:暂未指定(可能用于 `avg_prc` / `distance` 等数值字段,US5 扩展)
- values 类型:`gt` / `lt` → number,`between` → `[min, max]`
- 本批行为:LLM 输出带这 3 个 op → `DictValidation` 拒收,样本进 `training_data_failures.jsonl`

---

## 字典校验规则(SC-002)

`validate_params(params, dictionary) -> (ok, errors)` 的判定步骤:

1. **字段名白名单**:`params` 只能有 7 个固定键(`taste` / `occasion` / `ingredient` / `cuisine_region` / `target_audience` / `emotion_value` / `party_size`),多出 → error(`"unexpected field: <name>"`)
2. **字段缺失**:7 维有缺 → null 补齐(不算 error)
3. **op 白名单**:每个非 null 值的 `op` 必须在 `OP_TYPES` 中,且属于本批实现的 4 个(`eq` / `contains` / `in` / `not_in`),否则 → error
4. **op 适用维度**:`op` 必须匹配字段名(如 `eq` 只能用在 `party_size`),否则 → error
5. **values 类型**:`values` 类型必须跟 `op` 对应(`eq` → string,`contains` / `in` / `not_in` → array<string>),否则 → error
6. **values 字典校验**:`values` 中每项必须在对应维度的字典候选值集合内(`configs/tag_dictionary.yaml`),否则 → error
7. **空数组**:`contains` / `in` / `not_in` 的 `values = []` → error(`"empty values array"`)

---

## 字典候选值(沿用 001 `configs/tag_dictionary.yaml`)

| 维度 | 候选值 |
|------|--------|
| `taste` | 辣 / 甜 / 咸 / 酸 / 苦 / 鲜 / 清淡 / 奶香 / 麻 |
| `occasion` | 早餐 / 午餐 / 晚餐 / 夜宵 / 下午茶 / 聚会 / 一人食 / 商务 |
| `ingredient` | 牛 / 鸡 / 鱼 / 虾 / 蔬菜 / 米 / 面 / 奶 / 蛋 / 豆制品 |
| `cuisine_region` | 川 / 粤 / 鲁 / 苏 / 浙 / 闽 / 湘 / 徽 / 日 / 韩 / 泰 / 西式 / 中式 / 东南亚 |
| `target_audience` | 学生 / 白领 / 家庭 / 情侣 / 健身 / 老人 / 儿童 |
| `emotion_value` | 解压 / 治愈 / 活力 / 暖心 / 清爽 / 提神 / 怀旧 |
| `party_size` | `1` / `2` / `3-4` / `5-8` / `9+` |

字典变更时:运营直接改 yaml,训练数据生成时**热加载**,不需要改 prompt / 改代码。

---

## 示例:正 / 反样本

### 正样本(7 维中 2 维被指定)

```json
{
  "intent": "search_item",
  "params": {
    "taste":          {"op": "contains", "values": ["辣", "麻"]},
    "occasion":       {"op": "in",       "values": ["午餐", "晚餐"]},
    "ingredient":     null,
    "cuisine_region": {"op": "contains", "values": ["川"]},
    "target_audience":null,
    "emotion_value":  null,
    "party_size":     {"op": "eq",       "values": "3-4"}
  },
  "order_by": "rating",
  "negative": false
}
```

### 负样本(用户拒绝)

```json
{
  "intent": "search_item",
  "params": {
    "taste":          {"op": "not_in",   "values": ["辣"]},
    "occasion":       null,
    "ingredient":     null,
    "cuisine_region": null,
    "target_audience":null,
    "emotion_value":  null,
    "party_size":     null
  },
  "order_by": null,
  "negative": true
}
```

对应对话可能是:用户「我想要个不辣的川菜」→ 助手推荐 → 用户「算了太辣了不看了」

### 校验失败样本(字典外值)

```json
{
  "intent": "search_item",
  "params": {
    "taste":          {"op": "contains", "values": ["超级辣"]},  // ⛔ 字典外
    "occasion":       null,
    ...
  }
}
```

→ `DictValidation: taste.values[0] '超级辣' 不在字典候选值集合内`,样本进 `training_data_failures.jsonl`。

---

## LP Agent 提参模型运行时使用

```python
def filter_items(items: List[Item], params: Dict[str, ParamSpec]) -> List[Item]:
    """LP Agent 提参模型按 op 过滤候选商品"""
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
        # gt/lt/between: 留接口
    return result
```
