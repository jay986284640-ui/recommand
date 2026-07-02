# Feature Specification: 训练数据生成 (兴业 O2O 三品类 SFT 语料)

**Feature Branch**: `training-data-synonym`
**Created**: 2026-06-22
**Status**: v2.5.2 — Config-driven LLM inference + extensible tables
**Input**: User description: "工程的输入是 `tabale_structer.sql` 中的各种表,推荐商品包含美团门店、自拓展门店、优惠券;工程分为三步:(1) 全量标签抽取,从 Hive 抽取 brand/category/taste/occasion 字典;(2) 实际标注数据,LLM 推断 8 维标签,字典约束;(3) 合成 SFT 数据,标签 → 多轮对话语料。"

> **v2.5.2 变更(2026-06-27)**: 3-Stage Pipeline 架构。
> - **Stage 1 (`extract-tags`)**:全量标签抽取。从 Hive 原始字段(Brnd_Nm / Cat_Nm)统计频次,
>   经 Levenshtein + Jaccard 聚类归一,输出 `brands_diff.yaml` / `categories_diff.yaml`
>   供人工 review。合并 dim_dictionary.yaml 中 taste/occasion 等字典全集。
>   产物:`dim_dictionary_snapshot.yaml`(8 维约束集,供 Stage 2 校验)。
> - **Stage 2 (`enrich`)**:实际标注数据。接收 Stage 1 的 `--dict-snapshot`,LLM 推断
>   8 维标签 + name_inference fallback + dict_rejection 可观测。自动导出
>   `dim_dictionary_snapshot.yaml` 到 output-dir。
>   产物:`item_tags.jsonl`(每行 8 维标签 + tag_source + llm_model)。
> - **Stage 3 (`sft`)**:合成 SFT 数据。item_tags → 多轮对话训练语料 + 字典校验
>   + 负样本 + coverage 检查。产物:`sft_corpus.jsonl`。

> **v2.5.1 变更(2026-06-26)**:
> - **A-004 新增**:`_meta.field_contract.<role>.required` 声明每种 role 必须提供的字段,
>   loader 在加载时校验缺失并抛 `TablesConfigError`。
> - **A-005 新增**:**禁隐式 JOIN**。`extract_geo` 移除 `address_row` 参数;
>   自拓展门店的 `Lng`/`Lat` 由上游 SQL JOIN 或 fixture pre-join 提供。
> - **FR-014 新增**:商品名称 fallback 推断。当 `Brnd_Nm` / `Cat_Nm` / `productDesc`
>   为空,或为券抢购规则文案(`满50减10` / `代金券` / `限时抢购` / `核销` /
>   `优惠券`)时,从 `Str_Nm` / `shopName` / `couponName` 按字典值做最长子串匹配推断
>   brand / category / taste / occasion。规则文案识别命中即整体抑制该 item 推断
>   (避免误判)。`LLMEnricher` 把 hints 注入 prompt + LLM 返回 None 时替换;`ConsumableMapper`
>   当 `category=None` 时用 name 推断 category 再查 mapping。可观测:
>   `LLMEnricher.inferred_used_count` + `ConsumableMapper.inferred_count` +
>   `logger.info("name_hint_used", ...)` / `name_inferred_category` 结构化日志。
>
> **v2.5 变更(2026-06-26)**:
> - **A-003 新增**:`configs/tables.yaml` 声明 db / name / role / columns / type / sensitive flags,
>   取代从 `tabale_structer.sql` 解析 DDL 的旧路径。`tabale_structer.sql` 降级为业务参考文档,
>   不再被运行时解析。`--sql <path>` CLI flag 保留为 deprecated alias。
> - **D-015 新增**:OpenAI 兼容 HTTP LLM 客户端(`httpx` POST `/chat/completions`),
>   `--provider openai_compat` 启用。Bearer Token + tenacity 重试 + T097 结构化日志。
> - **SC-002 增强**:字典取值合规率由"硬编码 1.0"改为 `dict_pass_rate = 1 - dict_rejected_count / llm_calls`;
>   reject 计数 / 失败盘 / log 三路可观测。reject 不阻塞主产物(保持向后兼容)。
> - **新增 CLI**:`cmd_split`(md5 bucket 80/10/10 + SC-010 no-leak)、
>   `cmd_verify`(SC-001~SC-010 聚合 + `verify_report.json`)、
>   `cmd_all`(enrich → sft → split → verify 串联)。

**Related**:

- `agent-platform/training-data-synonym/docs/ALIGNMENT_cib_o2o.md` — 业务对齐说明

---

## 3-Stage Pipeline 概览

```
Stage 1: extract-tags          Stage 2: enrich                Stage 3: sft
┌────────────────────┐   ┌────────────────────┐   ┌────────────────────┐
│ 全量标签抽取        │   │ 实际标注数据         │   │ 合成 SFT 数据        │
│                    │   │                    │   │                    │
│ Hive Brnd_Nm/Cat_Nm│   │ Hive 原始数据       │   │ item_tags.jsonl    │
│   频次统计 + 聚类    │──→│ LLM 推断 8 维标签    │──→│ 多轮对话语料生成     │
│ + taste/occasion   │   │ 字典约束 + reject   │   │ 字典校验 + coverage │
│   (dim_dictionary)  │   │ name_inference     │   │ 负样本 + 清洗 + 划分 │
│                    │   │                    │   │                    │
│ → brands_diff.yaml │   │ → item_tags.jsonl   │   │ → sft_corpus.jsonl │
│ → snapshot (约束集) │   │ → snapshot (自动)    │   │ → train/val/test   │
└────────────────────┘   └────────────────────┘   └────────────────────┘
```
- `agent-platform/synonym-dictionary/` — 同义词词表(姊妹工程)
- `specs/001-promo-recommend-agent/spec.md` — LP Agent(下游消费方)
- `tabale_structer.sql` — 业务库 DDL,本工程唯一外部输入

---

## Clarifications

### Session 2026-06-22

