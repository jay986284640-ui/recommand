# Data Model: 训练数据生成

**Version**: `v1` | **Date**: 2026-06-14
**Spec**: [./spec.md](./spec.md)
**Companion**: [./contracts/training_data_format_v1.md](./contracts/training_data_format_v1.md), [./contracts/param_op_types.md](./contracts/param_op_types.md)

---

## 概述

训练数据生成子包(`feature_extraction/training_data/`)涉及 **4 个核心实体 + 1 个状态实体 + 1 个失败实体 + 3 个数据准备实体(Cleaning / Distribution / Split)**。
本数据模型定义**Python dataclass** 形式(Spark 不直接用,本子包用 pandas 读 `item_features_ai.jsonl` 后在 driver 端做 LLM 调用)。

---

## 实体 1:`TrainingSample`(主输出)

| 字段 | Python 类型 | JSON 类型 | 必填 | 默认值 | 来源 / 校验 |
|------|------------|-----------|------|--------|------------|
| `item_id` | `str` | string | ✅ | — | 取自 `item_features_ai.jsonl` |
| `intent` | `str` | string | ✅ | — | 候选:`search_item` / `use_coupon` / `pay` / `view_order` / `browse` |
| `messages` | `List[MessageTurn]` | array | ✅ | — | 长度 1~4,首条 `role=user` |
| `params` | `Dict[str, ParamSpec \| None]` | object | ✅ | — | 7 个固定 key,顺序固定,缺失 → None |
| `order_by` | `Optional[str]` | string\|null | ✅ | `None` | 候选:`distance` / `price` / `rating` / `time` / `None` |
| `negative` | `bool` | boolean | ✅ | `False` | `True` = 负样本 |
| `generated_at` | `datetime` | string (ISO8601) | ✅ | now(UTC) | LLM 调用完成时间 |
| `llm_model` | `str` | string | ✅ | — | 模型 ID |
| `_format_version` | `str` | string | ✅ | `"training_data_v1"` | 常量,写盘时强制写入 |

**dataclass 草图**:
```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime

@dataclass
class TrainingSample:
    item_id: str
    intent: str
    messages: List["MessageTurn"]
    params: Dict[str, Optional["ParamSpec"]]
    order_by: Optional[str] = None
    negative: bool = False
    generated_at: datetime = field(default_factory=lambda: datetime.utcnow())
    llm_model: str = ""
    _format_version: str = "training_data_v1"
```

---

## 实体 2:`MessageTurn`(`messages` 元素)

| 字段 | Python 类型 | JSON 类型 | 必填 | 候选 |
|------|------------|-----------|------|------|
| `role` | `str` | string | ✅ | `user` / `assistant` / `system` |
| `content` | `str` | string | ✅ | 自然语言,UTF-8,不含 tab / 控制字符 |

**dataclass 草图**:
```python
@dataclass
class MessageTurn:
    role: str  # "user" | "assistant" | "system"
    content: str
```

**约束**:
- `messages[0].role == "user"`(首条必为用户)
- `messages` 长度 1~4(由 `TrainingDataConfig.max_message_turns` 控制,默认 3)
- `content` 长度建议 5~200 字(避免空话和长段落)

---

## 实体 3:`ParamSpec`(`params` 值)

| 字段 | Python 类型 | JSON 类型 | 必填 | 约束 |
|------|------------|-----------|------|------|
| `op` | `str` | string | ✅ | 候选:`eq` / `contains` / `in` / `not_in`(本批),`gt` / `lt` / `between`(预留,本批拒) |
| `values` | `Union[str, List[str]]` | string\|array | ✅(非 None 时) | 类型跟 `op` 对应,详见 `param_op_types.md` |

**dataclass 草图**:
```python
from typing import Union

@dataclass
class ParamSpec:
    op: str
    values: Union[str, List[str]]

    def to_dict(self) -> dict:
        return {"op": self.op, "values": self.values}
```

**op → values 类型映射**:

