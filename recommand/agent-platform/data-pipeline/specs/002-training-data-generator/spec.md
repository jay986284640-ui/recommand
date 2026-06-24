# Spec: 训练数据生成 (Training Data Generator)

**Branch**: `002-training-data-generator` | **Date**: 2026-06-14 | **Status**: Draft
**Project**: `agent-platform/data-pipeline/`
**Related**:
- [001-promo-recommend-agent](../../../../specs/001-promo-recommend-agent/spec.md) — LP Agent(最终消费者,意图识别 + 提参模型)
- [001-data-pipeline-enhancement](../001-data-pipeline-enhancement/spec.md) — 7 维 AI 标签来源(`item_features_ai.jsonl`)

---

## 1. 概述

为 LP Agent 的 **意图识别模型** + **提参模型** 自动生成训练数据。

- **输入**:`item_features_ai.jsonl`(来自 001 增强后的 7 维 AI 标签)
- **输出**:`training_data_v1.jsonl` — 1 行 1 个训练样本,字段含 `messages`(多轮对话)+ `params`(7 维 `op` / `values`)+ `order_by` + `intent` + `item_id`
- **核心**:LLM 读 7 维标签 → 合成自然语言多轮对话 → 提取结构化 params(可作为提参模型 ground truth)

不动现有代码,只追加新模块 `feature_extraction/training_data/`。

---

## 2. 背景与目标

### 2.1 背景

LP Agent 上线需要 2 个模型在生产前大量标注对话样本:
- **意图识别模型**:从 user query 识别"想找咖啡 / 想买单 / 想用券 / 想看订单"等意图
- **提参模型**:从 user query + 历史对话 提取 `(occasion=午餐, party_size=2, taste=辣)` 等结构化参数

手工标注成本高、覆盖度低;**7 维 AI 标签**(taste/occasion/ingredient/cuisine_region/target_audience/emotion_value/party_size)已经存在,可作为"商品真实意图分布"反向合成 user query。

### 2.2 目标

- (G1) 自动化生成 **多轮对话** 训练样本,默认 8 条/商品(可配 5~10)
- (G2) 每条样本同时输出**结构化 params**(提参模型 ground truth)
- (G3) 输出 jsonl 100% 可被 LP Agent 训练管道直接消费
- (G4) 100% 字典校验,确保 params 字段值在 7 维候选值集合内

### 2.3 非目标

- 不做真实用户隐私数据生成(纯合成)
- 不替代手工标注的高质量数据,只补"长尾 + 字典覆盖度"
- 不做模型训练本身(那是 LP Agent 训练管道的事)
- 不改 LP Agent envelope 协议
- 不改 001 增强管线(`ai_enhance/`)的任何代码

---

## 3. 输入 / 输出

### 3.1 输入

| 来源 | 路径 | 用途 |
|------|------|------|
| `item_features_ai.jsonl` | 001 增强产物 | 商品 7 维 AI 标签,反向合成 query |
| `configs/tag_dictionary.yaml` | 7 维字典 | params 字典校验 |
| `configs/prompts/training_data_v1.txt` | prompt 模板 | 对话生成 + 提参 |

### 3.2 输出

| 路径 | 用途 | 来源 |
|------|------|------|
| `training_data_v1.jsonl` | LLM 原始生成的主产出 | FR-001~FR-006 |
| `training_data_failures.jsonl` | LLM 解析 / 字典校验失败的样本(排查用) | FR-003 |
| `training_data_state.parquet` | 增量模式:item_id + md5 指纹 + 已生成时间 | FR-004 |
| `training_data_cleaned.jsonl` | **清洗后**(FR-007),留存量 ≥ 85% | FR-007 |
| `cleaning_failures.jsonl` | **清洗失败样本**(被删原因,排查用) | FR-007 |
| `distribution_report.json` | **8 分布指标 + 历史趋势**(FR-008) | FR-008 |
| `balancing_failures.jsonl` | **平衡失败样本**(FR-008) | FR-008 |
| `train.jsonl` | **训练集**(80%,FR-009) | FR-009 |
| `val.jsonl` | **验证集**(10%,FR-009) | FR-009 |
| `test.jsonl` | **测试集**(10%,FR-009) | FR-009 |

---

## 4. 用户故事

### US1 — 训练数据生成(P1,核心)

> 作为 LP Agent 训练管道,我想拿到覆盖 7 维各 (5~10) 条/商品的合成对话样本,每条样本带 ground-truth params,直接喂给意图识别 + 提参模型微调。

