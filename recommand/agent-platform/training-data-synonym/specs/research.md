# Research: 训练数据生成 (兴业 O2O 三品类 SFT 语料)

**Spec**: [./spec.md](./spec.md) (v2.4) | **Plan**: [./plan.md](./plan.md) | **Date**: 2026-06-22

---

## 概述

Phase 0 收敛 14 个技术决策(D-001 ~ D-014),为 Phase 1 数据模型 / 契约 / quickstart 提供前置依据。

研究范围:**Hive 读侧适配器、字典 / 映射数据结构、LLM prompt 设计、增量与降级策略、CI 脱机能力**。研究边界 = `agent-platform/training-data/` 子包内部;不涉及 LP Agent 主体、不改 `data-pipeline/`、不改 `tabale_structer.sql`。

---

## D-001 — 子包架构 vs 复用 `data-pipeline` 子模块

| 选项 | 优点 | 缺点 |
|------|------|------|
| (A) 全独立 Python 包 `training_data/` | Library-First(P-I)清晰;依赖单向;CI 隔离;可独立 release | 部分 dataclass(`LLMClient` 抽象)需复制 |
| (B) 复用 `data-pipeline.feature_extraction.training_data/` 子模块 | 复用 LLMClient / 字典加载 | 反向耦合到 data-pipeline;违反 Library-First |

**Decision**:**(A) 全独立**。

**Rationale**:Constitution Principle I("Library-First")明确要求子包自包含;`agent-platform/training-data/` 已是顶层兄弟目录,与 `data-pipeline/` 平级。少量重复(LLMClient 抽象)通过**接口契约**层面对齐,避免代码反向依赖。

**Alternatives considered**:(B) 在迭代早期被验证为"反向耦合 + 同步发布枷锁",已弃。

---

## D-002 — Hive 读侧适配器选型

| 选项 | 优点 | 缺点 |
|------|------|------|
| (A) PySpark Hive Catalog | 与 data-pipeline 一致;批量并行;Kerberos 内建;分区下推 | 启动慢(JVM ~10s);依赖 Spark 集群 |
| (B) PyHive (HiveServer2) | 轻量;无 JVM | 大表慢(单线程);无分区下推优化 |
| (C) Trino + trino-python-client | 跨集群查询;SQL 表达力强 | 兴业当前无 Trino 部署 |

**Decision**:**(A) PySpark(生产)+ MockHiveReader(CI)**;**(B) PyHive 保留为"非 Spark 环境"备选后端**。

**Rationale**:① 兴业现有 data-pipeline 已部署 Spark 3.5.3 客户端,运维成本最低;② Stage 1 一次性读最近 1 个分区的 3 张核心表(<10 万行级)是 Spark 的舒适区;③ PyHive 后端通过同一 `HiveReader` 抽象切换,不污染上层代码。

**Alternatives considered**:(C) Trino 在客户环境不可用。

---

## D-003 — 增量指纹键

| 选项 | 覆盖场景 |
|------|---------|
| (A) `item_id + raw_md5` | 行变更 |
| (B) `item_id + raw_md5 + dict_version` | 行变更 + 字典升级 |
| (C) `item_id + raw_md5 + dict_version + etl_dt` | 行变更 + 字典升级 + 新分区到达 |

**Decision**:**(C) 四元组**。

**Rationale**:Hive 按 `etl_dt` 分区写入;新分区到达必须触发该日 item 的 Stage 1 重算(否则会复用旧分区指纹),`etl_dt` 是必备维度;`dict_version` 由 `dim_dictionary.yaml._meta.version` + `consumable_type_map.yaml._meta.version` 双字段联合 md5 派生。

**Alternatives considered**:(A) / (B) 在新分区或字典升级场景下会漏算,被弃。

---

## D-004 — `distance` 维度路径

**Decision**:**透传**(`shop_lng/lat` 落 `raw_record`,Stage 1 `tags.distance` 始终 null;Stage 2 字典直采)。

