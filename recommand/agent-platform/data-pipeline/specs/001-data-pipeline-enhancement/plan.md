# Implementation Plan: 数据处理管线增强

**Branch**: `001-data-pipeline-enhancement` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

> 本 plan 在现有 4 步管线(`agent-platform/data-pipeline/`)基础上,设计 3 个新能力的实现路径。
> 现有代码**不动**,只追加新模块(ai_enhance / streaming)+ 改 writer 输出格式。

---

## Summary

3 个能力的总体接入形态:

| 能力 | 接入位置 | 触发方式 | 产出来源 |
|------|----------|----------|----------|
| AI 特征增强 | `feature_extraction/` 新增 `ai_enhance/` 子模块 | 独立 `run_ai_enhance.py` 脚本,手动 / 调度 | item_title/description → LLM → **7 维标签(含就餐人数)** |
| JSONL 输出 | `feature_extraction/writer.py` + 5 个 writer | 默认 | 改写格式,字段不变 |
| 实时特征处理 | `streaming/` 新模块 | 独立 `run_streaming.py` 脚本,常驻 | Kafka → 微批 → user_*_*.jsonl |

---

## Technical Context

**Language/Version**: Python 3.11+(沿用)
**Spark**: 3.5.3(沿用)
**新增依赖**:
- LLM SDK(Anthropic / OpenAI,具体看大模型平台)
- `pyspark` 已含 `spark-sql-kafka`(`--packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3` 启动时拉)
- `jsonschema`(可选,用于验证 Kafka 消息)

**Storage**:
- AI 增强状态:`./ai_enhance_state.parquet`
- AI 失败日志:`./ai_enhance_failures.jsonl`
- 流式 checkpoint:`./checkpoints/streaming/`
- 流式输出:`./streaming_output/`

**Testing**:
- pytest + SparkSession 单元测试(沿用现有 conftest)
- 实时流测试:`pytest tests/streaming/test_*.py` 用 `pyspark.sql.streaming.test` 模拟 Kafka
- 集成测试:用 Kafka Embedded / Testcontainers(可选)

**Target Platform**: Linux 容器(沿用);流任务 K8s Deployment(常驻)+ Liveness Probe / Readiness Probe
**Project Type**: 在现有 `data-pipeline/` 中追加 2 个顶层子包(`ai_enhance/` + `streaming/`),并改 `feature_extraction/` 的 writer 格式

**Performance Goals**:
- AI 增强:100 items < 10 min(LLM 50 req/min 限速)
- 增量:1% 增量 < 1 min(对 10w 基线)
- 流:单微批 P95 ≤ 30s(空批)/ ≤ 3min(满载 1000 事件)

**Constraints**:
- 不动现有 4 步管线的清洗 / 标准化 / 稽核逻辑
- 不动 LP Agent envelope 协议
- LLM 调用必须可降级(失败 → 空标签 + 告警,不阻塞主流程)
- jsonl 输出必须 100% 可被 `jq -c .` 解析

**Scale/Scope**:
- item 总量:1w~10w SKU(沿用)
- 日活:客户场景的 DAU(等 001 spec 收敛)
- Kafka 事件量:预估 1k~10k/min 峰值

---

## Constitution Check

### I. Library-First ✅
- `ai_enhance/` / `streaming/` 都是新顶层子包,独立可测
- 与现有 4 步管线**不交叉依赖**(通过 parquet / kafka 解耦)

### II. CLI Interface ✅
- `run_ai_enhance.py --mode=full|incremental --batch-size=N`
- `run_streaming.py --config=...`
- 与 `run_*.py` 一致

### III. Test-First (NON-NEGOTIABLE) ✅
- 3 个能力都有独立可测试段(US1 / US2 / US3)
- tasks.md 会**先**写测试任务,再写实现

### IV. Integration Testing ✅
- AI 增强:用 mock-llm 服务(类似 mock-llm in 001 quickstart)
- 流式:用 Testcontainers Kafka 或内存 mock Spark Streaming
- jsonl:在 tests 里加 `tests/feature_extraction/test_jsonl_output.py`

### V. Observability, Versioning, Simplicity ✅
- AI 增强:失败率 / 平均延迟 / 标签字典覆盖率(指标)
- 流式:Spark metrics UI + Kafka lag 监控 + checkpoint 健康
- jsonl 格式版本化:每行可加 `_format_version: "jsonl-v1"`
- Simplicity:不引入新的中间件(沿用 Kafka / Spark / LLM SDK)

**Constitution Check 状态:通过**。Complexity Tracking 表空。

---

## Project Structure(增量)

