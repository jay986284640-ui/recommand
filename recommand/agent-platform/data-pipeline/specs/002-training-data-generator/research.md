# Research: 训练数据生成 — 关键技术决策

**Date**: 2026-06-14 | **Spec**: [./spec.md](./spec.md) | **Plan**: [./plan.md](./plan.md)

> 本文件记录 plan.md 中 D-001~D-007 7 个决策的更详细 rationale + alternatives considered。
> 决策都基于"为 LP Agent 意图识别 + 提参模型生成合成训练数据"这一目标。

---

## D-001:LLM 调用策略(1 段 vs 2 段)

**决策**:**1 段** —— 用 `structured output` 一次性产出 `messages + intent + params`,JSON schema 强约束。

**Rationale**:
- **延迟减半**:1 段单次 LLM 调用 ≈ 2~3s,2 段是 4~6s(2 倍延迟)
- **字段对齐精度更高**:同一段 prompt 上下文,LLM 不会"忘了对话里说了什么"导致 params 跟 messages 不对齐
- **代码简单**:1 套 prompt + 1 套 parser,不需要在对话和提参间做 ID 对齐
- **LP Agent 训练场景匹配**:提参模型训练的 ground truth 必须是"对话 → params"严格对应,1 段更接近真实分布

**Alternatives considered**:

| 方案 | 优势 | 劣势 | 决策 |
|------|------|------|------|
| **1 段(本决策)** | 延迟低 / 字段对齐 / 代码简单 | prompt 长,token 多 ~30% | ✅ |
| 2 段(先生成对话,再单独提参) | prompt 短 / 提参 prompt 可独立调 | 延迟翻倍 / 字段易错位 | ❌ |
| 多段(逐轮生成 + 逐轮提参) | 可模拟工具调用 / 多 agent | 复杂度极高 / 延迟 5x+ / 现阶段不需要 | ❌ |

**实施细节**:
- 用 Anthropic `messages.create(response_format=...)` 或 OpenAI `response_format={"type": "json_schema", ...}` 强制 JSON
- prompt 中给出完整 JSON schema 样例,LLM 严格按格式输出
- 解析失败 → failures,不阻塞主流程

---

## D-002:对话轮次分布(固定 vs 随机)

**决策**:**1~4 轮随机**,权重:1 轮 10% / 2 轮 30% / 3 轮 40% / 4 轮 20%。

**Rationale**:
- **真实分布**:用户对话 80% 是 1~3 轮(简答 query),少数 4 轮以上(复杂场景)
- **3 轮为主(40%)**:贴你示例的"用户 → 助手 → 用户再细化"模式
- **1 轮不能丢(10%)**:训练提参模型对单轮 query 的支持(短 query 也得能提参)
- **4 轮不能太多(20%)**:避免 LLM 编不出内容时硬凑,降低失败率

**Alternatives considered**:

| 方案 | 优势 | 劣势 | 决策 |
|------|------|------|------|
| **1~4 轮随机(本决策)** | 贴近真实 / 覆盖全 | 需要权重配置 | ✅ |
| 固定 3 轮 | 实现最简 | 短 query / 长 query 覆盖不到 | ❌ |
| 1~8 轮全随机 | 覆盖广 | 5 轮以上 LLM 容易跑题,失败率 ↑ | ❌ |
| 全部 1 轮(单 query) | 失败率最低 | 不符合 LP Agent 多轮对话设计 | ❌ |

**实施细节**:
- `TrainingDataConfig.max_message_turns=3`(上限),prompt 中随机选 `1~4` 轮
- 轮次通过 `random.choices([1, 2, 3, 4], weights=[0.1, 0.3, 0.4, 0.2])` 选
- 同一 item 的 N 条样本(`count_per_item=8`)轮次分布应该接近上述权重

---

## D-003:维度采样(全 7 维 vs 随机 N 维)

**决策**:**每条样本随机选 2~4 维**(从 7 维中)来表达 query 条件。

