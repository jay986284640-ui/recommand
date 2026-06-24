# Research: 优惠推荐 Agent (Promo Recommend Agent)

**Date**: 2026-06-12
**Status**: Phase 0 — Technology & Approach Decisions
**Spec**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)

> 本文件由 `/speckit-plan` Phase 0 产出。聚焦于 spec 阶段标记为"延后到 plan"或"由 plan 阶段定"的技术选型收敛,以及与外部依赖的集成最佳实践。**不重复** spec 中已经决定的事实(已决项见 plan.md 的 Summary 与 Technical Context)。

---

## 决策清单(Decisions)

### D-001:Agent 运行时语言 — **Python 3.11+**

- **Decision**: 主 Agent 与本地优惠子 Agent 服务均用 **Python 3.11+** 实现。
- **Rationale**:Python 是 LLM/Agent 生态主流(Anthropic SDK、OpenAI SDK、LangChain、LlamaIndex、Pydantic、FastAPI 等);与"大模型平台托管 API"对接的工具编排形态最契合;async/await 模式对 LLM 流式响应 + 多工具并发友好。
- **Alternatives considered**:
  - **Node.js 20+**:TypeScript 类型系统对工具 schema 友好,生态(OpenAI/Anthropic SDK、Vercel AI SDK)成熟;但对 Elasticsearch/数据处理 / Pydantic 类生态偏弱。**作为备选保留**,若团队 JS 栈为主则切换。
  - **Go**:性能与部署优势明显,但 LLM/Agent 生态弱,工具集成需手写。**未选**:与 spec 中"工具封装、轻量编排"的形态不匹配。
- **依赖**:Web 框架用 **FastAPI**(异步原生 + OpenAPI 自动生成,适合对话接口);内部 RPC 用 **gRPC**(性能 + 强 schema,主 Agent ↔ LP);ES 客户端用 **elasticsearch-py**;LLM SDK 按大模型平台供应商定。

### D-002:大模型平台 API 接入 — **Function Calling / Tool Use**

- **Decision**:主 Agent 与 LP 子 Agent 都通过大模型平台的 **Function Calling / Tool Use** 能力把"工具"暴露给 LLM,而不是手写"LLM 输出 JSON → 字符串解析"的工作流。
- **Rationale**:
  - Function Calling 是 Claude / OpenAI / 国内大模型平台的标配,工具 schema 一等公民;
  - 避免自研 JSON 解析的脆弱性(LLM 输出格式漂移);
  - 多轮 tool_calls 由平台 runtime 自动管理(输入 / 输出回填到 messages)。
- **Alternatives considered**:
  - **纯文本 + 提示词工程**:实现快但脆弱,不可生产。
  - **ReAct / LangChain Agent 框架**:抽象过重,反而把"主 Agent + 子 Agent"分层模糊掉;且 LangChain 版本演进快,锁定成本高。
- **落地**:
  - 主 Agent 暴露自己的工具(intent_classifier、session_state_getter、response_assembler、preference_writer、trace_recorder);
  - LP 子 Agent 暴露四层工具(recommend_*/order_*/wallet_*/exclude_*);
  - 工具入参 / 出参用 Pydantic schema,与 Envelope / H5 Payload 解耦。

### D-003:Session State 存储 — **Redis(per-user,JSON 序列化)**

- **Decision**:Session State(per-user,见 FR-003 / A-017)存于 **Redis**,按 user id 持有,值为 JSON 序列化的完整 state(当前列表、草稿、排序键、排除项、临时覆盖标记、压缩后的 Session Summary)。
- **Rationale**:
  - 多端共享要求"按 user id 持有 + 跨实例可访问",Redis 是天然选择;
  - 读写延迟在 1ms 量级,不影响端到端 4s 预算;
  - JSON 序列化便于多语言(若未来子 Agent 用其他语言实现)与跨实例迁移。
- **Alternatives considered**:
  - **进程内 + sticky session**:实现简单,但不支持多副本 + 跨实例重启;违反 FR-052 独立部署。
  - **Postgres / MySQL**:延迟偏高,不适合每轮读写的 state 存储;且成本不划算。
- **细节**:
  - Redis key: `sess:{user_id}`;
  - TTL:per-session 24h(可配);A-016 / FR-054 的"长会话"由压缩而非 TTL 处理;
  - 写策略:每轮 LLM 调用前先 GET,调完 SET 回去;并发场景用 Redis WATCH/MULTI 或分布式锁避免 race(关键操作如支付前互斥)。

### D-004:多端同步协议 — **H5 端 SSE(Server-Sent Events)主动推送 + 状态轮询兜底**