- Q: Stage 1 补全 `distance` 维度时,是否调用 LLM 推断?如不调用,数据来源是什么? → A: **不调用 LLM**;`distance` 走"几何计算"专用路径——从源表读取经纬度(美团门店:`o2o_new_gut_shop_base_third.Lng/Lat`;自拓展门店:`o2o_new_gut_shop_address.longitude/latitude` 经 `shopId` join;优惠券:经 `o2o_new_gut_coupon_shop` join 后取关联门店的 lng/lat),用 haversine 公式计算距离再桶化到 `dim_dictionary.distance` 候选;`tag_source.distance` 新增 `geo` 枚举值标识该来源。
- Q: 补全数据是否需要新增"吃 / 喝"的二分维度? → A: **需要**。新增第 8 维 `consumable_type`,候选值 `food | drink | mixed | none`(`mixed` 用于既卖吃又卖喝的便利店 / 综合餐饮,`none` 用于纯非餐券或暂无品类的兜底);该维**默认从 `category` 映射**(咖啡/奶茶/果汁→drink;快餐/中餐/西餐/日料/火锅/烧烤/烘焙→food;便利店/水果/甜品→mixed),`tag_source.consumable_type ∈ {derived | ai | missing}`;`derived` 来源不耗 LLM;若 `category` 缺失或无法映射(如券文案与品类冲突),退回 LLM 推断后落字典。该维同时纳入 SFT 语料的 `params`,op=`eq`,允许用户在对话中表达"我想吃点东西 / 喝点东西"等粗粒度意图;7 维 → **8 维**,所有字段顺序、计数、字典校验同步更新。
- Q: Stage 2 SFT 生成 `params.distance` 时,需要按 shop 经纬度做 haversine 计算桶化吗? → A: **不需要**。SFT 的训练目标是**提参准确性**——模型只需识别"用户是否想按距离排序、距离限制是哪个桶";`distance` 在 SFT 阶段**与 shop / 用户的真实经纬度完全无关**,直接从 `dim_dictionary.distance` 候选(`0-500 / 500-1000 / 1000-3000 / 3000+`)按目标分布抽样,LLM 据此生成与之对齐的自然语言表述(如"近一点的"/"500 米以内"/"远点没关系"等);`order_by=distance` 与 `params.distance` 的非 null 概率独立可配。**shop_lng / shop_lat 仍在 Stage 1 落入 `raw_record`** 作为 LP Agent 运行时(下游消费方)的几何计算原料,但本工程 Stage 2 不读、不用、不校验。FR-008b 简化为"shop_lng/lat 透传抽取";Stage 2 新增 FR-013b 描述 `distance` 字典采样规则。
- Q: `configs/dim_dictionary.yaml` / `brand_dictionary.yaml` 当前手工维护的候选值数量太少,如何从 Hive 真实数据扩字典? → A: 引入 Stage 0 **离线 CLI `extract-dictionary`**:SQL 抽取(美团门店 + 自拓展门店 + 券模板 + 品类映射 4 表)→ 规范化(去括号 / 去 `Co./Ltd./Inc./LLC/GmbH` 后缀 / 中文括号)→ 双阈值聚类(Levenshtein ≤ 3 + char 2-gram Jaccard ≥ 0.6,跨脚本不合并)→ 频次过滤(`frequency_min` 默认 10)→ 输出 `dict_candidates/{brands_raw,brands_normalized,brands_diff,categories_*}.{csv,yaml}`。**产物落在候选区,与权威 yaml 隔离**;人工 review `brands_diff.yaml` 的 `added / existing / removed` 三段,选择性 promote 进 `configs/brand_dictionary.yaml` / `configs/dim_dictionary.yaml` 并 bump `_meta.version` → `dict_version` md5 自动变 → Stage 1 增量重算(FR-006)自动触发。**不进入 Stage 1/2 主流水线**,仅由运营每季度跑一次。

---

## User Scenarios & Testing *(mandatory)*

### User Story 0 — 全量标签抽取 (Stage 1, Priority: P1)

作为 Stage 2 数据标注的约束源,我需要从 Hive 原始数据中抽取全量合法标签值(brand/category/taste/occasion),经频次过滤 + 聚类归一后与人工字典合并,产出 `dim_dictionary_snapshot.yaml`(8 维约束集),防止后续 LLM 推断/语料生成时出现异常品牌、异常分类等数据。

**Why this priority**:没有 Stage 1 约束集,Stage 2 LLM 可能推断出不存在于库中的品牌/分类(幻觉);Stage 3 SFT 语料也可能包含虚假标签值。Stage 1 产出是整个流水线的合法性基线。

**Independent Test**:以 Hive 中 3 张核心表为输入跑 `extract-tags`,期望输出 `brands_diff.yaml`(新增/已有/移除三段) + 合并 dim_dictionary.yaml 中的 taste/occasion 字典全集,产生 `dim_dictionary_snapshot.yaml`。

**Acceptance Scenarios**:
1. **Given** Hive 表 Brnd_Nm 含 `["星巴克", "Starbucks", "星巴克(人民广场)"]` 3 条记录,**When** 跑 Stage 1,**Then** 输出品牌归一化为 `星巴克`(频次 2 + 变体 2),`brands_diff.yaml` 中 `added=[{canonical: 星巴克, frequency: 2, n_variants: 2, aliases: [Starbucks, 星巴克(人民广场)]}]`。
2. **Given** `frequency-min=10` 且某品牌仅出现 3 次,**Then** 该品牌不进入 `added` 段(被过滤),但在 `raw_count/normalized_count/filtered_count` 中体现。

### User Story 1 — 实际标注 8 维标签 (Stage 2, Priority: P1)

作为 LP 提参模型训练管线的上游,我需要把 Hive 中三类业务记录的**原始单据**自动读取下来,由 LLM 推断补全 8 维商业属性标签,推断时以 Stage 1 的 `dim_dictionary_snapshot.yaml` 作为合法性约束(值不在字典中 → dim 置 null + 可观测)。`distance` 与 `consumable_type` 不走 LLM。

**Why this priority**:8 维标签是后续 SFT 语料生成的基础;Stage 1 字典确保标注值合法。

**Independent Test**:以 Hive 3 张核心表 + Stage 1 snapshot 为输入跑 Stage 2,期望输出 `item_tags.jsonl`,300+ 行,`dict_rejected_count` 可观测,`tag_source` 标明每维来源。

**Acceptance Scenarios**:

1. **Given** Hive 表 `recommand_workspace.o2o_new_gut_shop_base_third` 最新分区中一行美团门店记录,缺 `Avg_Prc` 与 `Srvc_Tag`,**When** 运行 Stage 1,**Then** 输出 jsonl 行包含 `category / consumable_type / merchant / avg_prc / distance / age / occasion / taste` 8 维标签,其中由 AI 推断的字段在 `tag_source` 中标记 `ai`,原始字段标记 `raw`,`consumable_type` 由 `category` 映射标记 `derived`,`distance` 由 lng/lat 几何计算标记 `geo`。
2. **Given** Hive 表 `recommand_workspace.o2o_new_gut_coupon_template` 中一行券记录(`couponName="星巴克 30 元代金券"`、`productDesc` 含使用范围),**When** 运行 Stage 1,**Then** `category=咖啡`、`merchant=星巴克` 从 `couponName` / `Brnd_Nm` 提取,`avg_prc` 从 `facePrice` 桶化,缺失维度由 AI 推断并落字典。
3. **Given** 某条记录 AI 推断后某维仍无法确定,**When** 运行 Stage 1,**Then** 该维保留 `null` 并在 `tag_source` 中记为 `missing`,不再强行编造,样本仍写入主输出。
4. **Given** AI 推断的标签值不在 `dim_dictionary.yaml` 候选集合内,**When** 字典校验,**Then** 该维回退为 `null`,记录到 `tag_enrichment_failures.jsonl`,不污染主输出。
5. **Given** 同一 `item_id` 在两次跑批之间未更新(Hive 分区 `etl_dt` 未变 / 行级 md5 一致),**When** 选择增量模式,**Then** 仅对(a) 源表行 md5 变化、(b) 新增分区、或(c) 字典版本变化 的记录重算,其余直接复用上次产物。
6. **Given** Hive 集群不可达 / 权限不足 / 目标分区不存在,**When** Stage 1 启动,**Then** 进程退出非 0 并打印明确诊断("connection refused" / "AccessDenied: table=..." / "partition etl_dt=... not found"),不产生半成品输出。

---

### User Story 2 — 合成 SFT 多轮对话语料 (Stage 3, Priority: P1)

作为 LP Agent **意图识别 + 提参** 微调任务的训练管线,我需要使用 Stage 2 产出的 `item_tags.jsonl` 为每个商品生成**多条多轮对话样本**(单样本最多 5 轮),每条样本带 **ground-truth 8 维 params + intent + order_by**,且 N 条样本合起来要**覆盖该商品所有非 null 维度**(即所有"可被用户提问"的维度都至少被 1 条样本提及)。`dim_dictionary_snapshot.yaml`(Stage 1→Stage 2 自动导出)作为字典校验输入。

**Why this priority**:这是工程的核心交付物,直接决定下游模型 P/R。没有这步,Stage 1 的标签只是中间产物。

**Independent Test**:取 Stage 1 输出 50 个 item(覆盖 3 品类),跑 Stage 2,期望输出 `sft_corpus.jsonl`,样本数 = `Σ count_per_item`,(a) 每条样本的对话轮数 ∈ [1, 5];(b) 同一 item 的样本集合并起来,8 维中所有非 null 维度均出现在至少一条样本的 `params` 中(SC-005 覆盖率);(c) `params` 100% 在 `dim_dictionary.yaml` 字典内(SC-002)。

