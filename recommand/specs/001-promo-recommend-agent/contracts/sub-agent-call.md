# Contract: 主 Agent ↔ 子 Agent 调用

**Owner**: 主 Agent(调用方)+ 子 Agent(被调用方)
**Date**: 2026-06-12
**Status**: Phase 1 — 契约
**Spec**: [spec.md §设计——交互方式](../spec.md)

> 主 Agent 与子 Agent 之间的调用走 **gRPC** + Protocol Buffers 描述,确保强 schema。子 Agent 跨调用无状态(每次调用是独立的),所有会话状态由主 Agent 通过调用入参下发。

---

## 1. 调用模式

- **传输**:gRPC(HTTP/2)
- **认证**:mTLS(内部服务网格统一管理)
- **超时**:默认 30s(可按工具细调;P99 < 5s)
- **重试**:默认不重试;由调用方在熔断器(见 research.md D-008)后决定
- **关联 id**:每次调用在 gRPC metadata 中带 `x-trace-id`

---

## 2. gRPC Service 定义

```protobuf
syntax = "proto3";
package promo_agent;

service LocalPromoAgent {
  // 主 Agent 向子 Agent 发起一次"工具调用"批次
  // (一次 RPC 可包含多个工具调用,LLM 一次响应内多 tool_calls)
  rpc InvokeTool (InvokeToolRequest) returns (InvokeToolResponse);
}

message InvokeToolRequest {
  // 上下文
  string user_id = 1;
  string session_id = 2;
  string trace_id = 3;
  repeated string device_ids = 4;        // 用于多端同步的 device 列表(空 = 单端)

  // 槽位(主 Agent 持有的 view)
  Slots slots = 5;

  // 当前状态(主 Agent 持有的 view,只读)
  SessionContext context = 6;

  // 工具调用批次(LLM 一次响应内的所有 tool_calls)
  repeated ToolCall tool_calls = 7;

  // 偏好(从 Preference Store 拉取后下发)
  repeated Preference preferences = 8;
}

message InvokeToolResponse {
  // 工具调用结果(顺序与请求一致)
  repeated ToolResult results = 1;

  // 子 Agent 的整体 Envelope 返回
  Envelope envelope = 2;

  // 更新后的上下文(若有)
  SessionContext updated_context = 3;
}
```

---

## 3. ToolCall / ToolResult

```protobuf
message ToolCall {
  string tool_call_id = 1;               // LLM 生成的 id(用于回填)
  string tool_name = 2;                  // 工具名(如 `exclude_items` / `prepare_draft`)
  google.protobuf.Struct arguments = 3;  // 工具入参(JSON-like)
}

message ToolResult {
  string tool_call_id = 1;               // 对应 ToolCall.id
  bool success = 2;
  string error_code = 3;                 // 失败时填
  string error_message = 4;
  google.protobuf.Struct result = 5;     // 工具出参(JSON-like)
}
```

---

## 4. SessionContext(主 Agent 下发的会话上下文 view)

```protobuf
message SessionContext {
  // 当前列表(若 LP 之前返回过)
  RecommendationList current_list = 1;

  // 当前草稿订单(若有)
  DraftOrder draft_order = 2;

  // 排序键
  SortKey sort_key = 3;

  // 本次临时排除项
  repeated string session_excludes = 4;

  // 临时覆盖的持久化偏好(本轮)
  repeated string preference_overrides = 5;

  // 上下文压缩摘要(若有)
  SessionSummary session_summary = 6;
  repeated Turn recent_turns = 7;        // 最近 N 轮原样
}
```

---

## 5. 工具清单(LP 子 Agent 内部)

LP 子 Agent 暴露给 LLM 的工具集(由 Function Calling 注册),按四层分组:

### 5.1 推荐工具层