**Rationale**:用户明确(spec v2.4 Clarifications Q3):SFT 训练目标是提参准确性,`distance` 与几何无关。透传方案兼顾"下游 LP Agent 运行时可计算真实距离"+"SFT 不耗几何运算"。

**Alternatives considered**:LLM 推断(spec v2.1 之前)/ Stage 2 haversine 计算(spec v2.2)— 已在 Clarifications Q1 与 Q3 中被否决。

---

## D-005 — `consumable_type` 维度路径

**Decision**:**`configs/consumable_type_map.yaml` 映射 + LLM 兜底**。

**Rationale**:90%+ 的 item 可由 `category` 直接映射(`category` 在 12 个候选值内,映射规则确定),节省 LLM 调用;映射失败的兜底(`category` 缺失 / 不在映射表 / 券文案冲突)走 LLM,落字典后 `tag_source.consumable_type = ai`,保证全维度可推断。

**Alternatives considered**:全 LLM(浪费 token,违反 Simplicity)/ 全规则(优惠券文本与品类常冲突,误判率高)— 已弃。

---

## D-006 — SFT `distance` 与 `order_by` 来源

**Decision**:**`dim_dictionary.distance` 字典直采,与 lng/lat 解耦**;`order_by` 5 类按可配分布抽样,与 `params.distance` 非 null 状态**双向耦合**(详见 spec v2.4 FR-013b)。

**Rationale**:见 D-004;此处仅强化"采样耦合":`params.distance` 非 null 时 `order_by=distance` 概率 ≥ 60%,`params.distance = null` 时 ≤ 5%,确保模型学到"用户表达距离 → order_by=distance"的强信号。

**默认参数**:

```yaml
distance_param_ratio: 0.30                 # 30% 样本含 distance
distance_bucket_weights: [0.25, 0.25, 0.25, 0.25]   # 4 桶等权
order_by_distribution: [0.30, 0.20, 0.15, 0.10, 0.25]   # distance/price/rating/time/null
order_by_distance_when_param_present: 0.60   # 耦合下限
order_by_distance_when_param_null:    0.05   # 耦合上限
```

**Rationale(为什么 4 桶等权)**:训练集要让模型识别"近 / 中近 / 中远 / 远"四档表达,均衡比模仿真实分布更重要(SFT 目标是 P/R 而非校准)。

**Alternatives considered**:几何计算(已在 spec Clarifications Q3 否决);偏置分布(近距偏高)留给运维通过配置调,不写死。

---

## D-007 — `consumable_type_map.yaml` 初始映射

**Decision**:覆盖 `dim_dictionary.category` 全部 12 个候选值 + `default: none` 兜底。

```yaml
_meta:
  version: 1.0
  description: category(品类) → consumable_type(吃 / 喝)的映射表;FR-008c 用
map:
  drink:
    - 咖啡
    - 奶茶
  food:
    - 快餐
    - 中餐
    - 西餐
    - 日料
    - 火锅
    - 烧烤
    - 烘焙
    - 甜品
  mixed:
    - 便利店
    - 水果
default: none                              # 未识别 / 非餐饮兜底
coupon_text_hints:                         # FR-008c.5 — 优惠券文本判定关键词种子
  drink: [咖啡, 拿铁, 美式, 奶茶, 茶饮, 果汁, 饮品, 椰汁, 柠檬]
  food:  [汉堡, 炸鸡, 面, 烤, 寿司, 火锅, 套餐, 米饭, 烤肉]
  mixed: [便利店, 综合]
```

**Rationale**:`dim_dictionary.category` 已有 12 值,本映射表 11 值已显式声明(`咖啡/奶茶 → drink`、`快餐/中餐/西餐/日料/火锅/烧烤/烘焙/甜品 → food`、`便利店/水果 → mixed`)。`水果` 入 `mixed` 是因为兼有现榨果汁的可能(运营反馈)。

**Alternatives considered**:`水果 → food` — 与现榨场景冲突;`甜品 → mixed` — 主销冰品 / 烘焙,纳入 food 更直观。本映射版本号 1.0,后续按运营反馈版本化。