| op | values 类型 | 示例 |
|----|------------|------|
| `eq` | `str` | `"2"` |
| `contains` | `List[str]` | `["辣", "麻"]` |
| `in` | `List[str]` | `["午餐", "晚餐"]` |
| `not_in` | `List[str]` | `["夜宵"]` |
| `gt` / `lt` | (预留)`float` | — |
| `between` | (预留)`[float, float]` | — |

**字典校验**(由 `param_schema.validate_params()` 执行,SC-002):
- `params` 字段名白名单(7 维固定)
- `op` 白名单(本批 4 个)+ `op` 适用维度匹配
- `values` 类型跟 `op` 对应
- `values` 中每项在字典候选值集合内
- 7 维缺失字段 → `None` 补齐(不算 error)

---

## 实体 4:`NegativeSample`(负样本包装)

`NegativeSample` = `TrainingSample` + `type: str` 字段,但实际**不**单独存盘,而是在 `TrainingSample.negative=True` 时,在生成时记录 `type`(拒绝 / 转移 / 不满足)。

| 字段 | 类型 | 必填 | 候选 |
|------|------|------|------|
| `type` | `str` | ✅ | `reject` / `pivot` / `unsatisfiable` |
| `sample` | `TrainingSample` | ✅ | 完整的样本 |

**生成策略**(plan.md D-005,spec.md §FR-006):
- 比例 = `TrainingDataConfig.negative_ratio`(默认 0.1)
- 3 类权重:reject 0.4 / pivot 0.4 / unsatisfiable 0.2
- 注入位置:`prompt.py` 的 `negative_instruction` 字段
- 实现:`negative_sampler.sample_negative_type(seed=None) -> str`

**3 类语义**:

| type | 语义 | 示例对话 |
|------|------|----------|
| `reject` | 用户表达"不要"某条件 | 用户「我想要不辣的」 → params: `{taste: {op: "not_in", values: ["辣"]}}` |
| `pivot` | 用户转移意图 | 用户「算了不看咖啡了,看奶茶」 → params: `{ingredient: {op: "contains", values: ["奶"]}}`(覆盖) |
| `unsatisfiable` | 无 item 满足 query | 用户「附近没这种店」 → 助手「暂时没找到,要不看看...」 |

---

## 实体 5:`TrainingDataState`(增量状态)

| 字段 | Python 类型 | 必填 | 说明 |
|------|------------|------|------|
| `item_id` | `str` | ✅ | 商品 ID |
| `ai_tags_md5` | `str` | ✅ | 7 维 AI 标签的 md5(增量比对用) |
| `sample_count` | `int` | ✅ | 已生成样本数(默认 8) |
| `generated_at` | `datetime` | ✅ | 上次生成时间 |
| `llm_model` | `str` | ✅ | 用的模型版本 |

**存储**:`./training_data_state.parquet`(Spark 可读,driver 端用 pandas 读)

**增量比对规则**(由 `state.diff_incremental()` 执行,FR-004):
- 全量模式:不读 state,所有 item 都跑
- 增量模式:
  - state 中无 `item_id` → 新增
  - state 中有 `item_id` 但 `ai_tags_md5` 变了 → 修改
  - state 中有 `item_id` 且 `ai_tags_md5` 没变 → 跳过

**md5 计算粒度**:`md5(json.dumps(ai_tags, sort_keys=True, ensure_ascii=False))`
- 字段顺序不影响 md5(`sort_keys=True`)
- 字典值变化 / 多标签变化都会触发重算

---

## 实体 6:`TrainingDataFailure`(失败日志)

| 字段 | Python 类型 | JSON 类型 | 必填 | 候选 |
|------|------------|-----------|------|------|
| `item_id` | `str` | string | ✅ | 商品 ID |
| `raw_response` | `str` | string | ✅ | LLM 原始输出(便于排查) |
| `error` | `str` | string | ✅ | `JSONDecodeError` / `MissingField` / `DictValidation` / `Timeout` / `Other` |
| `error_detail` | `str` | string | ❌ | 详细错误信息(可空) |
| `occurred_at` | `datetime` | string(ISO8601) | ✅ | 失败时间 |

**存储**:`./training_data_failures.jsonl`(append 模式)