**Rationale**:
- **真实用户不会一次性表达所有条件**:用户说"我想吃辣的川菜"只覆盖 2 维(taste + cuisine_region)
- **避免过拟合"全堆"模式**:如果 100% 样本都是 7 维全填,模型会学"只要 user 提到 X,7 维都要填",与真实推理场景不符
- **覆盖度反而更好**:每条样本少填几维,8 条样本加起来能覆盖更多(维度 × 值)组合

**采样规则**:
- 7 维中随机选 2~4 维(权重均匀)
- 选中的维度从对应字典随机选 1~3 个候选值
- 未选中的维度 → `null`(本样本不指定)

**Alternatives considered**:

| 方案 | 优势 | 劣势 | 决策 |
|------|------|------|------|
| **2~4 维随机(本决策)** | 贴近真实 / 覆盖广 | 实现略复杂 | ✅ |
| 全 7 维 | 数据完整 | 失真 / 模型过拟合"全堆"模式 | ❌ |
| 固定 1 维 | 最简 | 不足以训练复杂提参 | ❌ |
| 5~7 维 | 接近全堆 | 同上 | ❌ |

---

## D-004:字典版本化(硬编码 vs 外部 yaml)

**决策**:**外部 yaml**(沿用 001 `configs/tag_dictionary.yaml`),**只读不改**。

**Rationale**:
- **001 已维护**:字典运营已经在 yaml 里维护,本子包直接读
- **热加载**:运营改字典后,下次跑 `run_training_data.py` 自动生效
- **避免重复定义**:不引入第二份字典,避免两份不一致
- **dict 校验逻辑只校验候选值集合**:不校验 op 类型,op 类型是 hardcode(只有 4 个,改 op 需要改代码,合理)

**Alternatives considered**:

| 方案 | 优势 | 劣势 | 决策 |
|------|------|------|------|
| **外部 yaml 沿用(本决策)** | 复用 001 / 热加载 / 单一来源 | 依赖 001 yaml 路径 | ✅ |
| 独立 yaml | 本子包自治 | 重复维护 / 容易不一致 | ❌ |
| 硬编码字典 | 0 依赖 | 改字典要改代码 + 部署 | ❌ |
| DB 字典 | 实时 | 增加 DB 依赖 | ❌ |

**实施细节**:
- `param_schema.py` 启动时读 `configs/tag_dictionary.yaml`(由 `tag_schema.load_dictionary()` 封装)
- 字典读取走 SparkSession / 配置文件路径,不引入新依赖
- 字典文件变化时,本子包不需要重启服务(下次跑批重新加载)

---

## D-005:负样本类型(单类 vs 多类)

**决策**:**3 类**:reject(拒绝) / pivot(转移) / unsatisfiable(不满足),权重 0.4 / 0.4 / 0.2。

**Rationale**:
- **reject(40%)** —— 训练模型识别"用户不要 X",LP Agent 应过滤掉 X 标签商品
- **pivot(40%)** —— 训练模型识别"用户换意图",LP Agent 应重置过滤条件
- **unsatisfiable(20%)** —— 训练模型识别"无匹配",LP Agent 应返回"未找到"提示
- 3 类覆盖了 LP Agent 实际会遇到的负面场景(用户拒绝 / 转移 / 无结果)

**权重理由**:
- reject 和 pivot 是高频场景(用户多轮对话中常出现)
- unsatisfiable 频率低(空跑批 + 用户追问)
- 总比例 = `negative_ratio`(默认 0.1,10%)

**Alternatives considered**:

| 方案 | 优势 | 劣势 | 决策 |
|------|------|------|------|
| **3 类(本决策)** | 覆盖广 / 权重可调 | prompt 多 3 套指令 | ✅ |
| 仅 reject | 实现最简 | 覆盖不足 | ❌ |
| 5+ 类(加"延迟型" / "犹豫型") | 更细 | LLM 难以区分,失败率 ↑ | ❌ |
| 全 50% 负样本 | 强化负向学习 | 训练集整体偏负,模型预测失衡 | ❌ |