---

## D-008 — 负样本类型

**Decision**:**3 类**(`reject / pivot / unsatisfiable`),沿用 spec v2.4 FR-013。

**Rationale**:覆盖 LP Agent 线上易错三类场景:

- `reject`:用户给出负向条件("不要太辣")— 训练模型识别 `op=not_in`。
- `pivot`:用户切换意图("不看咖啡看奶茶")— 训练模型识别上下文切换。
- `unsatisfiable`:无满足项("附近没这种店")— 训练模型识别"无 item"。

每类占比 ≥ 20%(spec SC-006),总负样本 10%(配置 `negative_ratio=0.10`)。

**Alternatives considered**:5 类(细分"价格太贵 / 远 / 时间不合适")— 实施期可扩展;本批先 3 类。

---

## D-009 — `op` 类型集合(本批实现)

**Decision**:**4 个**(`eq / contains / in / not_in`);`gt / lt / between` 留接口,本批字典校验拒绝。

**op ↔ 维度映射**(详见 `contracts/param_op_types_v2.md`):

| dim | op | values 类型 |
|-----|----|------------|
| `category` | `in` | array<string> |
| `consumable_type` | `eq` | string(单值) |
| `merchant` | `in` | array<string> |
| `avg_prc` | `in` | array<string>(桶 ID) |
| `distance` | `in / not_in` | array<string>(桶 ID) |
| `age` | `in` | array<string> |
| `occasion` | `in` | array<string> |
| `taste` | `contains / not_in` | array<string> |

**Rationale**:本批 op 集合保持向后兼容 spec v1 的 `param_op_types.md`;`gt/lt/between` 在 `avg_prc / distance` 数值化时启用(US5 扩展)。

---

## D-010 — Stage 1 LLM prompt 模板

**Decision**:**单 prompt + 字段子集注入**(`configs/prompts/enrichment_v1.txt`)。

**结构**:

```text
你是一个 O2O 推荐系统的标签补全助手。
给定一个商品的原始信息(品类、品牌、价格、文案等),请输出 6 维标签(JSON):
{
  "category": "<必填,从字典选>",
  "merchant": "<可选,品牌>",
  "avg_prc":  "<可选,价格桶>",
  "age":      "<可选,目标客群年龄段>",
  "occasion": "<可选,消费场合>",
  "taste":    ["<可选,口味数组>"]
}

候选字典(注入 6 维各自值):
- category: [咖啡, 快餐, 奶茶, ...]
- merchant: [星巴克, 瑞幸, ...]
- avg_prc:  ["0-30", "30-50", ...]
- age:      ["18-25", "25-35", ...]
- occasion: [早餐, 午餐, ...]
- taste:    [甜, 咸, 辣, ...]

要求:
- 严格 JSON,不写字典外值;
- 不知道的字段填 null,不要编造;
- consumable_type 与 distance 不属于本任务,不要输出;
- 不要写解释。

原始信息:
{raw_record}
```

**Rationale**:`distance` / `consumable_type` 不进 prompt;6 维注入字典子集让 LLM 落字典;少 few-shot,降低 token 成本(每次调用 ~800 token)。

**Alternatives considered**:多 prompt 分维度独立调用 — 6× 调用成本,无显著质量提升,弃。

---

## D-011 — Stage 2 LLM prompt 模板

**Decision**:**单 prompt + 多轮对话生成 + ground-truth 注入**(`configs/prompts/sft_v1.txt`)。

**结构**:

```text
你是一个生成 SFT 训练样本的助手。
给定一个商品(item)和**目标 params/intent/order_by**,生成 1~5 轮的用户↔助手对话,使得对话表述能被反向解析回这些目标值。

商品信息(8 维标签):
{item_tags}

目标:
- intent:    {target_intent}
- params:    {target_params}             # 8 维 ParamSpec / null
- order_by:  {target_order_by}
- 对话轮数:  {target_turns}              # 1~5,首条 user
- 负样本类型: {negative_type}             # none / reject / pivot / unsatisfiable
- 句式骨架:  {sentence_template}         # 5~8 套,随机选 1

输出严格 JSON:
{
  "messages": [{"role": "user", "content": "..."}, {"role": "assistant", ...}, ...],
  "covered_dims": ["category", "distance", ...]
}

约束:
- messages 长度 = {target_turns};
- 用户表述要自然口语化,不照搬字典值(如 distance="0-500" → "500 米以内 / 走路 5 分钟");
- params.distance 若非 null,user 必须显式提到距离;
- consumable_type 若非 null,user 应用"想吃 / 想喝"等粗粒度词;
- 负样本时,user 末轮必须表达拒绝 / 切换 / 不满意;
- 不要输出 explanation。
```

**Rationale**:Stage 2 把 ground-truth 显式注入 prompt,让 LLM"作出"对应表述,这是 SFT 数据生成的标准范式("逆向 NLU")。

**Alternatives considered**:LLM 自由生成 + 后置 NLU 标注 — 标注成本高且不稳;放弃。

---

## D-012 — LLM 调用降级策略

**Decision**:**重试 2 次 → 失败写 failures → 跳过该样本继续**。

```python
@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
def call_llm(prompt: str) -> dict:
    ...

try:
    sample = call_llm(prompt)
    validate(sample)              # 字典校验
except (TimeoutError, JSONDecodeError, ValidationError) as e:
    write_failure(item_id, str(e))
    return None                   # 跳过
```

**Rationale**:Constitution V Observability + spec FR-007/022 — 单样本失败不阻塞主流程;失败明细全量留存;> 30 分钟连续失败触发 alert 并退出非 0(FR-007 边界)。

**Alternatives considered**:无限重试(雪崩风险)/ 直接退出(单点故障放大)— 弃。

---

## D-013 — Mock Hive 实现

**Decision**:**fixture 目录** `tests/fixtures/hive/`,每张表 1 个 jsonl,行字段与 `tabale_structer.sql` DDL 严格一致(包含 `etl_dt` 列)。

**目录结构**:

```text
tests/fixtures/hive/
├── o2o_new_gut_shop_base_third.jsonl        # 美团门店 100 行,含 50 有 lng/lat + 50 无
├── o2o_new_gut_shop_base.jsonl              # 自拓展门店 100 行
├── o2o_new_gut_shop_address.jsonl           # 自拓展门店地址(覆盖 80%)
├── o2o_new_gut_coupon_template.jsonl        # 100 张券
├── o2o_new_gut_coupon_shop.jsonl            # 券-门店绑定(覆盖 70 张券)
├── o2o_new_gut_shop_category_meituan.jsonl  # 美团品类映射
└── o2o_new_gut_shop_category_mapping.jsonl  # 美团-自营品类映射
```

**Rationale**:fixture 目录 vs 内联 fixture:目录可独立替换、可大体量、可分桶覆盖边界(冷启动 / 多门店券 / 缺 lng/lat 等);内联会让 pytest 文件巨化。

**Alternatives considered**:`sqlite + DDL` 模拟 Hive — 类型映射成本高,弃。

---

## D-014 — 离散 LLM 录像

**Decision**:**录关键 case**(`tests/fixtures/llm/mock_responses.jsonl`)。

**录入规则**:

- 每个 unit test 至少 1 条录像(对应一个 prompt key)。
- 录像键 = `hash(prompt_text)`;mock client 命中 → 直返录像;未命中 → 走启发式 fallback(`heuristic_response()`)。
- 启发式 fallback 实现:基于字典随机 + 模板填空 + 注入失败 case(用于测降级)。

**Rationale**:CI 必须可复现 + 离线;录像保证关键决策路径稳定测试;启发式 fallback 让 fixture 缺失时仍可跑测,降低维护成本。

**Alternatives considered**:VCR 风格全请求录像 — 与 LLMClient 抽象冲突;真实 API 录制 — 不可重现。弃。

---

## 性能模型(SC-010 验证)

