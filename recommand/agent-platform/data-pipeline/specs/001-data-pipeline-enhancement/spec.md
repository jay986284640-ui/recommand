# Spec: 数据处理管线增强 (Data Pipeline Enhancement)

**Branch**: `001-data-pipeline-enhancement` | **Date**: 2026-06-14 | **Status**: Draft
**Project**: `agent-platform/data-pipeline/`
**Related**: [001-promo-recommend-agent](../../../../specs/001-promo-recommend-agent/spec.md) — LP Agent 的离线数据来源

---

## 1. 概述

在现有 4 步管线(稽核 → 清洗 → 标准化 → 特征提取)基础上,新增 3 个能力:
1. **AI 辅助特征增强** — 用 LLM 从 item_title / item_description 抽取 7 个维度的标签(含就餐人数)
2. **JSONL 输出** — 特征提取算子统一输出 jsonl,方便下游 ES / LLM 消费
3. **实时特征处理** — Kafka → Spark Structured Streaming 微批(3~5 分钟),更新 user_interaction_history / user_features

不动现有代码,只追加新模块与配置开关。

---

## 2. 背景与目标

### 2.1 背景

当前管线是纯离线批处理,产出 5 类特征 parquet。LP Agent 消费时遇到两个痛点:
- **冷启动 / 弱信号品类**:`item_features` 仅有显式 `category` 字段,无法区分"咖啡"是早餐还是下午茶、用户更倾向什么口味。
- **特征更新滞后**:用户刚发生一笔买单,LP Agent 要等下次离线批跑完(几小时后)才能看到新的 user_interaction_history;实时推荐"再看看相关的"做不到。

### 2.2 目标