**独立可测试**:给 50 个 `item_features_ai` 行,跑 `run_training_data.py --count=8` 后产出 400 行训练数据 jsonl,每行 `messages` 合法 + `params` 字段 100% 在字典内(SC-001, SC-002, SC-004)。

**场景**:
- 新增商品上架 → 全量跑一次,产出 N×8 条样本
- 字典新增 1 个候选值(如 taste 新增"果香") → 增量跑,只补"果香"相关 query
- LLM 报错 → 写 `training_data_failures.jsonl`,不阻塞主流程
- 用户用模糊 query("有什么好的") → 也要能生成样本(强泛化训练)
- 负样本(用户拒绝 / 转移意图)占 ~10%,训练模型识别"非匹配 query"

---

## 5. 功能性需求(FR)

### FR-001 多轮对话生成

LLM 必须输出 **结构化 JSON**(单次调用同时产出对话 + 提参):

```json
{
  "messages": [
    {"role": "user", "content": "我想喝咖啡"},
    {"role": "assistant", "content": "为您推荐附近的咖啡门店"},
    {"role": "user", "content": "有没有离我近一点的"}
  ],
  "intent": "search_item",
  "params": {
    "taste": null,
    "occasion": null,
    "ingredient": null,
    "cuisine_region": null,
    "target_audience": null,
    "emotion_value": null,
    "party_size": null
  },
  "order_by": "distance"
}
```

- 输入:`item_features_ai` 一行 + prompt 模板(含 7 维字典子集)
- 输出:1 条训练样本
- 批量调用,batch_size 默认 16(可配)
- LLM temperature = 0.7(适度多样性,但不过发散)
- 1 条失败 → 写 `training_data_failures.jsonl`,继续其他
- 对话轮次:1~4 轮(可配,默认 3)
- `intent` 候选:`search_item` / `use_coupon` / `pay` / `view_order` / `browse`

### FR-002 7 维 Params 提取 + 字典校验

`params` 字段结构(对 7 维统一用 `op` + `values`):

```json
{
  "taste":         {"op": "contains", "values": ["辣", "麻"]},
  "occasion":      {"op": "in",       "values": ["午餐", "晚餐"]},
  "ingredient":    null,
  "cuisine_region":{"op": "contains", "values": ["川"]},
  "target_audience": null,
  "emotion_value": null,
  "party_size":    {"op": "eq",       "values": "2"}
}
```

7 个 op:

| op | 适用维度 | values 类型 | 示例 |
|----|----------|------------|------|
| `eq` | party_size | string(单值) | `{"op": "eq", "values": "2"}` |
| `contains` | taste / ingredient / cuisine_region | array<string> | `{"op": "contains", "values": ["辣", "麻"]}` |
| `in` | occasion / target_audience / emotion_value | array<string> | `{"op": "in", "values": ["午餐", "晚餐"]}` |
| `not_in` | occasion / target_audience / emotion_value | array<string> | `{"op": "not_in", "values": ["夜宵"]}` |
| `gt` / `lt` | (预留,本批不输出) | number | — |
| `between` | (预留,本批不输出) | [min, max] | — |

字典校验:
- `params` 字段名必须在 7 维中(多余字段 → 拒绝;缺失字段 → null 补齐)
- `values` 中的每个值必须在对应维度的字典候选值集合内
- 校验失败 → 写 failures + 跳过该样本
- 校验通过 → 字段按 7 维固定顺序写出(`taste, occasion, ingredient, cuisine_region, target_audience, emotion_value, party_size`)

### FR-003 降级与失败处理

- LLM 调用失败 / 超时(>15s) → 该样本写 `training_data_failures.jsonl` + 继续
- LLM 返回非 JSON / 缺 `messages` / 缺 `params` / 缺 `intent` → 写 failures + 跳过
- 字典校验失败 → 写 failures + 跳过(避免污染训练集)
- 全程不阻塞:`run_training_data.py` 是独立 run 脚本,失败不污染 `training_data_v1.jsonl`

### FR-004 增量 / 全量模式

`run_training_data.py --mode=full|incremental`
- **full**:对 `item_features_ai.jsonl` 所有行重算,覆盖 `training_data_state`
- **incremental**:用 `item_id` + `ai_tags` md5 指纹,只跑新增 / 修改 item
- 状态持久化:写入 `training_data_state.parquet`

### FR-005 多样性控制