**Acceptance Scenarios**:

1. **Given** 一个补齐后的美团门店 item(8 维非 null),**When** 设置 `count_per_item=8`,**Then** 产出 8 条样本,样本集的 `params` 合并后命中全部 8 维,无遗漏维度。
2. **Given** 一个优惠券 item(8 维仅 5 维非 null),**When** 生成,**Then** 该 item 的样本集仅需覆盖那 5 维,缺失维度不强行编造。
3. **Given** 用户负样本占比配置为 0.1,**When** 跑 1000 条,**Then** `negative=true` 比例 ∈ [0.08, 0.12](SC-006)。
4. **Given** 一条对话 messages 长度被 LLM 生成为 7 轮,**When** 写盘,**Then** 该样本被截断至 5 轮(首条 `role=user`,末条 `role=user`)并通过校验;或被记为格式失败入 failures。
5. **Given** 模板"我想喝 X"在 100 条样本首句中占比 35%,**When** 多样性降频,**Then** 触发模板降频规则,使其占比 ≤ 20%(SC-007)。
6. **Given** 3 个 item_type 各占源表 50% / 30% / 20%,**When** 跑全量,**Then** 输出 SFT 语料中 `item_type` 分布 ±5% 偏差内保留源分布,可在配置中通过 `type_balance_strategy` 切换为均衡(每类 1/3)。

---

### User Story 3 — 训练 / 验证 / 测试集划分 (Priority: P2)

作为下游训练管线,我需要把 SFT 语料按 **`item_id` hash** 划分到 `train / val / test`(默认 80/10/10),保证同一 item 的所有样本落在同一集合,避免数据泄露。

**Why this priority**:必要的下游入口契约,但实现简单且与核心生成解耦,降级到 P2。

**Independent Test**:跑全量,期望 `train.jsonl` / `val.jsonl` / `test.jsonl` 三文件存在,体量比 80/10/10 ±2%,且任一 `item_id` 不跨集合(SC-009)。

**Acceptance Scenarios**:

1. **Given** 1 万样本(1 千 item × 10 条),**When** 划分,**Then** 三集合 `item_id` 交集为空。
2. **Given** 切分后,**When** 抽 100 样本人工抽检,**Then** `train` 中无 `val` / `test` item 出现。

---

### User Story 4 — 字典扩量离线 CLI (Priority: P3) 🛠️ ops

**Goal**: 作为运营 / 数据工程师,我能从一个离线 CLI 从 Hive 真实数据**抽取全量品牌 + 分类候选**,产出可审核的 diff 报告,人工 promote 进权威 yaml 后,Stage 1 自动增量重算。

**Why this priority**:字典扩量是 off-cycle ops 任务,不影响 Stage 1/2 主流水线;但字典质量直接决定 LP Agent 召回 P/R。每季度跑一次即可,**不阻塞生产 SFT 出货**。

**Independent Test**: `python -m training_data_synonym.cli extract-dictionary --source mock --frequency-min 1` 产出 `dict_candidates/{brands_raw,brands_normalized,categories_*}.csv` + `brands_diff.yaml` / `categories_diff.yaml`,含 `_meta` 字段(raw_count / normalized_count / added_count / removed_count / frequency_min / levenshtein_threshold / jaccard_threshold);`brands_diff.yaml` 含 `added / existing / removed` 三段,排序按 `frequency` 降序;`extract` 函数可独立调用并返回统计 dict。CI 完全脱机可跑(mock fixture),无需 Hive 集群。

**Acceptance Scenarios**:

1. **Given** Hive 中 3 张核心表 + 2 张品类映射表(etl_dt 最新分区),**When** 运行 `extract-dictionary`,**Then** `brands_raw.csv` 含 `name / frequency / sources` 三列;`brands_normalized.csv` 经 Levenshtein + Jaccard 聚类后,同品牌变体合并(如 `味多美10/20/30/50 元代金券` → 1 个 canonical `味多美30元代金券`),`frequency` 加和。
2. **Given** 候选中存在 `星巴克` 和 `Starbucks`(跨 CJK/Latin 脚本),**When** 聚类,**Then** 它们**不合并**(Levenshtein > 3 且 char n-gram 无重叠);2 个独立 cluster。
3. **Given** 当前权威 yaml 中收录 60+ 品牌,**When** 跑完 extract,**Then** `brands_diff.yaml` 的 `added` 段含 Hive 有但 yaml 没有的品牌,`existing` 段含两边都有,`removed` 段含 yaml 有但 Hive 频次低于阈值(或近 N 天未出现)的品牌。
4. **Given** 人工 promote 5 个新品牌进 `configs/brand_dictionary.yaml` 并 bump `_meta.version: 1.0 → 2.0`,**When** 跑 Stage 1,**Then** `dict_version` md5 自动变,触发 Stage 1 增量重算(只重算受影响 item);**无需改任何代码**。
5. **Given** `frequency_min = 10000`(高于实际频次),**When** extract,**Then** 0 个品牌通过过滤;`filtered_count = 0`;`brands_normalized.csv` 为空(仅 header);不报错。
6. **Given** `extract-dictionary` 是**离线工具**,**When** 跑 Stage 1 / Stage 2,**Then** 这两个子命令行为**完全不变**;extract-dictionary **不污染** 主流水线(`item_tags.jsonl` / `sft_corpus.jsonl` 不动)。
7. **Given** extract-dictionary 抽取结果中 `frequency >= 50` 的高频候选,**When** 人工 review,**Then** 这些候选代表**真实业务的核心品牌**,应**优先 promote**;`frequency 1~10` 的候选为**长尾**,可暂缓或丢弃。

---

### Edge Cases

- **SQL 解析异常**:`tabale_structer.sql` 中存在无法解析的非标准 DDL(嵌注释 / 续行) → 跳过该表并写 `parse_warnings.log`,不阻塞;若三类核心表(`o2o_new_gut_shop_base_third` / `o2o_new_gut_shop_base` / `o2o_new_gut_coupon_template`)任一缺失,**直接错误退出**。
- **Hive 不可达 / 权限不足 / 分区不存在**:Stage 1 启动即检查并诊断退出(connection refused / AccessDenied / partition not found / DDL ↔ Hive schema 漂移);不生成半成品;CI 期可通过 `--source=mock` 绕过。
- **Hive 行级数据 schema 漂移**:Hive 真实表的列与 `tabale_structer.sql` DDL 不一致(新增列 / 列改名) → 自动忽略未声明的列、对缺失列填 null 并写 `schema_drift.log`,Stage 1 继续。
- **三品类来源缺失**:某品类 Hive 表为空 → 输出空区段,主流程继续;在 `summary.json` 中给出 `item_type_counts` 与 `WARN: <type> empty`。
- **模型连续不可用**:Stage 1 或 Stage 2 LLM 调用连续失败 > 30 分钟 → 进程退出非 0,已成功的 batch 保留在 jsonl 中可断点续跑。
- **券与门店关联缺失**:`o2o_new_gut_coupon_shop` 找不到券对应的门店 → 该券仍输出,但 `merchant` / `distance` 维度按 `null` 处理,`tag_source.merchant=missing`。
- **字典外候选值**:运营在源表录入了"未知品类"导致 AI 推断出字典外值 → 字典校验拒收该维,记到 enrichment_failures。
- **SFT 对话超长**:LLM 生成超过 5 轮 → 优先尝试截断;若截断后首末 role 约束被破坏,则丢弃整条样本入 failures。
- **同一 item 多次生成不收敛**:同 item 的 8 条样本中 ≥ 5 条 `params` 完全相同 → 触发多样性降频回退到 `temperature += 0.1` 重试一次;仍不收敛则保留并报警。
- **冷启动 item(8 维全 null)**:Stage 1 后某 item 全维仍 null → 该 item 不进入 Stage 2,记录到 `cold_start_items.jsonl`。