- (G1) 离线 **AI 特征增强** 给 `item_features` 增加 7 维标签(口味/场景/食材/地域/人群/情绪/**就餐人数**)
- (G2) 5 类特征产出改为 **JSONL**,对齐 LP Agent 现有 envelope 协议
- (G3) **微批流式** 增量更新 user_interaction_history + user_features,延迟 ≤ 5 分钟

### 2.3 非目标

- 不做实时推荐(那是 LP Agent 的运行时职责)
- 不做在线学习模型训练
- 不动 LP Agent 的 envelope 协议
- 不动 4 步管线的清洗 / 标准化逻辑

---

## 3. 现有 4 步管线回顾(基线)

| 步骤 | 输入 | 输出 | 模块 |
|------|------|------|------|
| 1. 数据质量稽核 | 中间格式 | `audit_report.json` | `audit/` |
| 2. 数据清洗 | 中间格式 | 清洗后 users/items/interactions | `cleaning/` |
| 3. 数据标准化 | 清洗数据 | 标准化数据 | `normalization/` |
| 4. 特征提取 | 标准化数据 | 5 类 parquet | `feature_extraction/` |

5 类产出:`item_features` / `user_features` / `user_interaction_history` / `co_purchase` / `impression_log`(stub)

---

## 4. 用户故事

### US1 — AI 辅助特征增强(P1,核心)

> 作为 LP Agent,我想知道"这杯星巴克拿铁"是"咖啡"+"早餐场景"+"奶咖"+"白领人群"+"提神情绪"+"1 人份",以便做更精准的语义召回和重排(尤其"双人餐/家庭餐/聚会餐"的差异化推荐)。

**独立可测试**:给一条 item_meta,跑 `ai_enhance.py` 后能输出 6 维标签 jsonl,字段齐全且可被 ES 索引。

**场景**:
- 新商品上架 → 全量跑一次,产出 7 维标签(含就餐人数)
- 商品 description 改了 → 增量跑,只重算 md5 变化的
- LLM 报错 → 降级为空标签数组,不阻塞主流程
- 自助餐 / 套餐类商品 → LLM 推断支持的就餐人数(1 / 2 / 3-4 / 5-8 / 9+);单人饮品通常为 1

### US2 — JSONL 输出格式(P1,基础设施)

> 作为下游消费者(ES / LLM / 数据分析师),我希望直接 `jq` / `pd.read_json` 读特征文件,而不用先转 parquet。

**独立可测试**:任何一类特征 writer 产出的 `.jsonl` 文件,每行是一个有效 JSON,字段齐全。

**场景**:
- `feature_extraction/run_*.py` 跑完 → `features/*.jsonl`
- `item_features` 的一行 = 一个商品 + 6 维标签 + 统计特征
- jsonl 文件可被 `head -1` / `jq` 直接消费

### US3 — 实时特征处理(P2,扩展)

> 作为 LP Agent,用户在 2 分钟前刚买了一杯瑞幸,我想在这次对话里立刻推荐"咖啡相关"。

**独立可测试**:把 1 条 Kafka 事件塞进 `topic=user_events`,3-5 分钟后 `user_interaction_history.jsonl` 多出一条 entry,`user_features.jsonl` 计数 +1。

**场景**:
- 用户下单 → LP 主流程发 Kafka 事件(user_id, item_id, action, ts)
- 流任务每 3-5 分钟批一次 → 更新 user_interaction_history(append)+ user_features(upsert)
- Kafka 积压 / 离线任务冲突 → 流式任务独立 checkpoint,不互相阻塞

---

## 5. 功能性需求(FR)

### FR-001 AI 特征增强 — 7 维标签抽取

LLM 提示词必须固定模板,固定输出 7 个字段(见 §6.1 schema),温度 ≤ 0.3 保证稳定性。
- 输入:items 表的 (item_id, item_title, item_description, content_type)
- 输出:`item_features_ai.jsonl` 中追加 7 维字段,含 `party_size`(就餐人数)
- 批量调用,batch_size 默认 50(可配)
- 单条失败 → 记入 `ai_enhance_failures.jsonl`,继续处理其他

### FR-001a AI 特征增强 — 就餐人数(party_size)推断

根据 `item_title` / `item_description` / `item_denomination` / `item_threshold` 等可观测字段,
推断该商品**适合几人就餐**。

- 推断目标:从字典 {`1` / `2` / `3-4` / `5-8` / `9+`} 中选 1 个最匹配的桶
- 推断依据(可被 LLM 自由组合):
  - title 含"单人/一杯/一瓶"→ `1`
  - title 含"双人/情侣/二人"→ `2`
  - title 含"家庭/3-4 人/四人/小聚"→ `3-4`
  - title 含"聚会/多人/团餐/8 人"→ `5-8`
  - title 含"婚宴/年会/大型"→ `9+`
  - 套餐类(双人套餐 / 家庭套餐)→ 看套餐名
  - 自助餐 / 单点菜:看单位(按位 / 按桌 / 按斤)
- 输出字段:`ai_tags.party_size`(string,5 个桶之一)
- 推断不确定 → 输出最可能的桶(不输出空);确实无法判断(如 description 缺失) → 输出空字符串
- 推断失败(LLM 报错)→ 与 FR-003 同样的降级路径

### FR-001b AI 特征增强 — 字典版本化

7 维字典(味/场/材/域/人/情/就)存放在 `configs/tag_dictionary.yaml`,支持运营热更新;
prompt 模板动态加载字典,字典变更不需要改 prompt。

### FR-002 AI 特征增强 — 全量 / 增量模式

`ai_enhance.py --mode=full|incremental`
- **full**:对 items 表所有行重算,覆盖 `ai_enhance_state` 表
- **incremental**:用 item_title+item_description 的 md5 指纹,只跑新增/修改行
- 状态持久化:写入 `ai_enhance_state` parquet(下次增量比对)

### FR-003 AI 特征增强 — 降级

- LLM 调用失败 / 超时(>10s) → 该 batch 写空标签 + 记告警
- LLM 返回非 JSON → 解析失败 → 记 `ai_enhance_failures.jsonl`
- 全程**不阻塞**主流程:`ai_enhance.py` 是独立 run 脚本

### FR-004 JSONL 写入

- 5 类特征 writer(`item_features` / `user_features` / `user_interaction_history` / `co_purchase` / `impression_log`)统一输出 **jsonl**(每行一个 JSON 对象)
- Spark 用 `.write.text()` + 自定义 UDF 序列化(或换 `pandas` 收集小结果集再写)
- 字段顺序:业务字段在前(`item_id` / `user_id`),衍生字段在后
- jsonl 末尾不留 `\n` 之外的多余字符

### FR-005 JSONL 兼容性

- 单行可被 `python -c "import json,sys; json.loads(sys.stdin.read())"` 解析
- 不出现 nan / inf 浮点;None 输出 `null`
- 嵌套结构(struct / array)用标准 JSON 表达
- 字段名 snake_case;**不**含 tab / 控制字符

### FR-006 实时流 — Kafka 消费

- Spark Structured Streaming job,订阅 `topic=user_events`(可配)
- Kafka message schema: `{user_id, item_id, action, timestamp, content_type?, store_id?, amount?}` (JSON)
- 起始 offset:`latest`(生产) / `earliest`(回填测试,可配)
- consumer group:`data-pipeline-realtime-v1`

### FR-007 实时流 — 微批窗口

- Spark trigger:`processingTime='3 minutes'`(可配 1~10 分钟,默认 3)
- 每个微批:从 Kafka 取 0~N 条事件 → 去重(同一 user_id+item_id+timestamp 唯一)→ 写
- 长时间无事件(空批)→ 跳过本次写,无副作用

### FR-008 实时流 — 写目标

- `user_interaction_history.jsonl`:append 模式,**不**重写历史(由流任务写增量;离线批写全量)
- `user_features.jsonl`:upsert(按 user_id),`interaction_count` 累加、`last_seen_ts` 取大
- 写入用 Spark foreachBatch + 临时 parquet 缓冲(避免 jsonl 增量并发写)

### FR-009 实时流 — 状态与容错

- Spark checkpoint 目录:`./checkpoints/streaming/`
- 重启时从上次 commit 的 offset 续读
- Kafka offset 与输出写在同一个微批里(atomic batch)

### FR-010 实时流 — 资源隔离

- 流任务用**独立 SparkSession**(`local[2]`,内存 2g),不与离线批抢资源
- 与离线 `run_pipeline.py` 同时跑:测试中不互相阻塞(IO / 网络隔离)

---

## 6. 数据契约

### 6.1 AI 增强后的 item_features 字段约定

```json
{
  "item_id": "item-123",
  "content_type": "meituan_coupon",
  "item_title": "星巴克 拿铁 中杯",
  "item_description": "经典浓缩咖啡 + 蒸奶,口感顺滑",
  "category": "咖啡",
  "interaction_count": 234,
  "buyer_count": 180,
  "is_cold": false,
  "ai_tags": {
    "taste": ["微苦", "奶香"],
    "occasion": ["早餐", "下午茶", "提神"],
    "ingredient": ["牛奶", "咖啡豆"],
    "cuisine_region": ["西式"],
    "target_audience": ["白领", "学生"],
    "emotion_value": ["提神", "治愈"],
    "party_size": "1"
  },
  "ai_enhanced_at": "2026-06-14T10:00:00Z",
  "ai_model": "claude-haiku-4-5"
}
```

7 维标签的取值字典(允许值集合,设计时收敛):

| 维度 | 字段 | 候选值 | 类型 |
|------|------|--------|------|
| 口味 | `taste` | 辣 / 甜 / 咸 / 酸 / 苦 / 鲜 / 清淡 / 奶香 / 麻 | array |
| 场景 | `occasion` | 早餐 / 午餐 / 晚餐 / 夜宵 / 下午茶 / 聚会 / 一人食 / 商务 | array |
| 食材 | `ingredient` | 牛 / 鸡 / 鱼 / 虾 / 蔬菜 / 米 / 面 / 奶 / 蛋 / 豆制品 | array |
| 地域菜系 | `cuisine_region` | 川 / 粤 / 鲁 / 苏 / 浙 / 闽 / 湘 / 徽 / 日 / 韩 / 泰 / 西式 / 中式 / 东南亚 | array |
| 人群 | `target_audience` | 学生 / 白领 / 家庭 / 情侣 / 健身 / 老人 / 儿童 | array |
| 情绪价值 | `emotion_value` | 解压 / 治愈 / 活力 / 暖心 / 清爽 / 提神 / 怀旧 | array |
| **就餐人数** | `party_size` | `1` / `2` / `3-4` / `5-8` / `9+` | **string(单值)** |

> 注:前 6 维允许多标签并存(如"咖啡"既是"早餐"又是"下午茶"),`party_size` 是单值字符串,
> 因为一个商品虽然可被多类人群消费,但其"份量"是固有属性(如一份双人套餐只能选 `2`)。

### 6.2 Kafka 事件 schema (`user_events` topic)

```json
{
  "event_id": "uuid-v4",
  "user_id": "u-123",
  "item_id": "item-456",
  "action": "buy",  // buy / use / pay / view
  "timestamp": 1718352000,
  "content_type": "meituan_coupon",
  "store_id": "s-789",
  "amount": 25.0
}
```

Partition key = `user_id`(保证同一用户事件顺序)

---

## 7. 成功标准(SC)

| ID | 标准 | 验证方式 |
|----|------|----------|
| SC-001 | AI 增强对 100 个 item 的全量跑批 < 10 分钟(LLM 限速 50 req/min) | `time python run_ai_enhance.py --mode=full` |
| SC-002 | 增量模式:1% 增量数据重跑,耗时 < 1 分钟(对 10 万 item 基线) | fixture 1 万 item + 100 增量 |
| SC-003 | AI 标签 JSON 解析成功率 ≥ 99%(LLM 偶发格式错误被 catch) | 统计 `ai_enhance_failures.jsonl` 行数 / 总数 |
| SC-004 | jsonl 文件 100% 可被 `jq -c .` 解析 | 写后用 `for line in features/*.jsonl; do jq -c . < $line; done` |
| SC-005 | 5 类特征 writer 都产出 jsonl(无 parquet 残留) | 跑完 `feature_extraction` 后 `find features -name "*.parquet"` 为空 |
| SC-006 | 流任务单微批延迟 P95 ≤ 30s(空批) / ≤ 3min(满载 1000 事件) | Spark metrics UI |
| SC-007 | Kafka offset 不漏不重:Kafka topic 中间断网 1 分钟后恢复,流任务不丢事件 | chaos test |
| SC-008 | 流任务与离线批同时跑,流任务不饿死(独立 SparkSession) | 并发跑 + Prometheus 监控 |
| SC-009 | 流任务重启后从 checkpoint 续读,user_features 计数无重复 +1 | kill -9 后重启,核对计数 |
| SC-010 | `party_size` 字段填充率 ≥ 95%(description 缺失的极少量商品允许空) | 统计 `party_size == "" or null` 的占比 |
| SC-011 | `party_size` 字段全部在 5 个桶(`1`/`2`/`3-4`/`5-8`/`9+`)之内(字典外值视为解析失败) | 字典校验 |
| SC-012 | `party_size` 推断 P95 延迟 ≤ 整体 LLM 调用延迟 + 5%(增加 1 个字段对 prompt 影响极小) | 性能回归 |

---

## 8. 假设与依赖

- (A-001) LLM 平台:沿用 001 spec 的"大模型平台托管 API",可批量调用
- (A-002) Kafka 集群:LP 主流程已部署 Kafka 或可由客户大数据平台提供
- (A-003) 实时流任务的 SparkSession 与离线批共享 checkpoint 目录(分离子目录)
- (A-004) jsonl 字段名延续 001 spec 的 snake_case 约定
- (A-005) AI 标签字典可在生产前调整;LLM prompt 中明确"输出必须为这字典的子集"
- (A-006) `party_size` 推断假设 LLM 能从 `item_title` 的"双人套餐/家庭装/单人份"等措辞 + 描述中的份量/单位信息做出合理判断;若两者都缺,允许空字符串
- (A-007) `party_size` 不考虑商品的"可拆分性"(一个双人套餐可被 1 人吃完但仍标 `2`),仅以"原生份量"为依据

---

## 9. 边界与负面场景

| 场景 | 行为 |
|------|------|
| 商品 description 为空 | AI 标签全部为空数组,`ai_enhanced_at` 仍写入 |
| LLM 整体不可用(>30 分钟) | `ai_enhance.py` 退出非 0;`item_features` 维持上版本 |
| Kafka topic 突然下线 | 流任务 retry;checkpoint 保留 offset;恢复后不丢 |
| jsonl 文件被外部进程改写 | 流任务用临时文件 + 原子 rename,避免半写 |
| 同一事件被 Kafka producer 重发 | 用 event_id 去重(flink-style 状态) |

---

## 10. 配置开关

YAML 增加 3 个顶级段:

```yaml
ai_enhance:
  enabled: true
  mode: incremental  # full | incremental
  batch_size: 50
  llm_timeout_seconds: 10
  llm_temperature: 0.2
  model: claude-haiku-4-5
  prompt_template: configs/prompts/ai_enhance_v1.txt
  state_path: ./ai_enhance_state.parquet
  failures_path: ./ai_enhance_failures.jsonl

output_format: jsonl  # jsonl | parquet(jsonl 为本增强默认)

streaming:
  enabled: true
  kafka_bootstrap: kafka-1:9092,kafka-2:9092
  topic: user_events
  consumer_group: data-pipeline-realtime-v1
  trigger_interval: 3 minutes
  starting_offset: latest
  checkpoint_dir: ./checkpoints/streaming
  output_dir: ./streaming_output
  app_name: DataPipelineRealtime
  spark_master: local[2]
  spark_memory: 2g
```

---

## 11. 待澄清

(暂无阻塞性问题;新增 3 个功能不与现有 FR 冲突。)

---

## 12. 相关文档

- 001 spec:`specs/001-promo-recommend-agent/spec.md`
- 4 步管线 README:`agent-platform/data-pipeline/README.md`
- 特征字段设计:001 spec data-model.md