- 同 item 生成的 N 条样本,messages 模板应差异化(避免"全部都是"我想喝 X"开头)
- 实现:`prompt.py` 提供多种"句式模板",LLM 随机选 1 种作骨架
- 验证:SC-005 — 100 条样本中,首句高频模板出现 ≤ 20%

### FR-006 负样本生成

- 比例可配(默认 0.1 = 10%)
- 负样本类型:
  - **拒绝型**:用户表达"不要"某条件(`"不要辣的"`)
  - **转移型**:用户换意图(`"算了不看咖啡了,看奶茶"`)
  - **不满足型**:无 item 满足 query(`"附近没这种店"`)
- 负样本字段:`negative: true`,`params` 仍正常填(模型应学会"不推荐"语义)
- `order_by: null`

### FR-007 数据清洗(LLM 生成后,二次过滤)

`run_training_data.py` 跑完 LLM 生成后,必须对 `training_data_v1.jsonl` 做二次清洗,过滤低质量样本。

**7 类清洗规则**(全开关可配):

| # | 规则 | 默认 | 触发 |
|---|------|------|------|
| 1 | **完全相同去重** | `text_hash`(md5 of `messages`+`params`)相同 → 留 1 条 | always on |
| 2 | **消息过短过滤** | 任一 `messages[].content` < `min_message_length` 字 → 删 | 默认阈值 10 字 |
| 3 | **模板重复降频** | n-gram 统计首句,高频模板(占比 > 30%)随机降频到 ≤ 20%(强化 SC-005) | always on |
| 4 | **params 全 null** | 7 维全 null → 删(训练意义小) | always on |
| 5 | **控制字符过滤** | messages 含连续 `\n\n\n+` / tab / 控制字符 → 删 | always on |
| 6 | **item_id 不在字典** | ai_tags 7 维字段名不在 `tag_dictionary.yaml` → 删 | always on |
| 7 | **对话轮次异常** | messages 长度 < 1 或 > `max_message_turns` → 删 | always on |

**降级路径**:
- 清洗后留存率 < 50% → 报警 + 记录到 `cleaning_failures.jsonl`(含被删原因)
- 不阻塞主流程:清洗失败样本单独记录,不入主输出

**SC-008**:数据清洗后留存率 ≥ 85%(原始 100% → 清洗后 85%+);留存率 < 50% 必须报警

### FR-008 数据平衡与分布统计

跑完清洗后,做分布统计 + 自动平衡动作。

**8 个分布指标**(必报告,写到 `distribution_report.json`):

| 指标 | 目标 | 不达标动作 |
|------|------|------------|
| 5 类 `intent` 比例 | 每类 ≥ 3% | 报警 + 触发过采样 |
| 7 维 `params` 非 null 比例 | 每个维度 ≥ 5% 样本含非 null | 报警 + 触发过采样 |
| 4 个 `op` 比例 | not_in ≥ 3%(训练"反意图"识别) | 报警 + 触发过采样 |
| 负样本比例 | `negative_ratio` ±0.02 | 报警 + 重新分配 |
| 对话轮次分布 | 1/2/3/4 轮 = 10/30/40/20 % ±5% | 报警 |
| 消息平均长度 | 20~80 字 | 报警 |
| 字典覆盖率 | 每个候选值至少出现在 5 个样本中 | 报警 |
| params 组合多样性 | 1000 条样本中至少 200 种唯一 params 组合 | 报警 |

**平衡动作**(自动):
- 长尾类(< 3%)→ 简单过采样(原样本 + LLM 同义改写 1 次,共 2x)
- 不平衡度 > 5 倍 → 警告(不强制平衡,避免过拟合)
- 输出 `distribution_report.json`(含 8 个指标 + 历史趋势对比)

**降级路径**:
- 平衡动作失败 → 记录到 `balancing_failures.jsonl`,主输出仍产出

**SC-009**:数据分布 8 个指标全部达标(或警告 ≤ 2 个);不达标报警但不阻塞主输出

### FR-009 数据集划分(按 item_id,80/10/10)

清洗 + 平衡后,**按 item_id 划分**训练 / 验证 / 测试集。

**划分规则**:
```python
# 同一 item 的所有样本必须在同一集合(避免数据泄露)
import hashlib
def split_key(item_id: str) -> str:
    h = int(hashlib.md5(item_id.encode()).hexdigest(), 16) % 100
    if h < 80:   return "train"
    elif h < 90: return "val"
    else:        return "test"
```

**比例**(可配,默认 80/10/10):
- `train_ratio: 0.8`
- `val_ratio: 0.1`
- `test_ratio: 0.1`

**输出 3 个文件**:
- `train.jsonl` — 用于 SFT 训练
- `val.jsonl` — 用于早停 + 超参选择
- `test.jsonl` — 用于最终评估(**绝不参与训练**)

**额外要求**:
- val / test 集中**真实数据(脱敏后)优先**(如有真实数据源)
- 划分后校验:同一 `item_id` 不跨集合(SC-010)

**SC-010**:训练/验证/测试集按 item_id 划分,无数据泄露(同一 item 不跨集合)

**SC-011**:val + test 集中真实数据(脱敏后)占比 ≥ 50%(如有真实数据源;无则 SKIP 不阻塞)

---

## 6. 数据契约

### 6.1 训练数据 jsonl schema(`training_data_v1.jsonl`)

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
  "llm_model": "claude-haiku-4-5"
}
```

> **字段集说明**:你示例里的 `params` 字段是 `category / merchant / distance / avg_prc / flavor` 5 维业务字段。
> 本 spec 按你回答"复用 7 维 AI 标签"对齐到 **7 维**(味/场/材/域/人/情/就);
> 若需要扩展到 distance/avg_prc/merchant 这类 LP 提参业务字段,后续可加 US5(扩展 params schema)。
> 本 spec 的 `op` / `values` 结构、`order_by` 字段都按你示例的范式保留。

### 6.2 失败日志 schema(`training_data_failures.jsonl`)

```json
{
  "item_id": "item-456",
  "raw_response": "...LLM 原始输出...",
  "error": "JSONDecodeError" | "MissingField" | "DictValidation" | "Timeout",
  "error_detail": "缺少 'messages' 字段",
  "occurred_at": "2026-06-14T10:00:00Z"
}
```

### 6.3 状态表 schema(`training_data_state.parquet`)

| 字段 | 类型 | 说明 |
|------|------|------|
| `item_id` | string | 商品 ID |
| `ai_tags_md5` | string | 7 维 AI 标签的 md5(增量比对用) |
| `sample_count` | int | 已生成样本数(默认 8) |
| `generated_at` | timestamp | 上次生成时间 |
| `llm_model` | string | 用的模型版本 |

---

## 7. 成功标准(SC)

| ID | 标准 | 验证方式 |
|----|------|----------|
| SC-001 | 1 万 item × 8 条/商品 = 8 万样本,跑批 < 60 分钟(LLM 50 req/min,16 并发) | `time python run_training_data.py --count=8` |
| SC-002 | `params` 字段 100% 在 7 维候选值集合内(字典校验通过率 100%) | 解析 + 字典校验 |
| SC-003 | LLM JSON 解析成功率 ≥ 95%(失败的写 failures,不入主产出) | 统计 `training_data_failures.jsonl` 行数 / 总请求数 |
| SC-004 | 输出 jsonl 100% 可被 `jq -c .` 解析 + LP Agent 训练管道直接读取 | `jq -c . training_data_v1.jsonl \| head` |
| SC-005 | **多样性**:100 条样本中,首句高频模板(如"我想喝 X")出现 ≤ 20% | 简单 n-gram 统计 |
| SC-006 | 增量模式:1% 增量(100 个新 item)重跑,耗时 < 5 分钟 | fixture 1 万 item + 100 增量 |
| SC-007 | 负样本占比 = 配置文件 `negative_ratio`(默认 0.1,允许 ±0.02 误差) | 统计 `negative=true` / 总数 |
| SC-008 | 数据清洗后留存率 ≥ 85%;留存率 < 50% 必须报警 | `len(cleaned) / len(raw) ≥ 0.85` |
| SC-009 | 数据分布 8 个指标全部达标(或警告 ≤ 2 个);不达标不阻塞 | 读 `distribution_report.json` 校验 |
| SC-010 | 训练/验证/测试集按 item_id 划分,无数据泄露(同 item 不跨集合) | 划分后跑 `splitter.validate_no_leak()` |
| SC-011 | val + test 集中真实数据(脱敏后)占比 ≥ 50%(如有真实数据源;无则 SKIP) | 统计 `source` 字段 |

---

## 8. 假设与依赖

- (A-001) `item_features_ai.jsonl` 已存在(来自 001-data-pipeline-enhancement)
- (A-002) 7 维字典已通过 `configs/tag_dictionary.yaml` 维护
- (A-003) LLM 平台沿用 001 spec 的"大模型平台托管 API"
- (A-004) 训练管道只读 jsonl,不做 schema 校验(由 LP Agent 训练方负责)
- (A-005) 7 维 AI 标签的"主题分布"(如川菜占比 30%)是合理的,反向合成的 query 不会偏移到无意义品类
- (A-006) `op` 类型以 `eq` / `contains` / `in` / `not_in` 4 个为主,`gt/lt/between` 留接口不实现

---

## 9. 边界与负面场景

| 场景 | 行为 |
|------|------|
| `item_features_ai.jsonl` 不存在 | `run_training_data.py` 退出非 0,提示先跑 001 ai_enhance |
| LLM 整体不可用(>30 min) | 退出非 0;已生成样本保留在 v1.jsonl |
| LLM 返回纯文本 | 解析失败 → failures |
| LLM 返回 JSON 但缺 `messages` / `params` / `intent` | failures + 跳过 |
| `params` 字典校验失败 | failures + 跳过(避免污染训练集) |
| 同一 item 重复生成 | 按 `item_id` 去重(增量模式) |
| 字典新增 1 个值,旧样本无该值 | 不重算旧样本;新样本可触发新值 |
| 训练管道读到的 jsonl 含历史 v0 字段 | LP Agent 训练方负责 schema 版本判断 |

---

## 10. 配置开关

```yaml
training_data:
  enabled: true
  llm:
    batch_size: 16
    timeout_seconds: 15
    temperature: 0.7
    model: claude-haiku-4-5
  mode: incremental                # full | incremental
  count_per_item: 8                # 5~10 区间,默认 8
  negative_ratio: 0.1              # 负样本比例(SC-007)
  max_message_turns: 3             # 1~4 轮,默认 3
  prompt_template: configs/prompts/training_data_v1.txt
  output_path: ./training_data_v1.jsonl
  failures_path: ./training_data_failures.jsonl
  state_path: ./training_data_state.parquet

  # === 阶段 2:数据清洗(FR-007) ===
  cleaning:
    enabled: true
    cleaned_path: ./training_data_cleaned.jsonl
    cleaning_failures_path: ./cleaning_failures.jsonl
    min_message_length: 10          # 规则 2:消息过短阈值
    template_repeat_threshold: 0.3  # 规则 3:触发降频的首句占比
    template_repeat_target: 0.2     # 规则 3:降频后目标占比
    min_retention_rate: 0.85        # SC-008 留存率下限
    alert_retention_rate: 0.50      # 留存率过低报警阈值

  # === 阶段 3:数据平衡与分布统计(FR-008) ===
  balancing:
    enabled: true
    report_path: ./distribution_report.json
    balancing_failures_path: ./balancing_failures.jsonl
    min_class_ratio: 0.03           # 长尾阈值(<3% 触发过采样)
    oversample_factor: 2            # 过采样倍数(原样本 + LLM 改写)
    max_oversample_ratio: 5         # 不平衡度上限(>5x 报警)
    intent_min_ratio: 0.03          # 5 类 intent 比例下限
    param_min_ratio: 0.05           # 7 维 params 非 null 比例下限
    op_not_in_min_ratio: 0.03       # not_in op 比例下限(SC-009 强化)
    negative_tolerance: 0.02        # 负样本比例容差(±2%)

  # === 阶段 4:数据集划分(FR-009) ===
  split:
    enabled: true
    train_ratio: 0.8
    val_ratio: 0.1
    test_ratio: 0.1
    train_path: ./train.jsonl
    val_path: ./val.jsonl
    test_path: ./test.jsonl
    real_data_priority: true        # val/test 真实数据优先(SC-011)
    real_data_min_ratio: 0.5        # val/test 真实数据占比下限
```

---

## 11. 待澄清

- (Q1) 字典新增值时,是否只补"新值相关"query?(已暂定:全量跑最简单,字典值变化概率低,留待实现期决定)
- (Q2) 训练管道是否需要 `messages` 字段带 `tool_calls` 模拟 LP Agent 工具调用?(本 spec 暂不生成,后续 US 可加)

---

## 12. 相关文档

- 001 spec:`specs/001-promo-recommend-agent/spec.md`(LP Agent 主 spec)
- 001 增强 spec:`specs/001-data-pipeline-enhancement/spec.md`(7 维 AI 标签源)
- 字典:`configs/tag_dictionary.yaml`
- 输出格式:本 spec 目录 `contracts/training_data_format_v1.md`
- 数据模型:本 spec 目录 `data-model.md`