| 阶段 | 关键瓶颈 | 估算 |
|------|----------|------|
| SQL 解析 + Hive 读 | Spark 启动(JVM) + 1 分区拉取 | ~30s + ~3 min(3 表 × 1 分区,假定 10 万行/表) |
| Stage 1 LLM 调用 | 50 req/min × 16 并发 | 1 万 item × 6 维 × 1 次/item = 1 万 req,约 12 分钟 |
| Stage 1 几何透传 + 映射 | 纯 CPU | < 1 分钟 |
| Stage 2 LLM 调用 | 同上 | 8 万 sample × 1 次/sample = 8 万 req,约 27 分钟 |
| 清洗 + 分布 + 划分 | 纯 CPU + 一次性扫描 | < 5 分钟 |
| **合计** | — | **~50 分钟**(SC-010 < 90 分钟,**裕度 40 分钟**) |

**裕度用途**:LLM 错误重试 / 字典校验失败重试 / 网络抖动。

---

## CI 脱机能力(Constitution V Simplicity)

| 依赖 | CI 替代 | 说明 |
|------|---------|------|
| Hive 集群 | `MockHiveReader` + `tests/fixtures/hive/` | `--source=mock`,完整契约一致 |
| LLM 平台 | `MockLLMClient` + `tests/fixtures/llm/` | 录像 + 启发式 fallback |
| Spark | 跳过 PySpark adapter import,只测 mock + pyhive | 单测不需 Spark |
| Kerberos / LDAP | 不涉及 | mock 路径无认证 |

**结论**:CI 100% 脱机可跑,单测 + 契约测 + 集成测全绿。

---

## 安全与隐私(spec A-008 落地)

| 字段 | 来源表 | 处理 |
|------|--------|------|
| `MASTERCARD_CUST_ID` | `CDM_ADM_CUST_INFO_STAT_F` | Hive 读入后立即 drop 列(`HiveReader.sensitive_columns_blocklist`) |
| `Crt_Psn_Id / Updt_Psn_Id / Opr_Psn_Id` | 几乎所有 o2o 表 | 同上 |
| `creator / updatePerson` | `o2o_new_gut_coupon_template` | 同上 |
| `shop_lng / shop_lat` | 透传到 `raw_record` | 保留(运行时计算距离需要);6 位小数精度;非个人字段 |
| `user_id / distinct_id`(c10) | 不消费 | 本批不读 c10 表 |

**审计点**:`HiveReader.read()` 出口必有"敏感列剔除断言",任何泄露通过单元测试(`test_hive_reader.py::test_sensitive_drop`)拦截。

---

## 与既有产物的对齐 / 取舍

| 产物 | 当前状态 | 处置 |
|------|---------|------|
| `agent-platform/data-pipeline/specs/002-training-data-generator/` | v1,与本工程为兄弟 spec | **保留作为 v1 历史**;本工程 spec v2.4 通过 superseded 标注引用 |
| `agent-platform/training-data/scripts/*.py` | demo legacy | 保留为兼容薄壳,实际逻辑迁入 `training_data/` 包 |
| `agent-platform/training-data/configs/dim_dictionary.yaml` | 7 维 | **改为 8 维**(新增 `consumable_type`),版本 1.0 → 2.0 |
| `agent-platform/training-data/configs/brand_dictionary.yaml` | 60+ 品牌 | 保留 |
| `agent-platform/training-data/docs/ALIGNMENT_cib_o2o.md` | 已对齐 v2.x | 微更新:加 consumable_type 段落、Hive 数据源段落 |

---

## D-015 — 字典扩量策略(US4 Stage 0)

| 选项 | 优点 | 缺点 |
|------|------|------|
| (A) 手工 yaml | 直接,无工程量 | 字典规模小(<200 品牌),漏新品牌;运营负担重 |
| (B) SQL 抽取 + 双阈值聚类 | 全量覆盖;跨脚本不合并;半自动 | 需维护阈值参数 |
| (C) 第三方 ETL (Airflow / NiFi) | 流程化 | 引入新依赖,本项目无该基础设施 |