```
agent-platform/data-pipeline/
├── feature_extraction/                       # 现有,扩展
│   ├── __init__.py
│   ├── pipeline.py                            # 改:增加 output_format
│   ├── item_features.py                       # 不动逻辑;writer 改 jsonl
│   ├── user_features.py
│   ├── user_interaction_history.py
│   ├── co_purchase.py
│   ├── impression_log.py
│   ├── writer.py                              # 现有 feature_writer 改:支持 jsonl
│   └── ai_enhance/                            # 新增子模块
│       ├── __init__.py
│       ├── llm_client.py                      # LLM 客户端(批量 + 重试 + 降级)
│       ├── prompt.py                          # 7 维 prompt 模板(含 party_size)
│       ├── tag_schema.py                      # 7 维字典 + jsonschema
│       ├── party_size.py                      # 就餐人数推断(规则 + LLM 融合)
│       ├── enhancer.py                        # 全量 / 增量调度
│       ├── state.py                           # 增量指纹状态持久化
│       └── pipeline.py                        # AI 增强 Pipeline
├── streaming/                                 # 新增子包
│   ├── __init__.py
│   ├── kafka_consumer.py                      # Kafka source 封装
│   ├── dedup.py                               # event_id 去重
│   ├── interaction_updater.py                 # 写 user_interaction_history
│   ├── user_feature_updater.py                # 写 user_features (upsert)
│   ├── pipeline.py                            # 流 Pipeline 编排
│   └── checkpoint.py                          # checkpoint 健康检查
├── writers/
│   └── jsonl_writer.py                        # 新增:jsonl 写出
├── configs/
│   ├── datasets/*.yaml                        # 现有
│   └── prompts/
│       └── ai_enhance_v1.txt                  # 新增:7 维 prompt(含 party_size)
├── tests/
│   ├── feature_extraction/
│   │   ├── test_jsonl_output.py               # 新增
│   │   ├── test_extractors.py                 # 现有
│   │   └── ai_enhance/                        # 新增
│   │       ├── test_prompt.py
│   │       ├── test_enhancer.py
│   │       ├── test_state.py
│   │       ├── test_tag_schema.py
│   │       └── test_party_size.py             # party_size 推断专项测试
│   └── streaming/                             # 新增
│       ├── test_kafka_consumer.py
│       ├── test_dedup.py
│       ├── test_interaction_updater.py
│       ├── test_user_feature_updater.py
│       └── test_pipeline.py
├── run_ai_enhance.py                          # 新增入口
├── run_streaming.py                           # 新增入口
└── run_pipeline.py                            # 现有,加 --skip-ai-enhance
```

---

## Phase 0 — 关键技术决策(research.md)

| ID | 决策点 | 选项 | 推荐 |
|----|--------|------|------|
| D-001 | LLM 批量策略 | 串行 / batch API / 并发池 | **并发池(asyncio + semaphore=10)**:易实现,无需等平台批 API |
| D-002 | LLM 客户端 | 官方 SDK / HTTP 直连 / LangChain | **官方 SDK**:001 spec 已锁定,沿用 |
| D-003 | AI 标签存储 | 直接合并到 item_features / 独立 ai_features 表 | **独立文件**(`item_features_ai.jsonl`),运行时 join;减少主特征表 IO |
| D-004 | jsonl 写出方式 | Spark `.write.json()` / `.write.text()` + UDF / pandas 收集 | **`.write.text()` + UDF 序列化**:保持 Spark 原生分片,无数据倾斜 |
| D-005 | jsonl 字段顺序 | 按定义顺序 / 按字母序 | **按定义顺序**(确定性强,便于人读) |
| D-006 | 流 trigger | `processingTime` / `continuous` | **`processingTime='3 minutes'`**:`continuous` 仍在实验 |
| D-007 | 流状态后端 | RocksDB / in-memory | **in-memory**(微批小,3min 窗口) |
| D-008 | 流 checkpoint | 沿用 HDFS / 切到本地 | **本地 + S3 备份**(客户现场是大数据平台,二选一) |
| D-009 | Kafka 起始 offset | `latest` / `earliest` | **`latest`(生产)+ `earliest`(回填测试)** |
| D-010 | 流输出合并策略 | foreachBatch 内 drop-and-rewrite / 增量 append | **foreachBatch 内临时 parquet 缓冲 + atomic rename** |
| D-011 | LLM prompt 版本 | hardcode / 外部文件 | **外部文件**(`configs/prompts/ai_enhance_v1.txt`),便于调优;prompt 动态注入字典 |
| D-012 | 7 维标签字典 | 硬编码 / 外部 yaml | **外部 yaml**(`configs/tag_dictionary.yaml`),运营可调;含 party_size 5 桶 |
| D-013 | party_size 推断路径 | 纯 LLM / 纯规则 / **规则优先 + LLM 兜底** | 规则快速覆盖 80%(双人套餐/家庭装等措辞),LLM 兜底推断剩余 20%(自助餐/单点菜等需看描述);融合后在 SC-010 上达 ≥ 95% 填充率 |
| D-014 | party_size 后处理 | 直出 / 字典校验 + 桶归一 | **字典校验 + 桶归一**(LLM 可能输出"2人"/"两人"/"double",全部归一为 `"2"`) |

