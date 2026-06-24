# Implementation Plan: 优惠推荐 Agent (Promo Recommend Agent)

**Branch**: `001-promo-recommend-agent` | **Date**: 2026-06-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/opt/recommand/recommand/specs/001-promo-recommend-agent/spec.md`

**Note**: 本 plan 由 `/speckit-plan` 命令产出。Spec 阶段的所有澄清已就位(5 条 Q→A),本 plan 在 spec 基础上定 Technical Context、做 Constitution Check、并产出 research / data-model / contracts / quickstart 四类设计文档。具体的"按 US 拆任务"放在 `/speckit-tasks` 阶段。

---

## Summary

第一期交付一个**主 Agent + 单子 Agent(本地优惠)的多 Agent 推荐系统**,部署为后端服务。H5 通过统一的对话接口调用主 Agent,主 Agent 负责意图分类、会话状态(per-user,跨多端)、跨子 Agent 编排、响应组装;**所有具体能力(推荐 / 下单 / 改单 / 支付交接 / 券包管理 / 联想召回 / 排除与偏好 / 上下文压缩 / 失败回溯)**都以"工具"形式下沉到本地优惠子 Agent 或主 Agent 自身。第一期不实现积分商城子 Agent,主 Agent 通过"未注册子 Agent → 暂未支持"兜底保证扩展性。

核心架构决定:
- **主 Agent 持有会话状态**(无状态 LP 子 Agent + 上下文压缩在主 Agent)
- **统一 Envelope 契约**(`{items?, summary, slots_used, sort_key?, actions?, follow_up?}`) + `Envelope + actions` 让 H5 用同一份 payload 渲染聊天气泡、商品卡、操作按钮
- **按"降级阶梯"处理外部依赖故障**(ES 缓存回退 / 推荐服务跳过 LLM 排序 / 两路全挂走错误页)
- **失败交易回溯 + 上下文压缩**作为非功能性基石,主 Agent 异步落盘 conversation trace、并在长会话时把早期轮次压缩为 summary

技术接入形态:大模型平台托管 API(推荐服务)+ Elasticsearch(候选检索)+ Preference Store 服务(偏好)+ 用户资产查询服务(券包)+ 上下文压缩服务(摘要生成)+ Conversation Trace 存储(回溯记录)+ H5 收银台(支付交接)。**Agent 不拥有数据,只编排工具**。

---

## Technical Context

**Language/Version**: Python 3.11+ (主要候选);Node.js 20+ (备选)。
*理由*:Python 是 LLM/Agent 生态的主流(OpenAI SDK、Anthropic SDK、LangChain、LlamaIndex 等),与"大模型平台托管 API"+"工具编排"形态契合。Node.js 是备选,适合团队更熟悉 TS/JS 栈时。最终决定由项目侧技术栈决定,在 Phase 0 research.md 中给出推荐与备选。

**Primary Dependencies**:
- LLM SDK(Anthropic Claude SDK / OpenAI SDK,具体看大模型平台)
- Elasticsearch Python/JS client
- 内部服务 SDK:Preference Store、用户画像、行为序列、用户资产查询、券服务、订单服务、收银台服务、推荐服务
- Web 框架(FastAPI / Express,用于暴露对话接口)
- 可观测性:OpenTelemetry SDK + 关联 id 透传

**Storage**:
- Agent 自身**不直接拥有数据**;依赖外部服务(参考上条)。
- **Session State** 在主 Agent 内部按 user id 持有;持久化方案在 research.md 中收敛(Redis 优先,因为 per-user state 需要跨实例共享、且需要支持多端同步,见 A-017)。
- Conversation Trace 用专门的 trace store(类日志存储),**异步写入**(FR-053)。
- Session Summary 同上,作为 trace 的一部分或单独的 summary store(由 research 决定)。

**Testing**:
- pytest / Jest(取决于语言选择)
- 单元测试:工具函数、Envelope 序列化、降级阶梯、降级路径
- 集成测试:与 ES / 推荐服务 / Preference Store 等的契约测试(FR-052 + Constitution IV 集成测试要求)
- 端到端测试:H5 ↔ 主 Agent ↔ LP 的完整对话流(Q1~Q8 各场景的端到端验证)
- 冒烟测试:FR-014b / FR-012b 的降级路径(故意把 ES / 推荐服务打挂,验证走降级)

**Target Platform**: Linux 容器(主 Agent + LP 子 Agent 均为独立部署的容器);**多副本 + 负载均衡**(因 Session State 在 Redis 而非进程内);H5 部署在 web,不归本服务管。

**Project Type**: Web service(后端服务)+ 内部模块(LP 子 Agent 作为主 Agent 内的子模块或独立进程;倾向**独立进程 + 内部 RPC**,便于独立部署、独立扩容)。

**Performance Goals**:
- 端到端发现路径 p95 ≤ 4 秒(SC-001)
- 单轮 LLM 调用次数 ≤ 2(SC-008:一次路由/意图,一次排序;联想召回与压缩是异步或独立路径,不计)
- per-user 限流:50 次/分钟(FR-055);下单相关操作更严格(plan 阶段定)
- 多端同步延迟:H5 端的状态变更同步到另一端 ≤ 2 秒(由 H5 推送/轮询实现,具体在 plan 收尾阶段定)

**Constraints**:
- **不得**在前端 / Agent 暴露 PII(身份证 / 手机号 / 银行卡等);Conversation Trace 与 Session Summary 强制去标识
- 不得在支付前阻塞超过 200ms(FR-023b 互斥校验);不得在压缩失败时阻塞用户(FR-054 降级)
- 单 LLM 调用的输入 token 必须有界(默认 ≤ 8000 字符,FR-054 压缩触发)
- 不依赖特定云厂商;服务可在私有化 / 公有云 / 混合云部署

**Scale/Scope**:
- 第一期目标:支持 X 万 DAU(具体数字由产品/运营定,**plan 阶段填入**)
- 单次会话典型 5~10 轮,极端情况 30+ 轮(由 FR-054 压缩支撑)
- 候选集:ES 候选 ≤ 50 条(FR-012 硬性封顶),推荐 top-K = 10(默认)
- 商品库:预估 1 万~10 万 SKU(美团 + 自拓展 + 外部券);具体由推荐服务侧定

---

## Constitution Check

*GATE: 必须在 Phase 0 research 开始前通过;Phase 1 设计后再次校验。*

### 初次校验(Phase 0 前)

### I. Library-First ✅
- 主 Agent 与 LP 子 Agent 都被设计为**可独立部署的进程**(FR-052),每个子 Agent 的工具集按"四层"分组(推荐 / 下单 / 券包管理 / 排除与偏好),边界清晰。
- 第二期新增"积分商城子 Agent"无需重写主 Agent,只通过 Sub-Agent Registry 注册(FR-040)。
- 满足 Library-First 的"独立可测 + 独立可部署 + 单一职责"。

### II. CLI Interface ✅
- 主 Agent 暴露一个 **HTTP/JSON 对话接口**(H5 ↔ 主 Agent);内部主 Agent ↔ LP 子 Agent 走"类工具调用"的结构化请求/响应(已在 spec 的"交互方式"小节锁定)。
- LP 子 Agent 自身的工具(`exclude_items` / `prepare_draft` / `list_my_coupons` 等)可视为"内部 CLI"——每个工具都有明确的入参 / 出参 schema,由 Envelope 统一封装。
- 满足 CLI Interface 的"stdin/args → stdout;errors → stderr"——主 Agent 入参是 user query,session id,user id;出参是 Envelope + payload。

### III. Test-First (NON-NEGOTIABLE) ✅
- 每个 US 都有"独立可测试"声明(US 1~8 均含独立可测试段)。
- 9 条 SC 全部可被自动化/手工验证;Q1~Q5 的 5 条澄清均已下沉为可测试的 FR(FR-003 多端 / FR-012b ES 降级 / FR-019b 删除 / FR-055 限流 / FR-014c 新用户回退)。
- **任务分解阶段(`/speckit-tasks`)必须先写测试任务,再写实现任务**——这是 Constitution III 的硬约束,会被 tasks.md 评审时检查。

### IV. Integration Testing ✅
- 跨服务契约:主 Agent ↔ Preference Store / 用户画像 / 行为序列 / 券服务 / 订单服务 / 收银台 / 推荐服务 / ES。
- 跨服务集成测试在 PR 流程中**必须**跑通,作为发布门。
- Conversation Trace 写入路径(FR-053)+ 上下文压缩(FR-054)作为"输出侧契约"也必须有集成测试覆盖。

### V. Observability, Versioning, Simplicity ✅
- **Observability**:FR-051(关联 id 贯穿 + 无 PII 日志)+ FR-053(Conversation Trace)+ FR-014b / FR-012b(降级路径带告警)+ OpenTelemetry 集成。
- **Versioning**:Sub-Agent Registry(FR-040)+ 主 Agent / LP 子 Agent 独立版本化(FR-052)+ Envelope 契约向后兼容。
- **Simplicity**:不引入额外的子 Agent 边界(Order 工具下沉到 LP 内,Q1 选择 B);不引入额外的服务边界(Preference Store 由后端提供,Agent 不实现);不引入"双层缓存"(ES 缓存由推荐服务侧维护,Agent 端不重复实现)。

**初次 Constitution Check 状态:通过**。Complexity Tracking 表为空——未触发"违反原则需要正名"的情况。

---

### 重审(Phase 1 设计后)

Phase 1 已产出 `research.md` / `data-model.md` / `contracts/` / `quickstart.md`。重审 Constitution 五项:

### I. Library-First ✅(重审)
- 主 Agent 与 LP 仍为两个独立服务(`main-agent/` + `local-promo-agent/`),各自有独立的 src / tests / Dockerfile。
- LP 内部工具按四层目录组织(`tools/recommend/` / `tools/order/` / `tools/wallet/` / `tools/exclude/`),每层可视为"内部 library"。
- 满足 Library-First。**无回归**。

### II. CLI Interface ✅(重审)
- H5 ↔ 主 Agent:`POST /agent/chat` + SSE 流式,见 `contracts/h5-payload.md`(等价于 CLI 的 stdin/args → stdout + structured errors)。
- 主 Agent ↔ LP:`gRPC LocalPromoAgent.InvokeTool`,见 `contracts/sub-agent-call.md`(结构化 Request/Response,errors 通过 `ToolResult.error_code` 表达)。
- LP 内部工具:每个都有 `tool_name` + `arguments(JSON)` + `result(JSON)`,见 `contracts/sub-agent-call.md §5`。
- 满足 CLI Interface。**无回归**。

### III. Test-First (NON-NEGOTIABLE) ✅(重审)
- `quickstart.md` 给出 8 个核心场景 + 8 个边界场景 + 3 个性能基线 + 5 个测试金字塔层级,**全部必须先写测试用例**。
- `tasks.md`(`/speckit-tasks` 阶段)将基于此 quickstart 拆任务,**先测试任务后实现任务**。
- 满足 Test-First。**无回归**。

### IV. Integration Testing ✅(重审)
- 契约测试覆盖:主 Agent ↔ Preference Store / 用户画像 / 行为序列 / 券服务 / 订单服务 / 收银台 / 推荐服务 / ES / Redis / OLAP / Kafka。
- 端到端测试覆盖:8 个核心场景(对话发现 / 排除持久化 / 联想召回 / 下单闭环 / 券包 / 重排 / 压缩 / 回溯)。
- 降级冒烟覆盖:ES 故障 / 推荐服务故障 / 两路全挂(FR-012b / FR-014b)。
- 满足 Integration Testing。**无回归**。

### V. Observability, Versioning, Simplicity ✅(重审)
- **Observability**:research.md §I-001 锁定 OTel + trace_id 透传;quickstart 性能基线验证延迟 / LLM 调用次数;FR-053 异步 trace 写入 + 6 个月 TTL。
- **Versioning**:Sub-Agent Registry 在 `data-model.md §16` 中明确定义(版本化 + 启停);Envelope 契约在 `contracts/envelope.md §4` 锁定向后兼容(MAJOR.MINOR)。
- **Simplicity**:**仍无违反**。Phase 1 设计未引入额外的服务/中间件/抽象层;所有决策都有更简单的备选被显式拒绝并记录理由(research.md 的 "Alternatives considered" 段)。
- 满足。**无回归**。

**重审 Constitution Check 状态:通过**。Complexity Tracking 表仍为空,Phase 1 设计未引入任何需要正名的复杂度。

---

## Project Structure

### Documentation (this feature)

```text
specs/001-promo-recommend-agent/
├── plan.md              # 本文件(/speckit-plan 输出)
├── research.md          # Phase 0 输出
├── data-model.md        # Phase 1 输出
├── quickstart.md        # Phase 1 输出
├── contracts/           # Phase 1 输出
│   ├── envelope.md      # 统一响应 Envelope 契约
│   ├── sub-agent-call.md# 主 Agent ↔ 子 Agent 调用契约
│   ├── tools.md         # LP 内部工具集契约
│   └── h5-payload.md    # H5 ↔ 主 Agent 入出参契约
├── checklists/
│   └── requirements.md  # 规格质量检查清单
└── tasks.md             # /speckit-tasks 输出(本 plan 不创建)
```

### Source Code (repository root)

```text
# 主 Agent 服务(对话入口、会话状态、跨子 Agent 编排)
agent-platform/
├── main-agent/
│   ├── src/
│   │   ├── core/                # 主 Agent 核心:意图分类、状态机、响应组装
│   │   ├── session/             # Session State(Redis-backed)、per-user 隔离
│   │   ├── compression/         # 上下文压缩(FR-054)+ Session Summary
│   │   ├── trace/               # Conversation Trace 写入(FR-053,异步)
│   │   ├── ratelimit/           # per-user 限流(FR-055)
│   │   ├── multi-device/        # 多端同步(FR-003 / FR-023b 互斥)
│   │   ├── preferences/         # Preference Store 写入主 Agent 端
│   │   ├── registry/            # Sub-Agent Registry(FR-040)
│   │   └── api/                 # HTTP 对话接口(H5 ↔ 主 Agent)
│   └── tests/
│       ├── unit/
│       ├── integration/         # 与 Preference / 用户画像 / ES / 推荐服务 等的契约
│       └── e2e/                 # 8 个 US 的端到端验证
│
# LP 子 Agent 服务(独立部署,主 Agent 通过 RPC 调用)
├── local-promo-agent/
│   ├── src/
│   │   ├── core/                # LP 核心:槽位抽取、工具调度、Envelope 返回
│   │   ├── tools/
│   │   │   ├── recommend/       # 推荐工具层(ES 检索、联想召回、推荐服务调用、补全、合并)
│   │   │   ├── order/           # 下单工具层(草稿、改单、校验、收银台交接)
│   │   │   ├── wallet/          # 券包工具层(list / detail / compare)
│   │   │   └── exclude/         # 排除与偏好工具层(exclude_items + Preference 读取)
│   │   ├── degradation/         # 降级阶梯(ES 缓存回退 / 推荐服务跳过 LLM)
│   │   └── prompts/             # 子 Agent 提示词版本化
│   └── tests/
│       ├── unit/                # 各工具的单元测试
│       ├── contract/            # 与 ES / 推荐服务 / 收银台 / Preference 等的契约
│       └── smoke/               # 降级路径冒烟测试(FR-012b / FR-014b)
│
# 共享契约(Envelop、Tool schema)
├── contracts/
│   ├── envelope.py / .ts
│   └── tool_schemas/             # 工具入参 / 出参 Pydantic / Zod schema
│
# 部署 / 基础设施
├── deploy/
│   ├── docker/
│   │   ├── main-agent.Dockerfile
│   │   └── local-promo-agent.Dockerfile
│   ├── k8s/                      # K8s manifests(主 Agent + LP 各自独立 Deployment + HPA)
│   └── observability/            # OTel collector、Prometheus 规则
```

**Structure Decision**:
- **两个独立服务**:`main-agent` 与 `local-promo-agent` 各自独立部署、独立扩容(FR-052 + Constitution V·Simplicity)
- **共享契约**:`contracts/` 目录同时被两个服务 import,作为内部 SDK 形式
- **观测与部署**:`deploy/observability` 提供 FR-051 / FR-053 的运行基础
- **第二期扩展**:`points-mall-agent/` 作为第三个服务,只需在 `main-agent/registry` 注册即可(FR-040)

---

## Complexity Tracking

> 仅在 Constitution Check 出现违反时填写。本 plan 无违反,故表为空。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (空) | (空) | (空) |

---

## Next Steps

1. **/speckit-plan Phase 0** → `research.md`:在以下点上做技术选型收敛(详见 research.md):
   - 大模型平台 API 的接入方式(Function Calling / Tool Use / 文本+JSON 等)
   - 上下文压缩的具体实现(自研 + LLM 摘要 / 第三方 SDK)
   - Conversation Trace 的存储选型(日志库 / OLAP / 数据仓库)
   - Session State 的存储选型(Redis / 内存 + 持久化)
   - 多端同步的实现(WebSocket / SSE / 短轮询)
2. **/speckit-plan Phase 1** → `data-model.md` + `contracts/` + `quickstart.md`
3. **Constitution Check 重审**(Phase 1 完成后)
4. **/speckit-tasks** → `tasks.md`(按 US 拆分,先写测试再写实现)
5. **/speckit-implement** → 按 tasks.md 顺序执行