**触发场景**(FR-003):
- LLM 返回非 JSON → `JSONDecodeError`
- LLM 返回 JSON 但缺 `messages` / `params` / `intent` → `MissingField`
- `params` 字典校验失败 → `DictValidation`
- LLM 调用 >15s → `Timeout`
- 其他未捕获异常 → `Other`

---

## 实体 7:`CleaningFilter`(FR-007 清洗规则)

7 类清洗规则的数据结构,用于声明式配置 + 校验结果记录。

| 字段 | Python 类型 | JSON 类型 | 必填 | 默认值 | 说明 |
|------|------------|-----------|------|--------|------|
| `rule_id` | `str` | string | ✅ | — | 1~7 对应 spec.md FR-007 表 |
| `name` | `str` | string | ✅ | — | `text_hash_dedup` / `min_message_length` / `template_repeat` / `params_all_null` / `control_char` / `item_id_not_in_dict` / `turn_count` |
| `enabled` | `bool` | boolean | ✅ | `True` | always on 6 个,`min_message_length` 可配 |
| `threshold` | `Optional[float]` | number\|null | ❌ | `None` | 规则 2:min_message_length=10 / 规则 3:repeat threshold 0.3 / 规则 3:target 0.2 |
| `dropped_count` | `int` | int | ✅ | `0` | 实际被删样本数(运行期统计) |
| `dropped_examples` | `List[str]` | array | ❌ | `[]` | 被删前 3 条样本 ID(排查用,不存明细) |

**7 类规则清单**:

| rule_id | name | 默认 enabled | threshold | 触发动作 |
|---------|------|------|------|------|
| 1 | `text_hash_dedup` | True | None | md5(messages+params) 相同 → 留 1 |
| 2 | `min_message_length` | True | 10 | 任意 content < 10 字 → 删 |
| 3 | `template_repeat` | True | 0.3 → 0.2 | 首句 n-gram 占比 > 30% → 降到 ≤ 20% |
| 4 | `params_all_null` | True | None | 7 维全 null → 删 |
| 5 | `control_char` | True | None | `\n\n\n+` / tab / 控制字符 → 删 |
| 6 | `item_id_not_in_dict` | True | None | ai_tags 字段名不在字典 → 删 |
| 7 | `turn_count` | True | max_message_turns | 长度 < 1 或 > N → 删 |

**输出**:
- `training_data_cleaned.jsonl`(留存量 ≥ 85%,SC-008)
- `cleaning_failures.jsonl`(被删样本的 item_id + 删除原因)

**dataclass 草图**:
```python
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class CleaningFilter:
    rule_id: int
    name: str
    enabled: bool = True
    threshold: Optional[float] = None
    dropped_count: int = 0
    dropped_examples: List[str] = field(default_factory=list)
```

---

## 实体 8:`DistributionStats`(FR-008 分布统计)

8 个分布指标 + 历史趋势,写到 `distribution_report.json`。

| 字段 | Python 类型 | JSON 类型 | 必填 | 说明 |
|------|------------|-----------|------|------|
| `intent_distribution` | `Dict[str, float]` | object | ✅ | 5 类 intent 比例,`{search_item: 0.6, ...}` |
| `param_non_null_ratio` | `Dict[str, float]` | object | ✅ | 7 维非 null 比例,`{taste: 0.32, ...}` |
| `op_distribution` | `Dict[str, float]` | object | ✅ | 4 个 op 比例,`{contains: 0.6, ...}` |
| `negative_ratio` | `float` | number | ✅ | 负样本比例 |
| `turn_distribution` | `Dict[int, float]` | object | ✅ | 对话轮次分布 `{1: 0.1, 2: 0.3, ...}` |
| `message_avg_length` | `float` | number | ✅ | 消息平均长度(字) |
| `dict_value_coverage` | `Dict[str, int]` | object | ✅ | 字典值覆盖次数 `{taste.辣: 234, ...}` |
| `params_combo_diversity` | `int` | int | ✅ | 1000 条样本中唯一 params 组合数 |
| `warnings` | `List[str]` | array | ✅ | 不达标项列表(SC-009:≤ 2 个) |
| `generated_at` | `datetime` | string(ISO8601) | ✅ | 报告生成时间 |