---

## Requirements *(mandatory)*

### Functional Requirements

#### A. 数据接入与表分类

- **FR-001**: 系统 MUST 把 `tabale_structer.sql` 当作**只读的 schema 与表角色**输入:解析建表 DDL,提取库名 / 列名 / 类型 / 注释 / `etl_dt` 分区键,并按表名映射到本工程的 3 类商品来源:
  - **美团门店 (item_type=`meituan_shop`)**:`recommand_workspace.o2o_new_gut_shop_base_third`,可借 `recommand_workspace.o2o_new_gut_shop_category_meituan` / `recommand_workspace.o2o_new_gut_shop_category_mapping` 解析品类。
  - **自拓展门店 (item_type=`self_shop`)**:`recommand_workspace.o2o_new_gut_shop_base`,可借 `recommand_workspace.o2o_new_gut_shop_address` / `recommand_workspace.o2o_new_gut_shop_category` 补地址与品类。
  - **优惠券 (item_type=`coupon`)**:`recommand_workspace.o2o_new_gut_coupon_template`,可借 `recommand_workspace.o2o_new_gut_coupon_shop`(关联适用门店)与 `recommand_workspace.o2o_new_gut_discounts_pay`(优惠规则)补充。
- **FR-002**: 系统 MUST 在解析后输出 `tables_meta.json`(每张表的库名 / 列名 / 注释 / 类型 / 分区键 / 推断的本工程角色),便于人工核对与版本对齐。
- **FR-003**: 系统 MUST 在 Stage 1 启动时**从 Hive 读取原始单据行**:
  - **读取范围**可由命令行 / 配置指定:`--etl-dt <YYYYMMDD>`(单分区)、`--etl-dt-range <start>:<end>`(连续区间)、`--latest-n-partitions N`(最近 N 个分区);默认 `latest-n-partitions=1`。
  - **采样**:可加 `--n-items-per-type N` 或 `--ratio R`,默认 demo 模式 `n=100/type`,全量留空。
  - **隐私字段过滤**:Hive 行读入后,在进入 prompt / 输出 jsonl 之前 MUST 去除 `MASTERCARD_CUST_ID` / `Crt_Psn_Id` / `Opr_Psn_Id` / `creator` / `updatePerson` 等敏感列(详见 A-008)。
  - **CI / 开发期降级**:系统 MUST 支持 `--source=mock`,读取本目录 fixture jsonl 代替 Hive(行为与契约不变),用于无 Hive 环境的回归测试。
  - **不修改 Hive**:本工程对 Hive **只读**,绝不写回 / 改 schema / 改分区。

#### B. Stage 1 — AI 8 维标签补全

- **FR-004**: 系统 MUST 在 Stage 1 输出 `item_tags.jsonl`,每行包含:
  ```json
  {
    "item_id": "...",
    "item_type": "meituan_shop | self_shop | coupon",
    "raw_record": { ... 表原始列子集,含 shop_lng / shop_lat(若可得) ... },
    "tags": {
      "category": "...", "consumable_type": "food | drink | mixed | none",
      "merchant": "...", "avg_prc": "...",
      "distance": "...", "age": "...", "occasion": "...", "taste": [...]
    },
    "tag_source": {
      "category":        "raw | ai | missing",
      "consumable_type": "derived | ai | missing",
      "merchant":        "raw | ai | missing",
      "avg_prc":         "raw | ai | missing",
      "distance":        "geo | missing",
      "age":             "raw | ai | missing",
      "occasion":        "raw | ai | missing",
      "taste":           "raw | ai | missing"
    },
    "enriched_at": "ISO8601",
    "llm_model": "..."
  }
  ```
  - **关键约束**:
    - `tag_source.distance` 仅可取 `geo` 或 `missing`,**永不取 `ai`**(distance 不进 LLM 推断,见 FR-008b)。
    - `tag_source.consumable_type` 仅可取 `derived` / `ai` / `missing`,**`derived` 路径不耗 LLM**(从 `category` 映射,见 FR-008c)。
    - 其余 6 维(`category / merchant / avg_prc / age / occasion / taste`)取 `raw | ai | missing`。
- **FR-005**: 系统 MUST 在 Stage 1 对**除 `distance` 与 `consumable_type` 之外的 6 维**(`category / merchant / avg_prc / age / occasion / taste`)按以下顺序产生标签;`distance` 走 FR-008b 的"几何计算"路径,`consumable_type` 走 FR-008c 的"category 映射"路径,二者均不走本 FR:
  1. 优先取**源表显式列**(如门店 `Avg_Prc` → `avg_prc` 桶化)。
  2. 若源列缺失或不可解析,组合**关联表 + 文本字段**(品类映射表、`Cat_Nm`、`Srvc_Tag`、券 `productDesc` 等)调用模型推断。
  3. 推断结果 MUST 落 `dim_dictionary.yaml` 候选集合;不落则降级为 `null`+ source=`missing` 并写 `tag_enrichment_failures.jsonl`。
- **FR-006**: 系统 MUST 支持 Stage 1 的**增量模式**:以 `item_id + raw_record_md5 + dictionary_version + source_partition(etl_dt)` 为指纹,只重算变化项(新分区、变更行、字典升级);状态持久化到 `tag_enrichment_state.parquet`。新分区到达时自动追加,不需要全量重跑。
- **FR-007**: 系统 MUST 在 Stage 1 LLM 调用失败 / 超时(默认 15s)/ 返回非法 JSON 时,**降级为该维 null**,样本主输出仍写入,失败明细写 `tag_enrichment_failures.jsonl`。
- **FR-008**: 系统 MUST 给三类商品**各自的标签来源策略**(可分别配置);**所有三类的 `distance` 维度统一走 FR-008b 几何路径,`consumable_type` 维度统一走 FR-008c 映射路径**,本 FR 描述其余 6 维:
  - 美团门店:`category` 走 meituan 映射表,其余走 `o2o_new_gut_shop_base_third` 原列 + AI。
  - 自拓展门店:全部 6 维以 `Brnd_Nm` / `catId` / `shopName` 为主,人均价靠 `discounts_pay` + 文本推断。
  - 优惠券:`merchant` 取 `couponName` 中的品牌词、`avg_prc` 桶化自 `facePrice`、其余从 `productDesc` / `ruleDescription` 文本推断。
- **FR-008b**: 系统 MUST 对 **`distance` 维度走"透传抽取"路径**,完全不调用 LLM、也不做几何计算:
  1. **shop_lng / shop_lat 抽取**(三类商品各自来源,均为 Hive 直接读取):
     - 美团门店:`recommand_workspace.o2o_new_gut_shop_base_third.Lng / Lat`(同表直读)。
     - 自拓展门店:`recommand_workspace.o2o_new_gut_shop_address.longitude / latitude`(经 `shopId` 与 `o2o_new_gut_shop_base` join)。
     - 优惠券:经 `recommand_workspace.o2o_new_gut_coupon_shop` join 到关联门店,再按上述两规则取 lng/lat(多门店时取第一条非空记录;无门店关联时整体留空)。
  2. **shop_lng / shop_lat 落地**:抽取后写入 `raw_record.shop_lng / shop_lat`(浮点,保留 6 位小数 ≈ 11cm 精度),**仅为下游 LP Agent 运行时复用**;本工程 Stage 2 SFT 生成不消费 lng/lat,不做 haversine 计算。
  3. **Stage 1 `tags.distance`**:始终 `null`(item 级别没有"用户",无法计算真实距离),`tag_source.distance ∈ {geo, missing}` 仅指示"shop_lng/lat 是否成功抽取"——即"下游运行时是否拥有几何计算所需数据":
     - 成功抽取 lng/lat 且数值合法(|lng|≤180 / |lat|≤90 / 非 0 兜底) → `tag_source.distance = geo`。
     - 缺失 / 越界 / 0/0 / NaN / 字符串"null" → `tag_source.distance = missing`。
  4. **绝不取 `ai`**:`distance` 永不进入 LLM 推断流。
  5. **Stage 2 处理**:`params.distance` 与 `order_by=distance` 的产生规则不依赖任何 lng/lat,见 FR-013b。