**Decision**:**(B) SQL 抽取 + 双阈值聚类**。

**Rationale**:① 当前 60+ 手工品牌字典,在 Hive 真实数据中应达 1万~5万行;② `extract-dictionary` 离线工具,与 Stage 1/2 主流水线解耦;③ Levenshtein + char n-gram Jaccard 双阈值聚类在中文 / 英文混合场景下表现稳定。

---

## D-016 — 品牌聚类指标选择

| 选项 | 适用 |
|------|------|
| (A) 单一 Levenshtein | 中文易误判(2 字符差异 → 距离 2 易合并),英文长字符串精确 |
| (B) 嵌入相似度(sentence-transformers) | 语义级,但需 GPU / 大模型 |
| (C) Levenshtein + char 2-gram Jaccard 双阈值 | 字符级 + 子序列级;纯 CPU;无外部依赖 |

**Decision**:**(C) 双阈值聚类**。

**Rationale**:① 字符级精确(避免"星巴克" / "新巴克"误合);② char 2-gram Jaccard 处理变长字符串相似性;③ 默认阈值 Levenshtein ≤ 3 + Jaccard ≥ 0.6,任一不满足不合并(避免假阳性)。

---

## D-017 — 跨脚本品牌处理

**Decision**:**强制分开**(CJK vs Latin 不合并)。

**Rationale**:中文 "星巴克" 与英文 "Starbucks" 在 Levenshtein 上距离 > 3,在 char 2-gram Jaccard 上几乎为 0;现有阈值自动分离。运营若需要"星巴克 ↔ Starbucks"映射,在 yaml 中手动加 alias 注释即可。

---

## D-018 — 离线 vs 在线治理循环

**Decision**:**独立 CLI**(本工程 stage 0,off-cycle ops 工具)。

**Rationale**:① 字典扩量不阻塞 SFT 生产出货;② 人工 review + PR 流程天然隔离(产品 / 运营 vs 算法);③ `dict_version` md5 自动变 → Stage 1 自动增量重算,无需改任何代码。每季度跑 1 次即可。

---

## Open follow-ups(供 `/speckit-tasks` 与 `/speckit-implement` 关注)

1. (D-002 / 适配器):PySpark 适配器需要在生产环境跑通 1 次端到端,补齐 `pyhive_reader.py` 作可选后端。
2. (D-007 / 映射):映射表初版上线后,需采集 100 张真实优惠券文本验证关键词种子集召回率 ≥ 80%。
3. (D-011 / prompt):Stage 2 prompt 的句式骨架需准备 5~8 套,在 `configs/prompts/sft_v1.txt` 旁边维护 `sentence_templates.yaml`。
4. (Coupon `tag_source.distance` 多门店归一):FR-008b 当前默认"取第一条非空记录",若运维反馈精度不够,可改"取最近的 / 取 traffic-rank 第一";本批保留默认。
5. (US5 扩展):`gt / lt / between` op 启用、`avg_prc / distance` 数值化、`shop_lng/lat` 精度等问题,留到下一个 spec。
6. (D-015 / 字典扩量):`extract-dictionary` 在生产 Hive 上的端到端跑通 + 与 `extract-dictionary --source=hive --catalog=...` 配合 SparkHiveReader 的实战验证。
7. (D-016 / 双阈值):根据真实数据调节 `levenshtein_threshold=3 / jaccard_threshold=0.6` 默认值,首次落地可能调整。

---

## Changelog

| Version | Date | Notes |
|---------|------|-------|
| v1 | 2026-06-14 | 初版:基于 v1 spec(7 维味标签)。 |
| **v2** | 2026-06-22 | 重写对齐 spec v2.4:14 个技术决策(D-001 ~ D-014),含 Hive 适配器 / 映射表 / prompt 模板 / CI 脱机 / 性能模型。 |
| **v2.5** | 2026-06-23 | 新增 US4 字典扩量离线 CLI 相关决策 D-015 / D-016 / D-017 / D-018;`extract-dictionary` 离线工具,产物落到 `dict_candidates/` 候选区。 |