**8 指标目标值**(对应 spec.md FR-008 表):

| 指标 | 目标 | 不达标动作 |
|------|------|------------|
| `intent_distribution` | 每类 ≥ 0.03 | 报警 + 触发过采样 |
| `param_non_null_ratio` | 每维度 ≥ 0.05 | 报警 + 触发过采样 |
| `op_distribution` | `not_in` ≥ 0.03 | 报警 + 触发过采样 |
| `negative_ratio` | `negative_ratio` ±0.02 | 报警 + 重新分配 |
| `turn_distribution` | 1/2/3/4 轮 = 10/30/40/20 % ±5% | 报警 |
| `message_avg_length` | 20~80 字 | 报警 |
| `dict_value_coverage` | 每个候选值 ≥ 5 样本 | 报警 |
| `params_combo_diversity` | 1000 样本 ≥ 200 唯一组合 | 报警 |

**输出**:`./distribution_report.json`

**dataclass 草图**:
```python
@dataclass
class DistributionStats:
    intent_distribution: Dict[str, float]
    param_non_null_ratio: Dict[str, float]
    op_distribution: Dict[str, float]
    negative_ratio: float
    turn_distribution: Dict[int, float]
    message_avg_length: float
    dict_value_coverage: Dict[str, int]
    params_combo_diversity: int
    warnings: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.utcnow())
```

---

## 实体 9:`DataSplit`(FR-009 数据集划分)

按 `item_id` hash 划分 80/10/10,3 个集合 + 泄露校验。

| 字段 | Python 类型 | JSON 类型 | 必填 | 说明 |
|------|------------|-----------|------|------|
| `train` | `List[TrainingSample]` | array(TrainingSample) | ✅ | 训练集(80%) |
| `val` | `List[TrainingSample]` | array | ✅ | 验证集(10%) |
| `test` | `List[TrainingSample]` | array | ✅ | 测试集(10%) |
| `source` | `Literal["synthetic", "real", "mixed"]` | string | ✅ | 样本来源 |
| `split_key` | `Callable[[str], str]` | (运行时函数) | — | `hashlib.md5(item_id).hexdigest() % 100` 映射到 `train` / `val` / `test` |
| `leak_check_passed` | `bool` | boolean | ✅ | SC-010:同 item 不跨集合 |
| `real_data_ratios` | `Dict[str, float]` | object | ✅ | 3 个集合中真实数据占比(SC-011) |

**划分算法**:
```python
import hashlib
from typing import Literal

def split_key(item_id: str) -> Literal["train", "val", "test"]:
    h = int(hashlib.md5(item_id.encode()).hexdigest(), 16) % 100
    if h < 80:   return "train"   # 0~79
    elif h < 90: return "val"     # 80~89
    else:        return "test"    # 90~99
```

**额外要求**:
- val / test 真实数据优先(SC-011):如 `source == "real"` 优先分到 val/test
- 划分后必须跑 `validate_no_leak()`(同 item 不跨集合)

**输出**:
- `train.jsonl` / `val.jsonl` / `test.jsonl`

**dataclass 草图**:
```python
from typing import List, Literal, Callable

@dataclass
class DataSplit:
    train: List[TrainingSample]
    val: List[TrainingSample]
    test: List[TrainingSample]
    source: Literal["synthetic", "real", "mixed"]
    leak_check_passed: bool = False
    real_data_ratios: Dict[str, float] = field(default_factory=dict)
```

---

## 实体关系图