- **FR-008c**: 系统 MUST 对 **`consumable_type` 维度走"category 映射"专用路径**,默认不调用 LLM:
  1. **映射表**(配置于 `configs/consumable_type_map.yaml`,初始版本):
     - `drink` ← 咖啡 / 奶茶 / 果汁 / 酒水 / 茶饮
     - `food`  ← 快餐 / 中餐 / 西餐 / 日料 / 火锅 / 烧烤 / 烘焙 / 甜品(可咀嚼)
     - `mixed` ← 便利店 / 综合餐饮 / 水果(部分需现榨)
     - `none`  ← 非餐饮兜底(如纯优惠券文案、未识别品类)
  2. **映射成功** → `tags.consumable_type` 取映射值,`tag_source.consumable_type = derived`。
  3. **映射失败**(`category` 为 null,或 `category` 不在映射表内,或券文案明显与 `category` 冲突):降级为 LLM 推断,落字典后 `tag_source.consumable_type = ai`。
  4. **LLM 也失败** → `tags.consumable_type = null`,`tag_source.consumable_type = missing`,记录到 `tag_enrichment_failures.jsonl`。
  5. **三品类应用**:
     - 美团门店 / 自拓展门店:由 `category` 映射;若门店是综合业态(便利店等),取 `mixed`。
     - 优惠券:优先按 `couponName` / `productDesc` 文本判定(出现"咖啡 / 奶茶 / 饮品"等关键词 → `drink`,出现"汉堡 / 炸鸡 / 面 / 烤"等 → `food`),其次回退到关联门店的 `category` 映射。
  6. **op 类型**:`params.consumable_type` op=`eq`,values 单值;允许用户在 SFT 对话中用"我想吃 / 我想喝"等粗粒度意图触发。

#### C. Stage 2 — SFT 多轮对话语料生成

- **FR-009**: 系统 MUST 在 Stage 2 基于 `item_tags.jsonl`(Stage 1 输出)+ 原始单据 (`raw_record`)产出 `sft_corpus.jsonl`,每行 1 个训练样本:
  ```json
  {
    "item_id": "...",
    "item_type": "...",
    "intent": "search_item | use_coupon | pay | view_order | browse",
    "messages": [{"role": "user|assistant", "content": "..."}, ...],
    "params": { 8 维 ParamSpec / null },
    "order_by": "distance | price | rating | time | null",
    "negative": false | true,
    "covered_dims": ["category", "merchant", ...],
    "generated_at": "ISO8601",
    "llm_model": "...",
    "_format_version": "sft_corpus_v2"
  }
  ```
- **FR-010**: 对话轮数 MUST ∈ **[1, 5]**(本版从 4 上调至 5),采样分布默认 `1:10%, 2:20%, 3:35%, 4:25%, 5:10%`,可配。首条 `role=user`,末条不限。
- **FR-011**: 每个 item 的 N 条样本(`count_per_item` 默认 8,可配 5~12)合并后 MUST 覆盖该 item **所有非 null 维度**(SC-005)。系统通过"剩余维度跟踪 + 多次 LLM 调用"实现:
  - 调用 1:LLM 自由生成,记录已覆盖维度集 `C`。
  - 调用 k(k ≥ 2):prompt 注入"未覆盖维度列表" `(8 维非 null) − C`,引导生成包含遗漏维的对话。
  - 若达到 `count_per_item` 仍未覆盖,**强制追加 1 条专门样本**补齐遗漏维(标记 `forced_coverage=true`)。
- **FR-012**: `params` 8 个字段必填(缺失补 null),按固定顺序 `category, consumable_type, merchant, avg_prc, distance, age, occasion, taste` 写出,**op 集合** 沿用 `param_op_types.md` 的 `eq / in / contains / not_in` 4 个;`gt / lt / between` 留接口本批不实现。`consumable_type` 强制 op=`eq`,values ∈ `{food, drink, mixed, none}`。
- **FR-013**: 系统 MUST 支持 **3 种负样本类型**(`negative=true`):
  - `reject`:用户拒绝某条件("不要太辣")。
  - `pivot`:用户切换意图("不看咖啡了,看奶茶")。
  - `unsatisfiable`:无满足项("附近没这种店")。
  - 比例由 `negative_ratio`(默认 0.1)控制,SC-006 ±0.02。
- **FR-013b**: 系统 MUST 在 Stage 2 用**字典采样**(而非几何计算)产生 `params.distance` 与 `order_by`,与商品的 lng/lat 完全解耦:
  1. **`params.distance` 采样**:
     - 每条 SFT 样本以可配概率 `distance_param_ratio`(默认 0.30)决定是否填非 null;否则 `params.distance = null`。
     - 当填非 null 时,从 `dim_dictionary.distance.values`(`0-500 / 500-1000 / 1000-3000 / 3000+`)按目标分布抽样(默认 4 桶各 25%,可配 `distance_bucket_weights`)。
     - 当 `distance` 是反向意图(负样本 `reject`),op=`not_in`,values 为字典子集(如 `["3000+"]` 对应"近一点的,别太远");其余正样本 op=`in`,values 单值或多值。
  2. **`order_by` 采样**:
     - 候选:`distance / price / rating / time / null`;按可配分布默认 `30/20/15/10/25%` 抽样。
     - **耦合约束**:当 `params.distance` 非 null 时,`order_by=distance` 的概率提高至 ≥ 60%(强化"按距离排序"信号);当 `params.distance = null` 时,`order_by=distance` 概率降至 ≤ 5%(避免空相关信号)。
  3. **LLM 生成对齐**:LLM 在生成对话文本时,prompt 必须注入"目标 distance 桶"与"目标 order_by",令自然语言表述与 ground-truth 一致(如 `0-500` → "走路 5 分钟内 / 500 米以内";`3000+` → "稍微远点没关系 / 公交也行");生成结果若反向偏离 ground-truth → 样本入 `sft_failures.jsonl`。
  4. **不消费 lng/lat**:Stage 2 全程不读 `raw_record.shop_lng / shop_lat`,不做 haversine;`distance` 只是字符串桶 ID。
  5. **SFT 训练目标对齐**:本 FR 服务"提参准确性"——模型应能从用户表述中正确抽出"是否按距离排序、距离桶为哪一个",而无需关心 shop / 用户的真实地理位置;真实距离过滤由 LP Agent 运行时(下游)完成。
- **FR-014**: 系统 MUST 在每个 item 内强制**句式多样性**:首句模板(n-gram 提取)的同模板占比 ≤ 20%(SC-007),超阈值时触发 `temperature += 0.1` 重试 1 次或丢弃多余的同模板样本。
- **FR-015**: 系统 MUST 提供 5 个 `intent` 候选:`search_item / use_coupon / pay / view_order / browse`,每类占比下限 3%,长尾触发自动过采样(原样本 + LLM 同义改写 1 次,2x),不平衡度 > 5x 仅报警不强平衡。
- **FR-016**: 系统 MUST 给三类商品**默认 intent 倾向**:
  - 美团门店、自拓展门店:`search_item` 为主,`browse` 次之。
  - 优惠券:`use_coupon` / `pay` 为主,`search_item` 次之。
  - 倾向以 prompt 注入实现,非硬约束。

#### D. 清洗、分布与划分(沿用 v1)