| 工具名 | 入参 | 出参 | FR |
|--------|------|------|-----|
| `search_candidates` | `{slots, distance_filter, content_types?}` | `{candidates: list[Candidate], total_count: int}` | FR-012 |
| `llm_relax_and_recall` | `{original_query, slots, threshold}` | `{expanded_terms: list[string], candidates: list[Candidate]}` | FR-017 |
| `get_user_profile` | `{user_id}` | `{profile: UserProfile}` | FR-013 |
| `get_user_behavior_sequence` | `{user_id, lookback_days}` | `{actions: list[Behaviour]}` | FR-013 |
| `call_recommendation_service` | `{candidates, user_context, top_k}` | `{ranked_items: list[RecommendationItem]}` | FR-014 |
| `enrich_coupon` | `{items}` | `{items: list[EnrichedItem]}` | FR-015 |

### 5.2 下单工具层

| 工具名 | 入参 | 出参 | FR |
|--------|------|------|-----|
| `prepare_draft` | `{reference: {type: index/name/id, value: string}, quantity?}` | `{draft_order: DraftOrder, ambiguity_question?: string}` | FR-020 |
| `update_draft` | `{action: change_qty/swap_item/swap_coupon/cancel, ...}` | `{draft_order: DraftOrder}` | FR-021 |
| `pre_payment_validate` | `{draft_order_id}` | `{valid: bool, issues: list[string]}` | FR-023 |
| `handoff_to_payment` | `{draft_order_id}` | `{h5_payment_url: string, lock_ttl: int}` | FR-022 |
| `handle_payment_result` | `{order_id, status, reason?}` | `{final_state: FinalState}` | FR-022 |

### 5.3 券包工具层

| 工具名 | 入参 | 出参 | FR |
|--------|------|------|-----|
| `list_my_coupons` | `{status?, sort?, filters?}` | `{coupons: list[OwnedCoupon]}` | FR-024 |
| `get_coupon_detail` | `{coupon_id}` | `{coupon: CouponDetail}` | FR-024 |
| `compare_coupons` | `{coupon_ids: list[string]}` | `{comparison: ComparisonCard}` | FR-024 |

### 5.4 排除与偏好工具层

| 工具名 | 入参 | 出参 | FR |
|--------|------|------|-----|
| `exclude_items` | `{target_type: brand/category/item, target_value: string, scope: session_only}` | `{filtered_list: RecommendationList, exclusion_id: string}` | FR-018 |
| `get_active_preferences` | `{user_id, include_expired: false}` | `{preferences: list[Preference]}` | FR-019 |

---

## 6. 错误码

| 错误码 | 含义 | 主 Agent 行为 |
|--------|------|---------------|
| `INTERNAL` | 子 Agent 内部错误 | 走 Envelope 错误页 |
| `INVALID_ARGS` | 工具入参校验失败 | 提示用户格式错 |
| `NOT_FOUND` | 资源不存在(如商品已下架) | 走"商品已不可用"流程 |
| `AMBIGUOUS` | 引用歧义(下单单有多匹配) | 追问用户 |
| `OUT_OF_STOCK` | 商品已售罄 | 走"重新选择"流程 |
| `LOCK_HELD` | 多端互斥锁被另一端持有 | 提示"另一端正在支付" |
| `EXTERNAL_DOWN` | 外部服务不可用 | 走降级阶梯 |

---

## 7. 调用方(主 Agent)的责任

- 在调用子 Agent 前,主 Agent **必须**:
  1. 加载 Session State(Redis);
  2. 检查限流(FR-055);
  3. 校验意图(确保路由到正确的子 Agent);
  4. 把 SessionContext 序列化进 gRPC metadata 或 message 字段;
  5. 在 gRPC metadata 中带 `x-trace-id`。
- 在收到子 Agent 响应后,主 Agent **必须**:
  1. 把返回的 `envelope` 与 session state 合并;
  2. 更新 Redis(乐观写 + WATCH/MULTI 兜底);
  3. 触发 SSE 推送到所有活跃 device;
  4. 触发 Conversation Trace 的状态机更新(若为关键事件);
  5. 返回 H5 流式响应。