```
                    ┌─────────────────────┐
                    │ item_features_ai    │  (001 增强产物,只读)
                    │ .jsonl              │
                    └──────────┬──────────┘
                               │ 加载
                               ↓
                    ┌─────────────────────┐
                    │ TrainingDataPipeline│
                    │ .run()              │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ↓                ↓                ↓
    ┌──────────────────┐  ┌──────────────┐  ┌──────────────────┐
    │ TrainingDataState│  │  LLMClient   │  │ ParamSpec        │
    │ (parquet)        │  │  (001 复用)  │  │ .validate_params │
    └──────────────────┘  └──────┬───────┘  └────────┬─────────┘
                                │                   │
                                ↓                   ↓
                    ┌─────────────────────┐  ┌──────────────┐
                    │ TrainingSample      │  │ 字典校验     │
                    │ (主输出 jsonl)      │←─│ (7 维字典)   │
                    └──────────┬──────────┘  └──────────────┘
                               │
                ┌──────────────┴──────────────┐
                ↓                             ↓
    ┌──────────────────────┐      ┌────────────────────────┐
    │ training_data_v1     │      │ training_data_failures │
    │ .jsonl               │      │ .jsonl                 │
    │ (400 行/50 items)    │      │ (失败样本)             │
    └──────────┬───────────┘      └────────────────────────┘
               │
       ┌───────┴────────────────────┐
       ↓                            ↓
┌──────────────────┐      ┌──────────────────┐
│ training_data_   │      │ cleaning_        │
│ cleaned.jsonl    │      │ failures.jsonl   │
│ (FR-007 清洗)    │      │ (被删原因)       │
└────────┬─────────┘      └──────────────────┘
         │
         ↓
┌──────────────────┐      ┌──────────────────┐
│ distribution_    │      │ balancing_       │
│ report.json      │      │ failures.jsonl   │
│ (FR-008 8 指标)  │      │ (FR-008 平衡)    │
└────────┬─────────┘      └──────────────────┘
         │
         ↓ 自动过采样
┌──────────────────┐
│ balanced         │
│ (FR-008 平衡后)  │
└────────┬─────────┘
         │
         ↓ 按 item_id hash 划分
    ┌────┴────┬────────┐
    ↓         ↓        ↓
┌────────┐ ┌──────┐ ┌───────┐
│train.  │ │val.  │ │test.  │
│jsonl   │ │jsonl │ │jsonl  │
│(80%)   │ │(10%) │ │(10%)  │
└────────┘ └──────┘ └───────┘
         ↑
   SC-010 泄露校验
   SC-011 真实数据 ≥ 50%
```

---

## 数据流

```
1. 读取 ./item_features_ai.jsonl                    # 001 增强产物
   ↓
2. 读取 ./training_data_state.parquet              # 增量模式
   ↓
3. state.diff_incremental(items)                   # 分类:新增 / 修改 / 跳过
   ↓
4. for each (item_id, ai_tags):
     a. for i in 1..count_per_item:
          - dialogue_template = diversity.pick_template()
          - negative_type = negative_sampler.sample_negative_type()  # 按 negative_ratio 触发
          - prompt = prompt.render(ai_tags, dictionary, dialogue_template, negative_type)
          - response = llm_client.generate_training_sample(prompt)
          - sample = parse_response(response)
          - ok, errors = param_schema.validate_params(sample.params, dictionary)
          - if ok: samples.append(sample)
                  else: failures.append({item_id, raw, error: "DictValidation"})
     ↓
5. writer.write_training_data_jsonl(samples, output_path)
6. state.persist(new_state)
7. writer.write_failures_jsonl(failures, failures_path)  # append
   ↓
8. cleaner.apply(raw_samples) → (cleaned, dropped)    # FR-007:7 类规则
   ↓
9. distribution.analyze(cleaned) → report.json        # FR-008:8 指标
   ↓
10. balancer.balance(cleaned, report) → balanced      # FR-008:自动过采样
    ↓
11. splitter.split(balanced) → (train, val, test)     # FR-009:80/10/10
    ↓
12. splitter.validate_no_leak(train, val, test)        # SC-010
13. writer.write_3_split_jsonl(train, val, test)       # 落 train.jsonl/val.jsonl/test.jsonl
```

---

## 不在本数据模型范围

- **LP Agent envelope 协议**:由 LP Agent 运行时负责,本子包不涉及
- **训练管道消费格式**:HuggingFace datasets / PyTorch DataLoader 自行处理,本子包只保证 jsonl 合法
- **001 增强产物的内部结构**:`item_features_ai.jsonl` 字段定义详见 [001 spec §6.1](../001-data-pipeline-enhancement/spec.md)