- **FR-017**: 系统 MUST 在 SFT 语料写出后跑 **7 类清洗规则**:
  1. `text_hash` 全相同去重。
  2. `messages[].content` < 10 字 → 删。
  3. 首句模板高频降频。
  4. `params` 8 维全 null → 删。
  5. content 含控制字符 / 连续 ≥ 3 个换行 → 删。
  6. `params` 字段不在 8 维白名单 → 删。
  7. messages 长度 ∉ [1, 5] → 删。
- **FR-018**: 系统 MUST 在清洗后输出 `distribution_report.json`,包含 **8 项分布指标**:`intent 比例 / 8 维 params 非 null 比例 / 4 个 op 比例 / 负样本比例 / 对话轮次分布 / messages 平均长度 / 字典覆盖率 / params 组合多样性`。长尾(<3%)触发过采样,不平衡度 > 5x 报警。`consumable_type` 的 3~4 类值(food/drink/mixed/none)单独纳入分布检查,每类占比目标 ≥ 5%(除 `none` 兜底外)。
- **FR-019**: 系统 MUST 按 `item_id` md5 hash 划分 `train / val / test`(默认 80/10/10),保证同一 `item_id` 不跨集合(SC-009);划分前先校验 0 泄露。
- **FR-020**: 系统 MUST 提供 `--mode=full | incremental` 与 `--stage=enrich | sft | all` 命令行开关,允许只跑某一阶段或全量重算。

#### E. 可观测与降级

- **FR-021**: 全流程 MUST 输出 `summary.json`(各阶段输入/输出条数、AI 调用次数、字典命中率、维度覆盖率、SC 通过情况)与按阶段的 failures jsonl,失败不阻塞主输出。
- **FR-022**: 系统 MUST 在三类产物(`item_tags.jsonl` / `sft_corpus.jsonl` / `train|val|test.jsonl`)上写入 `_format_version` 字段,任何字段集变更必须 bump 版本号并保留兼容期。

#### F. 字典扩量离线 CLI(US4,Stage 0)

- **FR-023**: 系统 MUST 提供离线 CLI `extract-dictionary`,从 Hive 中 3 张核心表(美团门店 / 自拓展门店 / 券模板)+ 2 张品类映射表抽取 `Brnd_Nm` 与 `Cat_Nm`,产出 6 个候选文件:`brands_raw.csv` / `brands_normalized.csv` / `brands_diff.yaml` / `categories_raw.csv` / `categories_normalized.csv` / `categories_diff.yaml`。
- **FR-024**: `extract-dictionary` MUST 使用 Levenshtein 距离 ≤ 阈值(默认 3)+ char 2-gram Jaccard ≥ 阈值(默认 0.6)**双阈值**聚类,避免单指标假阳性;跨脚本(CJK vs Latin)的品牌 MUST NOT 合并。
- **FR-025**: `extract-dictionary` MUST 支持 `frequency_min`(默认 10)过滤长尾候选;`frequency_min` 过高(超过实际频次) MUST NOT 报错,而是输出空集。
- **FR-026**: `extract-dictionary` MUST 输出 `brands_diff.yaml` / `categories_diff.yaml`,含 `_meta` 字段(raw_count / normalized_count / added_count / removed_count / frequency_min / levenshtein_threshold / jaccard_threshold)和 `added / existing / removed` 三段(均按 `frequency` 降序)。
- **FR-027**: `extract-dictionary` MUST 是**离线工具**,不进入 Stage 1/2 主流水线;产物落到 `dict_candidates/` 候选区,**绝不**自动覆盖 `configs/brand_dictionary.yaml` 或 `configs/dim_dictionary.yaml`。
- **FR-028**: 人工 review 后 promote 进权威 yaml 时,MUST bump `_meta.version`(e.g. `1.0 → 2.0`);`dict_version` md5 自动变 → Stage 1 增量重算(FR-006)自动触发,无需改任何代码。

### Key Entities