- **Decision**:H5 与主 Agent 之间,文本对话流用现有流式协议(已有);**session state 变更**(另一端排序 / 排除 / 下单)用 **SSE 主动推送**到当前活跃端,非活跃端在下一轮打开时通过轮询获取最新 state。
- **Rationale**:
  - SSE 单向推送足够(LP 不需要 H5 反向 ack),实现简单,断线自动重连;
  - 比 WebSocket 轻量,符合"H5 后端"形态;
  - 多端"严格一致"不是 MVP 必需,2s 内最终一致即可。
- **Alternatives considered**:
  - **WebSocket**:双向,功能更强,但实现复杂度高,且我们不需要反向消息;
  - **纯短轮询**:实现最简,但实时性差(秒级),且服务端压力较大。
- **细节**:
  - 主 Agent 在每次修改 session state 后,fan-out 推送到该 user 的所有活跃 SSE 连接;
  - 推送 payload: `state_version` + diff(用 list id + 状态变更,不全量);
  - 多端互斥(FR-023b):H5 在准备进入支付流时,主 Agent 先在 Redis 上设"草稿锁",锁的 TTL 是支付超时上限(默认 5 分钟)。

### D-005:上下文压缩实现 — **自研 + LLM 摘要(走独立 service)**

- **Decision**:主 Agent 内部封装"上下文压缩器",触发后调用独立 service(也是一个 LLM 调用,模型可选更便宜档)生成 Session Summary,回填到 Session State。
- **Rationale**:
  - 压缩本身需要 LLM 调用(生成摘要),但**不**应阻塞主对话的 LLM 调用;**可以**复用同一个 LLM,但用更便宜的 model 档;
  - 独立 service 便于监控压缩失败率、降级策略、压缩质量;
  - 摘要去标识处理(FR-054 + A-016)放在 service 内部集中做。
- **Alternatives considered**:
  - **第三方 SDK(如 LangChain 的 ConversationSummaryMemory)**:抽象过重,失去对触发阈值 / 摘要字段的精细控制。
  - **规则式截断(取最近 N 轮)**:实现最简,但丢失关键早期信息;只能作为"压缩失败降级路径"。
- **细节**:
  - 触发:每轮 LLM 调用前检查 token 数 / 字符数 / 轮次,任一超阈值触发;
  - 摘要字段:见 FR-054 锁定的"必须保留项";
  - 失败降级:丢弃早期轮次,保留最近 N 轮,失败信息写入 Conversation Trace。

### D-006:Conversation Trace 存储 — **OLAP-friendly 列存(初版 ClickHouse 或同类)**

- **Decision**:Conversation Trace 存于 **OLAP 列存**(ClickHouse 或同类,具体由基础设施团队确定),按会话时间分区,字段固定 schema,带 TTL(默认 6 个月,见 A-019)。
- **Rationale**:
  - 数据用于离线归因分析(US 6 / FR-053),不做实时查询;
  - 列存 + 分区 + 压缩比对关系数据库节省 10x+ 存储;
  - 6 个月保留后自动删除(A-019)。
- **Alternatives considered**:
  - **标准日志库(ES / Loki)**:可行但 ES 的聚合 / 漏斗分析能力对失败归因的常用查询不算最优;
  - **数据仓库(BigQuery / Snowflake)**:能力最强,但成本高,首期不必要;
  - **Postgres**:可作为 MVP 起步,后续迁移到 OLAP。
- **细节**:
  - 写入路径:**异步**(FR-053),主 Agent 推到消息队列(Kafka / RocketMQ),消费者写入列存;
  - 字段:见 FR-053 锁定的"必须包含项";
  - 关联 id 是主键,user id 做脱敏(hash);
  - 运营查询 UI 由运营/分析团队建设,Agent 不负责。

### D-007:ES 双路召回(关键词 + 向量) — **既有 ES 集群扩展向量能力**

- **Decision**:沿用现有 ES 集群,使用其 **dense_vector** 字段 + **knn 检索** 做向量召回;关键词走原有 `multi_match` / `match` 查询;两路结果在 LP 子 Agent 内合并去重。
- **Rationale**:
  - 复用现有 ES 集群,避免引入新基础设施;
  - ES 8.x 的 dense_vector + knn 已经生产可用;
  - 关键词 + 向量互补:关键词保证精确匹配(品牌名 / 店名),向量保证语义相关(冷门品类联想)。
- **Alternatives considered**:
  - **独立向量数据库(Milvus / Qdrant / Pinecone)**:能力更强,但引入新基础设施 + 数据双写复杂度,**首期不选**;
  - **纯关键词(无向量)**:召回质量不足,达不到"联想召回"的语义扩展效果。