**实施细节**:
- `negative_sampler.py` 提供 3 套 prompt 指令片段
- `prompt.py` 的 `negative_instruction` 字段根据 `sample_negative_type()` 注入
- 负样本的 `params` 仍正常填(模型应学会"按这个 params 过滤后不推荐"),`order_by: null`

---

## D-006:op 类型集合(4 个基础 vs 7 个完整)

**决策**:**本批实现 4 个基础 op**:`eq` / `contains` / `in` / `not_in`;`gt` / `lt` / `between` 留接口不实现。

**Rationale**:
- **7 维都是分类字段**(味/场/材/域/人/情/就),本批不需要数值比较
- **数值字段(avg_prc / distance)在 7 维中不存在**:US5 扩展时才需要 `gt/lt/between`
- **简化字典校验**:只校验 4 个 op,逻辑清晰,测试覆盖完整
- **LLM 不会乱用**:prompt 中明确说"只用这 4 个 op",LLM 偶发输出 `gt` → `DictValidation` 拒收

**接口预留**:
- `OP_TYPES` 常量含 7 个 op(便于 US5 直接启用)
- `validate_params()` 对 `gt/lt/between` 返回 `DictValidation` 错误(SC-002 通过)
- 数据契约 `param_op_types.md` 列出 7 个,标注本批 4 个 + 预留 3 个

**Alternatives considered**:

| 方案 | 优势 | 劣势 | 决策 |
|------|------|------|------|
| **4 个基础 + 3 个预留(本决策)** | 实施快 / 接口完整 | 数值字段延后 | ✅ |
| 7 个全实现 | 不延后 | 数值字段用不到 / 校验复杂 | ❌ |
| 2 个(只 `eq` + `in`) | 最简 | 表达力不够 | ❌ |

---

## D-007:多样性控制(模板 vs 温度 vs 二者结合)

**决策**:**二者结合**:prompt 注入 5~8 套句式骨架让 LLM 选 + `temperature=0.7`。

**Rationale**:
- **句式骨架**:让 LLM 在"我想喝 X" / "X 怎么样" / "推荐个 X" / "附近有 X 吗" / "X 求推荐" / "想找 X" / "X 哪里好吃" / "想试试 X" 这 8 套里选一套,避免千篇一律的首句
- **temperature=0.7**:适度的随机性,既能覆盖句式变化,又不会太发散(如果 1.0 容易跑题)
- **种子可复现**:`pick_template(seed=item_id)` 同 item 必出同模板;`random.Random()` 内部 state 可控
- **SC-005 验证**:100 条样本首句 n-gram 统计,最高频模板占比 ≤ 20%(在 `test_diversity_freq.py` 跑)

**句式骨架示例**(8 套):

| # | 句式骨架 | 适用场景 |
|---|----------|----------|
| 1 | "我想喝/吃 {item_title_keyword}" | 单 query 1 轮 |
| 2 | "{item_title_keyword} 怎么样" | 单 query 1 轮 |
| 3 | "推荐个 {item_title_keyword}" | 单 query 1 轮 |
| 4 | "附近有 {item_title_keyword} 吗" | 单 query 1~2 轮 |
| 5 | "{item_title_keyword} 求推荐" | 单 query 1 轮 |
| 6 | "想找 {item_title_keyword}" | 单 query 1 轮 |
| 7 | "{item_title_keyword} 哪里好吃/好喝" | 单 query 1 轮 |
| 8 | "想试试 {item_title_keyword}" | 单 query 1 轮 |

**Alternatives considered**:

| 方案 | 优势 | 劣势 | 决策 |
|------|------|------|------|
| **句式 + 温度(本决策)** | 多样性高 / 失败率可控 | 需要维护 8 套句式 | ✅ |
| 仅句式 | 0 LLM 随机 | 句式间仍有相似模式 | ❌ |
| 仅高温(1.0) | 0 句式维护 | 失败率 ↑ / 易跑题 | ❌ |
| 仅低温(0.2) | 失败率低 | 多样性差 | ❌ |
| N-gram 复检(LLM 输出后再去重) | 极致多样 | 实现复杂 / 延迟 + | ❌ |

**实施细节**:
- `diversity.py`:`DIALOGUE_TEMPLATES` 常量(8 套),`pick_template(seed=None) -> str`
- `prompt.py` 渲染时把 `dialogue_template` 注入到 prompt 的 `{dialogue_template}` 占位符
- LLM 按句式骨架生成首句 + 续写
- `temperature=0.7` 在 `TrainingDataConfig` 里配

---

## 综合:Linux 容器性能基线(SC-001 推算)

**目标**:1 万 item × 8 条/商品 = 8 万样本 < 60 分钟

**计算**:
- LLM 限速:50 req/min(大模型平台典型限速)
- 并发 semaphore=16
- 单次 LLM 调用:2~3s(prompt ~2k tokens,response ~500 tokens)
- 16 并发 × 60s ÷ 2.5s ≈ 384 req/min(理论)
- 实际受限于 50 req/min 限速:50 req/min × 60 min = 3000 req/min ... 等等,重算:
  - **8 万样本 ÷ 50 req/min = 1600 min** ❌ 远超 60 min

**修正**:需提升 LLM 限速到 ≥ 1500 req/min,或降低样本量(8 → 1)。**与客户确认限速后调整**:
- 如果限速 1500+ req/min:SC-001 可达成(8 万样本 < 60min)
- 如果限速 < 1500 req/min:SC-001 不可达成,需调整 `count_per_item=2~3` 或 SC-001 放宽到 120 min

> **风险标注**:SC-001 强依赖 LLM 限速,需在实施期先做限速压测,再定 `count_per_item` 默认值。

---

## 决策表(汇总)

| ID | 决策点 | 决策 | 影响 |
|----|--------|------|------|
| D-001 | LLM 调用策略 | **1 段** structured output | 延迟 -50% / 代码 -30% |
| D-002 | 对话轮次分布 | **1~4 轮随机**(权重 10/30/40/20) | 贴近真实 / 失败率可控 |
| D-003 | 维度采样 | **2~4 维随机** | 避免过拟合 / 覆盖广 |
| D-004 | 字典版本化 | **外部 yaml 沿用** | 单一来源 / 热加载 |
| D-005 | 负样本类型 | **3 类**(reject/pivot/unsatisfiable) | 覆盖广 / 权重可调 |
| D-006 | op 类型集合 | **4 基础 + 3 预留** | 实施快 / 接口完整 |
| D-007 | 多样性控制 | **句式 + 温度 0.7** | 多样性高 / 失败率低 |

---

## 风险与依赖

| 风险 | 缓解 |
|------|------|
| LLM 限速 < 1500 req/min,SC-001 不可达 | 实施期先压测;`count_per_item` 默认值可调 |
| 字典变更后旧样本无新值,模型预测偏移 | 增量模式重跑(FR-004);字典变更频次低 |
| 7 维对 LP Agent 提参业务字段(distance/avg_prc)不够 | US5 扩展;本批先覆盖 7 维 |
| LLM 偶发输出字典外值,字典校验拒收率 > 5% | prompt 强化字典子集约束;失败样本进 `failures.jsonl` 排查 |
| 多样性不足,SC-005 不达标 | 8 套句式 + 温度 0.7;实测后调权重 |

---

## 后续(本 spec 不做)

- US5:扩展 `params` 字段到 LP 提参业务字段(`category` / `merchant` / `distance` / `avg_prc` / `flavor`)
- US6:对话生成中模拟 LP Agent 工具调用(`tool_calls` 字段)
- US7:与 LP Agent 训练管道打通(直接喂 HuggingFace datasets,不经 jsonl 中转)