---

## Phase 1 — 设计产物

### 1.1 新增数据模型(`data-model.md` 增量,本 plan 简述)

| 实体 | 字段 | 来源 |
|------|------|------|
| `AiTag` | item_id, taste[], occasion[], ingredient[], cuisine_region[], target_audience[], emotion_value[], **party_size(str)**, ai_model, ai_enhanced_at | `ai_enhance/` 输出 |
| `AiEnhanceState` | item_id, title_md5, desc_md5, enhanced_at, model | 增量模式用 |
| `AiEnhanceFailure` | item_id, raw_response, error, occurred_at | 失败日志 |
| `RealtimeEvent` | event_id, user_id, item_id, action, timestamp, content_type?, store_id?, amount? | Kafka message |
| `StreamingCheckpoint` | topic, partition, offset, committed_at | Spark streaming offset |

> **party_size 字段说明**:string 单值,枚举 `{1, 2, 3-4, 5-8, 9+}` 或 `""`。
> 不存 array,因为"份量"是商品固有属性(如双人套餐就是 2,即使一人吃完仍是 2)。

### 1.2 新增 contracts

- `contracts/ai_enhance_output.md` — `ai_enhance.py` 的输出 jsonl schema
- `contracts/streaming_event.md` — Kafka message schema
- `contracts/jsonl_format_v1.md` — 通用 jsonl 行格式约定

### 1.3 复用现有

- `feature_extraction/pipeline.py` 改 `output_format` 字段,默认 `jsonl`
- `writers/feature_writer.py` 改写,`jsonl` 分支调新 `writers/jsonl_writer.py`
- `common/config_loader.py` 加 `ai_enhance` / `streaming` / `output_format` 三段

---

## Phase 1 后的 Constitution Check(预期)

✅ I. Library-First — 2 个新子包独立
✅ II. CLI Interface — 2 个新 run_*.py
✅ III. Test-First — tasks.md 先测后实
✅ IV. Integration Testing — Kafka / LLM mock 集成
✅ V. Observability — 失败率 / lag / checkpoint 指标

---

## 关键文件清单(增量)

| 文件 | 类型 | 说明 |
|------|------|------|
| `feature_extraction/ai_enhance/{prompt,llm_client,enhancer,state,pipeline,tag_schema,party_size}.py` | 新增 | AI 增强子包(7 维) |
| `feature_extraction/writer.py` | 改 | 增加 jsonl 分支 |
| `writers/jsonl_writer.py` | 新增 | 通用 jsonl 写出 |
| `streaming/{kafka_consumer,dedup,interaction_updater,user_feature_updater,pipeline,checkpoint}.py` | 新增 | 流处理子包 |
| `run_ai_enhance.py` | 新增 | 入口 |
| `run_streaming.py` | 新增 | 入口(常驻) |
| `configs/prompts/ai_enhance_v1.txt` | 新增 | 7 维 prompt(含 party_size 字段说明 + 5 桶约束) |
| `configs/tag_dictionary.yaml` | 新增 | 7 维字典 |
| `tests/feature_extraction/ai_enhance/{test_prompt,test_tag_schema,test_party_size,test_enhancer,test_state}.py` | 新增 | AI 增强测试(含 party_size 专项) |
| `tests/streaming/*` | 新增 | 流处理测试 |
| `tests/feature_extraction/test_jsonl_output.py` | 新增 | jsonl 格式验证 |
| `common/config_loader.py` | 改 | 加 3 段配置 |
| `run_pipeline.py` | 改 | 加 `--skip-ai-enhance` |

---

## Complexity Tracking

| 违反 | 为什么 | 更简单方案(被拒理由) |
|------|--------|---------------------|
| (空) | (空) | (空) |

---

## Next Steps

1. **Phase 0 research.md**:在 D-001~D-012 12 个点收敛;LLM 客户端选型、Spark Streaming trigger 验证
2. **Phase 1 design**:`data-model.md` 增量 + `contracts/{ai_enhance_output,streaming_event,jsonl_format_v1}.md`
3. **/speckit-tasks**:按 US1 / US2 / US3 拆任务
4. **/speckit-implement**:按任务执行