- **细节**:
  - 索引设计:商品 / 门店文档同时有 `text`(分词)+ `embedding`(dense_vector);
  - embedding 模型:由 ES 同厂商的 embedding 服务或 LLM 平台提供(由基础设施决定);
  - 双路召回:对同一 query,同时发两个查询(关键词 + knn),合并去重(以 id 为键);
  - 联想召回路径:LLM 扩词 → 双路召回 → 合并去重(同上去重)。

### D-008:降级阶梯 — **熔断器 + 多级 fallback(circuit breaker pattern)**

- **Decision**:LP 子 Agent 对外部服务(ES / 推荐服务)用 **circuit breaker** 模式封装,失败率 > 30% 持续 1 分钟即开路(见 A-018),走降级路径。
- **Rationale**:
  - 避免"雪崩":一个慢服务拖死所有调用;
  - 阶梯式降级:ES 挂 → 缓存回退;推荐服务挂 → 跳过 LLM;两路全挂 → 错误页(FR-014b);
  - 熔断器是成熟模式,有开源库可直接用(pybreaker、polly 等)。
- **Alternatives considered**:
  - **手动 try/except + 重试**:可工作但缺乏"开路/半开路"的状态机,无法自动恢复;
  - **重试到死**:在外部服务真挂时会把请求积压拖死整个系统。
- **细节**:
  - ES 熔断:失败率 > 30% 持续 1 分钟开路,半开路探测 30 秒一次;
  - 推荐服务熔断:同上;
  - 缓存:ES 缓存候选由推荐服务侧维护(LLM 排序时一并写缓存,缓存键 = 用户位置 + 品类 + 时间);
  - 告警:开路 / 半开路事件触发 Prometheus 告警,关联 id 写入 Conversation Trace。

### D-009:per-user 限流 — **Redis 滑动窗口(counter + expire)**

- **Decision**:用 **Redis 滑动窗口** 实现 per-user 限流(FR-055:50 次/分钟);key = `rl:{user_id}:{minute_bucket}`;敏感操作(下单 / 改单)单独 key(`rl:order:{user_id}:{minute_bucket}`,默认 10 次/分钟)。
- **Rationale**:
  - Redis INCR + EXPIRE 是限流的最经典实现,延迟低(< 1ms);
  - 滑动窗口可用 `ZSET`(时间戳为 score)更精确,但本场景下"分钟级"精度足够,counter 即可;
  - 与 Session State 复用同一 Redis 实例,运维简单。
- **Alternatives considered**:
  - **令牌桶(漏桶)**:更精确但开销大,本场景不需要;
  - **API 网关层限流**:如果整个平台有统一网关,可以下推;但 Agent 自身需要兜底(网关挂了 Agent 也要保护自己)。
- **细节**:
  - 正常请求:`INCR rl:{user_id}:{minute_bucket}`;若 > 50,返回"操作太频繁"提示;
  - 敏感操作:同样模式,key 不同,阈值不同;
  - 响应:超限必须立即返回,**不**走 LLM 调用(节省成本);
  - 多端共享:key 按 user id 持有(与 A-017 一致),不是按 session。

### D-010:多 LLM 调用 / 工具调用的成本控制

- **Decision**:典型推荐轮次 ≤ 2 次 LLM 调用(SC-008:1 路由 + 1 排序);其他能力(压缩、摘要生成)走独立 service,**不计入主对话 LLM 计数**。
- **Rationale**:
  - 严格锁定单轮成本上限,便于成本预测;
  - 联想召回的 LLM 扩词:走"独立短 LLM 调用"(非主对话模型),成本低;
  - 上下文压缩:走"独立 service + 便宜模型"(见 D-005);
  - 偏好写入追问的"是否要持久化":**不**走 LLM,走 H5 按钮(确定性交互)。
- **落地**:
  - 主 Agent 内的工具集以"主对话 LLM 调用" 为约束;
  - 副 service(压缩、扩词)用独立 token 预算;
  - 监控指标:每轮 LLM 调用次数的 P50 / P95 / P99 报表 + 告警(> 2 触发)。

---

## 与外部依赖的集成最佳实践

### I-001:与"大模型平台托管 API"集成

- **调用模式**:HTTPS REST,带鉴权(Bearer token);
- **请求/响应格式**:JSON,遵循平台约定的 messages / tools schema;
- **超时与重试**:单次调用 30s 超时,**最多 1 次重试**(避免雪崩);
- **关联 id 透传**:在请求 metadata 中带 `trace_id`,用于跨服务追踪;
- **错误处理**:4xx(参数错)直接失败;5xx(平台故障)走熔断器;
- **降级**:见 D-008。