- **TableMeta**:从 `tabale_structer.sql` 解析出的表元数据(`db / table_name / columns / partition_keys / inferred_role`),作为 Stage 1 启动时的 schema 校验与读 Hive 时的列白名单输入。
- **HiveReadSpec**:Stage 1 的 Hive 拉取规格(`db.table / etl_dt 选择 / 列投影 / 行过滤 / 采样规则`),由命令行 / 配置组合而成,记录到 `summary.json` 便于复盘。
- **RawRecord**:从 Hive 表读出的行级原始数据(已过滤敏感列),字段集随 `item_type` 不同,但都包含 `item_id`、品类相关列、文案列、状态列与 `etl_dt`。
- **ItemTags**:`item_id` + `item_type` + 8 维标签(含 `consumable_type`)+ `tag_source` + 原始记录子集,Stage 1 主输出。
- **TagSource**:8 维每维一个标记;6 维 `raw | ai | missing`,`distance` 仅 `geo | missing`,`consumable_type` 仅 `derived | ai | missing`;标识标签来源,影响后续训练采样策略与可观测面板。
- **SFTSample**:`item_id` + `item_type` + `intent` + `messages`(1~5 轮)+ `params`(8 维 ParamSpec)+ `order_by` + `negative` + `covered_dims` + 元数据。
- **ParamSpec**:`{op, values}`,4 个本批实现 op(`eq / in / contains / not_in`),3 个预留 op(`gt / lt / between`)。
- **EnrichmentFailure** / **SFTFailure**:阶段对应的失败样本,含 `item_id`、`raw_response`、`error_type`、`occurred_at`,用于排查不入主输出。
- **DistributionReport**:分布与平衡的全局报告,8 项指标。
- **EnrichmentState** / **SFTState**:增量模式的指纹表(`item_id + md5 + dictionary_version + generated_at`)。

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**:`tabale_structer.sql` 解析后,`tables_meta.json` 至少覆盖 3 张核心表(美团门店、自拓展门店、优惠券)与 4 张关联表;表角色推断准确率 ≥ 95%(人工抽 20 张校验)。Hive 连通自检(`SHOW PARTITIONS` 任一核心表)成功率 = 100%(失败即诊断退出)。
- **SC-002**:Stage 1 输出的 `item_tags.jsonl` 中,8 维标签**字典内合法率 = 100%**(超出字典或类型不符的值一律落 enrichment_failures);`consumable_type` 取值 100% ∈ `{food, drink, mixed, none}`。
- **SC-003**:Stage 1 完成后,3 类商品的"非 null 标签覆盖率"≥ 95%(即 8 维中至少 7 维非 null 的 item 占比 ≥ 95%);冷启动(全 null)item 占比 ≤ 1%。其中 `consumable_type` `derived` 命中率 ≥ 90%(仅 ≤ 10% 走 LLM 兜底)。
- **SC-004**:Stage 2 输出的 `sft_corpus.jsonl` 100% 可被 `jq -c .` 解析(单行 JSON,无碎片);`params` 字段顺序固定。
- **SC-005**:**对每个非冷启动 item**,其 N 条样本合并后的 `covered_dims` 集合 ⊇ 该 item 全部非 null 标签维度(单 item 覆盖率 = 100%)。全语料层面:任一字典候选值至少被 5 条样本提及。
- **SC-006**:负样本比例 = 配置 `negative_ratio` ±0.02;3 种负样本类型每类 ≥ 20%。
- **SC-007**:任一 item 内,首句高频模板占比 ≤ 20%;全语料层面首句 n-gram top-1 模板占比 ≤ 15%。
- **SC-008**:清洗后留存率 ≥ 85%;< 50% 触发报警并写 `cleaning_failures.jsonl`。
- **SC-009**:`train / val / test` 划分严格按 `item_id` hash,任一 `item_id` 不跨集合(0 泄露);三集合体量比 80/10/10 ±2%。
- **SC-010**:全量端到端跑(1 万 item ≈ 8 万样本)在 LLM 50 req/min、16 并发限速下 < 90 分钟;增量 1% 重跑 < 8 分钟。
- **SC-011**:**业务覆盖**:三类商品(`meituan_shop / self_shop / coupon`)在最终 train 集中的占比与源表分布偏差 ≤ 5%(或按 `type_balance_strategy=balanced` 切换为各 1/3)。
- **SC-012**:**字典抽取**: `extract-dictionary` 跑完后,`brands_diff.yaml` 的 `added` 段含至少 N 个候选(N ≥ frequency_min * #tables),且每个 candidate 含 `frequency / n_variants / sample_aliases` 3 字段;跨脚本品牌(中英文)100% 不合并(SC for FR-024)。
- **SC-013**:**离线 vs 在线隔离**: 跑 `extract-dictionary` 后,Stage 1 / Stage 2 的产物(`item_tags.jsonl` / `sft_corpus.jsonl`) MUST NOT 改变(字节级哈希一致);CLI 是纯只读离线工具。
- **SC-014**:**version bump 触发**: 改 `configs/dim_dictionary.yaml` 的 `_meta.version` 从 `1.0 → 2.0`,Stage 1 启动时 `dict_version` md5 变化 → 增量重算触发(`needs_recompute` 对所有 item 返回 True)。

---

## Assumptions

- (A-001) `tabale_structer.sql` 是本工程**唯一**的业务结构(schema)输入;`recommand_workspace` 与 `cdm` 两个 Hive 库是**唯一**的业务行级数据源。其他源表 / 库若出现,需先把 DDL 补到该文件中并重新对齐。
- (A-002) **客户的原始单据存储在 Hive**(集群由部署方提供 HiveServer2 / Spark Hive Catalog / Kerberos 访问凭据等),本工程对其**只读**;Stage 1 启动时按 `etl_dt` 分区拉取最近 N 个分区的行级数据,然后调用 LLM 推断补全 8 维标签(其中 `distance` 走经纬度几何计算、`consumable_type` 走 category 映射,均不耗 LLM)。Hive 行级数据 schema 以 `tabale_structer.sql` DDL 为权威;漂移时按 Edge Cases 规则处理。
- (A-003) 开发与 CI 期允许使用 `--source=mock` 把 Hive 替换为 `tests/fixtures/*.jsonl` mock 数据(行字段必须与 DDL 列一致);LLM 平台沿用 LP Agent 主 spec 的"大模型平台托管 API",开发期可用 `mock_llm_client.py` 本地启发式,不依赖网络与 GPU。
- (A-004) `dim_dictionary.yaml`(8 维候选值,含 `consumable_type`)、`brand_dictionary.yaml`(品牌词表)、`consumable_type_map.yaml`(category→consumable_type 映射,FR-008c)是字典权威源,由运营维护;任一字典版本变更触发 Stage 1 增量重算。
- (A-005) Stage 1 推断的"AI 标签"与"原始标签"在下游模型训练中权重相同;若下游希望区分权重,可读 `tag_source` 字段自行加权,本工程不强制。
- (A-006) 5 轮对话上限足够覆盖 LP Agent 实际线上场景(用户平均 2~3 轮决定下单);更长对话由后续 spec 扩展。
- (A-007) `op` 类型本批仅实现 4 个(`eq / in / contains / not_in`),`gt / lt / between` 留接口由后续 US 扩展(`avg_prc` / `distance` 数值化时启用)。
- (A-008) 用户隐私字段(`MASTERCARD_CUST_ID`、`Crt_Psn_Id`、`Opr_Psn_Id`、`creator`、`updatePerson` 等)在 Hive 读入后 MUST 在 `raw_record` 字段集与 prompt 中**显式剔除**,绝不进入 jsonl 输出。系统应给出可配置的"敏感列白/黑名单"以便审计。
- (A-009) 三类商品的 `item_id` 命名空间相互隔离(建议 `mt-<Str_Id>` / `self-<shopId>` / `cpn-<couponId>`),避免跨类碰撞。

---

## Dependencies

- **上游 schema**:`tabale_structer.sql`(`/opt/recommand/recommand/tabale_structer.sql`,737 行,10 张表的 DDL),仅作 schema 与表角色识别。
- **上游数据**:**Hive 集群**(库:`recommand_workspace` 与 `cdm`),Stage 1 只读访问;部署方需提供 HiveServer2 / Spark Hive Catalog 连接信息、Kerberos / LDAP 凭据、最少 `SELECT` 权限,以及目标分区(`etl_dt`)可见性。
- **配置**:`configs/dim_dictionary.yaml`(8 维,含 `consumable_type`)、`configs/consumable_type_map.yaml`(category → consumable_type 映射)、`configs/brand_dictionary.yaml`(品牌词典)。
- **姊妹工程**:`agent-platform/synonym-dictionary/`(查询同义词词表;不强依赖)、`agent-platform/data-pipeline/`(纯离线分析,与本工程互不依赖)。
- **下游**:LP Agent 提参 / 意图模型微调管线(`specs/001-promo-recommend-agent/`)直接消费 `train.jsonl` / `val.jsonl` / `test.jsonl`。
- **运行时不依赖**:不强依赖 Spark / embedding 模型 / 外网 LLM;CI 环境允许 `--source=mock` 完全脱机运行。

---

## Out of Scope

- 不做真实用户行为日志的注入(神策埋点 `c10_ods_events_xysh` 仅用作 occasion 推断辅助,不消费长序列)。
- 不做 LP Agent envelope 协议生成,本工程只产 jsonl 样本。
- 不替代手工标注集;本工程主要覆盖"长尾 + 字典覆盖度",val/test 在有真实人工标注集时优先采用真实集。
- 不修改 `tabale_structer.sql` 表结构;Stage 1 是只读的标签**增补**,不改源表。
- 不做模型训练本身(由下游 LP Agent 团队负责)。

---

## Configuration Snapshot (informational)

```yaml
# === Stage 0 字典扩量(US4,离线工具) ===
extract_dictionary:
  source: hive                      # hive | mock
  frequency_min: 10                 # 至少 N 次门店/券出现的品牌才收录
  levenshtein_threshold: 3          # 同品牌变体编辑距离阈值
  jaccard_threshold: 0.6            # 同品牌变体 char 2-gram Jaccard 阈值
  tables:
    brands: ["o2o_new_gut_shop_base_third", "o2o_new_gut_shop_base", "o2o_new_gut_coupon_template"]
    categories: ["o2o_new_gut_shop_category", "o2o_new_gut_shop_category_meituan", "o2o_new_gut_shop_category_mapping"]
  output_dir: ./dict_candidates
  promotion_workflow: |
    1. 人工 review dict_candidates/brands_diff.yaml
    2. 选择 added 段候选,合并进 configs/brand_dictionary.yaml
    3. bump _meta.version (e.g. 1.0 → 2.0)
    4. 提交 PR → merge → dict_version 自动变 → Stage 1 自动增量重算
  cadence: quarterly                # 每季度跑一次即可
```

```yaml
# === Stage 0 字典扩量(US4,离线工具) ===
extract_dictionary:
  source: hive                      # hive | mock
  frequency_min: 10                 # 至少 N 次门店/券出现的品牌才收录
  levenshtein_threshold: 3          # 同品牌变体编辑距离阈值
  jaccard_threshold: 0.6            # 同品牌变体 char 2-gram Jaccard 阈值
  tables:
    brands: ["o2o_new_gut_shop_base_third", "o2o_new_gut_shop_base", "o2o_new_gut_coupon_template"]
    categories: ["o2o_new_gut_shop_category", "o2o_new_gut_shop_category_meituan", "o2o_new_gut_shop_category_mapping"]
  output_dir: ./dict_candidates
  promotion_workflow: |
    1. 人工 review dict_candidates/brands_diff.yaml
    2. 选择 added 段候选,合并进 configs/brand_dictionary.yaml
    3. bump _meta.version (e.g. 1.0 → 2.0)
    4. 提交 PR → merge → dict_version 自动变 → Stage 1 自动增量重算
  cadence: quarterly                # 每季度跑一次即可
```

```yaml
training_data_synonym:
  input:
    sql_path: /opt/recommand/recommand/tabale_structer.sql
    source: hive                         # hive | mock(CI / dev 用)
    hive:
      catalog: spark_hive_catalog        # 由部署方注入;具体连接参数见运维手册
      databases:
        recommand_workspace: recommand_workspace
        cdm: cdm
      etl_dt:
        mode: latest_n                   # single | range | latest_n
        latest_n: 1                      # 默认拉最近 1 个分区
        # range: ["20260601", "20260615"]
        # single: "20260620"
      sample_n_per_type: 100             # demo;全量留空表示读全表
      sensitive_columns_blocklist:
        - MASTERCARD_CUST_ID
        - Crt_Psn_Id
        - Opr_Psn_Id
        - creator
        - updatePerson
    mock:
      fixture_dir: ./tests/fixtures/hive/
    item_types: [meituan_shop, self_shop, coupon]
  enrichment:                            # Stage 1
    enabled: true
    mode: incremental                    # full | incremental
    output_path: ./item_tags.jsonl
    failures_path: ./tag_enrichment_failures.jsonl
    state_path: ./tag_enrichment_state.parquet
    llm:
      model: claude-haiku-4-5
      timeout_seconds: 15
      batch_size: 16
      temperature: 0.3                   # 推断要稳,温度低
    dictionary_path: ./configs/dim_dictionary.yaml
    brand_dictionary_path: ./configs/brand_dictionary.yaml
  sft:                                   # Stage 2
    enabled: true
    input_path: ./item_tags.jsonl
    output_path: ./sft_corpus.jsonl
    failures_path: ./sft_failures.jsonl
    cold_start_path: ./cold_start_items.jsonl
    count_per_item: 8                    # 5~12
    max_message_turns: 5                 # 新版从 4 上调至 5
    turn_distribution: [0.10, 0.20, 0.35, 0.25, 0.10]
    negative_ratio: 0.10
    negative_types: [reject, pivot, unsatisfiable]
    llm:
      model: claude-haiku-4-5
      timeout_seconds: 15
      batch_size: 16
      temperature: 0.7                   # 多样性要高
    coverage:
      forced_coverage: true              # FR-011 强制覆盖
      template_repeat_limit: 0.20        # SC-007
    distance_sampling:                   # FR-013b — 与 lng/lat 解耦的字典采样
      distance_param_ratio: 0.30         # 每条样本 30% 概率填非 null distance
      distance_bucket_weights:           # 4 桶目标分布(归一化前)
        "0-500":     0.25
        "500-1000":  0.25
        "1000-3000": 0.25
        "3000+":     0.25
      order_by_distribution:             # `order_by` 候选 5 类分布
        distance: 0.30
        price:    0.20
        rating:   0.15
        time:     0.10
        null:     0.25
      order_by_distance_when_param_present: 0.60   # 耦合下限
      order_by_distance_when_param_null:    0.05   # 耦合上限
  cleaning:
    enabled: true
    min_message_length: 10
    min_retention_rate: 0.85
    alert_retention_rate: 0.50
  distribution:
    enabled: true
    report_path: ./distribution_report.json
    intent_min_ratio: 0.03
    param_min_ratio: 0.05
    op_not_in_min_ratio: 0.03
  split:
    enabled: true
    train_ratio: 0.8
    val_ratio: 0.1
    test_ratio: 0.1
    train_path: ./train.jsonl
    val_path: ./val.jsonl
    test_path: ./test.jsonl
  type_balance_strategy: source          # source | balanced
```

---

## Changelog

| Version | Date | Author | Notes |
|---------|------|--------|-------|
| v1 | 2026-06-14 | (initial) | 原始 spec:输入为 `item_features_ai.jsonl`(来自 001-data-pipeline-enhancement),7 维口味标签(味/场/材/域/人/情/就),对话 1~4 轮。 |
| v2 | 2026-06-22 | 修订 | 输入改为 `tabale_structer.sql` 直接读三类源表(美团门店 / 自拓展门店 / 优惠券);新增 Stage 1 AI 标签补全;7 维改为商业属性(category/merchant/avg_prc/distance/age/occasion/taste);对话上限改为 **5 轮**;新增"全维度覆盖"约束(SC-005)。 |
| v2.1 | 2026-06-22 | 修订 | **澄清数据源**:客户原始单据存储在 **Hive**(`recommand_workspace` / `cdm` 两库);Stage 1 直接从 Hive 按 `etl_dt` 分区拉取行级数据,再调用 LLM 推断补全;`tabale_structer.sql` 仅作 schema 输入。新增 Hive 连接/分区选择/敏感列过滤/`--source=mock` 降级 等 FR;A-002 / Edge Cases / Dependencies / Configuration Snapshot 同步更新。 |
| v2.2 | 2026-06-22 | 修订 | **`distance` 改走经纬度几何计算**:不进 LLM 推断,从源表读取 lng/lat(美团:`o2o_new_gut_shop_base_third.Lng/Lat`;自拓展:`o2o_new_gut_shop_address` join;券:`o2o_new_gut_coupon_shop` join 到门店),haversine 计算后桶化。新增 FR-008b、`tag_source.distance ∈ {geo, missing}`、shop_lng/lat 落 `raw_record`、相关 Edge Cases。FR-005 调整为只覆盖剩余 6 维。 |
| v2.3 | 2026-06-22 | 修订 | **新增第 8 维 `consumable_type`**(`food / drink / mixed / none`),从 `category` 映射,默认不耗 LLM;新增 FR-008c、`tag_source.consumable_type ∈ {derived, ai, missing}`、`configs/consumable_type_map.yaml` 字典;7 维 → 8 维 跨章节同步(FR-004/005/008/011/012/017/018、SC-002/003、Key Entities、Assumptions、Dependencies);`params` 字段顺序前移至 `category, consumable_type, ...`;Acceptance Scenarios 与 Configuration Snapshot 同步刷新。 |
| v2.4 | 2026-06-22 | 修订(本版) | **SFT 提参聚焦,Stage 2 与经纬度解耦**:用户澄清 SFT 训练目标 = 提参准确性,只需识别"是否按距离排序、距离桶值",不关心几何数据。FR-008b 简化为"shop_lng/lat 透传抽取(留给下游 LP Agent 运行时)";Stage 2 新增 FR-013b 描述 `params.distance` 与 `order_by` 的**字典采样规则**(distance_param_ratio / bucket weights / order_by 与 distance 的耦合概率 / LLM 对齐表述)。Edge Cases 的"shop lng/lat 缺失"现仅影响 `tag_source.distance` 标记,与 SFT 生成无关。 |
| **v2.5** | 2026-06-23 | 修订(本版) | **新增 US4 字典扩量离线 CLI `extract-dictionary`**(Stage 0):SQL 抽取 3 表 `Brnd_Nm` + 2 品类表 `Cat_Nm` → 双阈值聚类(Levenshtein ≤ 3 + Jaccard ≥ 0.6,跨脚本不合并)→ 频次过滤(`frequency_min` 默认 10)→ 输出 `dict_candidates/` 候选文件;人工 PR review `brands_diff.yaml` 后 promote 进权威 yaml + bump `_meta.version` → `dict_version` 自动变 → Stage 1 增量重算(FR-006)自动触发。新增 FR-023~FR-028 + SC-012~SC-014;`extract-dictionary` 完全离线、不污染 Stage 1/2 主流水线。 |