### I-002:与 Elasticsearch 集成

- **查询模式**:同步查询(单次 ≤ 200ms 超时);
- **索引变更**:不在 Agent 端发起(由数据团队负责);
- **连接管理**:长连接池,默认 10 个连接;
- **降级**:见 D-008(ES 缓存回退)。

### I-003:与 Preference Store 集成

- **数据契约**:`{user_id, target, direction, source, confidence?, created_at, expire_at}`;
- **TTL**:`expire_at` 由 Preference Store 主动扫描清理;
- **写入主 Agent 端**(主 Agent 走"持久化追问"流程,见 FR-018);
- **读取 LP 子 Agent 端**(在检索 / 排序前调用,见 FR-019)。

### I-004:与收银台 / 订单服务集成

- **下单**:LP 子 Agent 准备草稿 → 收银台 H5 标准支付流(Agent 不直接调收银台);
- **支付结果回传**:H5 回调主 Agent → 主 Agent 更新 session state + 写 Conversation Trace;
- **互斥**:见 D-004 的 Redis 锁。

### I-005:与 H5 前端的契约

- **入参**:user query、session id、user id、device id(用于多端)、location(可选);
- **出参**:流式文本 + Envelope(`items?` / `summary` / `actions?` / `follow_up?`);
- **流式**:SSE 推送,每个 chunk 是增量;
- **错误**:结构化错误码 + 用户友好提示。

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM 平台故障 | 全 Agent 不可用 | 熔断器 + 缓存候选 + 友好错误页(FR-014b) |
| ES 故障 | 推荐不可用 | 缓存回退(FR-012b) |
| Redis 故障 | 会话状态丢失 | Session State 持久化策略:RDB + AOF;TTL 24h;丢失的会话用户重新进入即重置 |
| 多端同步延迟 > 2s | 体验割裂 | 优先用 SSE,延迟可控;非活跃端 5s 轮询兜底 |
| 上下文压缩失败 | 长会话 LLM 上下文爆炸 | 降级为"丢早期轮次"(FR-054),失败信息进 trace |
| 限流误伤真实用户 | 用户投诉 | 阈值 50/分钟远超典型用户(5~10 轮);监控误伤率;误伤即放宽 |
| 联想召回幻觉 | 推荐不相关 | 硬护栏:商品必须来自 ES 召回结果(FR-017);定期评测召回质量 |
| 偏好数据 PII 泄漏 | 隐私合规事故 | 偏好只存"目标 + 方向 + 来源",不存原始输入(FR-019);写入时去标识 |
| Conversation Trace 数据膨胀 | 存储成本 | 6 个月 TTL(A-019)+ 聚合脱敏(分析时不可定位个人) |

---

## 待 tasks 阶段进一步细化的点

- [ ] LP 子 Agent 内部各工具的具体 Pydantic schema(在 tools.md 契约中展开)
- [ ] 主 Agent 的 prompt 模板(在 tasks 阶段单独作为"prompt-task"实现)
- [ ] 推荐服务的 SLO 数字(由推荐服务团队定;此处只引用其承诺)
- [ ] Redis 集群的具体配置(主从 / Sentinel / Cluster,运维决定)
- [ ] ES 索引的 mapping(由数据团队定;Agent 端只消费查询)
- [ ] 限流敏感操作(下单 / 改单)的具体阈值(默认 10 次/分钟,plan 阶段已锁定)
- [ ] 新用户 → 个性化的切换阈值(默认 5 次浏览或 1 次下单;在 plan 阶段定,见 A-009 / FR-014c)
- [ ] 第一期 DAU / 容量基线(由产品/运营提供,见 plan.md Scale/Scope)

---

## Open Questions(留给 plan 收尾或后续阶段)

- **OQ-P1**:大模型平台供应商具体是哪个(Anthropic / OpenAI / 国内大模型)?这决定 SDK 选择;**plan 阶段**可暂以"通用 LLM SDK 抽象 + Function Calling"实现,具体平台在实现期选。
- **OQ-P2**:ES 集群的版本(7.x vs 8.x)?8.x 支持 dense_vector + knn;若 7.x 需要先升级或独立向量索引。**plan 阶段**默认 8.x。
- **OQ-P3**:现有用户资产查询服务、券服务、订单服务、收银台服务的 API 风格(REST / gRPC / Dubbo)?这决定客户端 SDK 选择。**plan 阶段**统一为内部 SDK(可包装不同协议),对 Agent 透明。
- **OQ-P4**:Conversation Trace 的查询 / 报表 UI 由谁提供?运营 / 数据团队 vs Agent 平台?**plan 阶段**默认运营 / 数据团队提供,Agent 只负责写。
