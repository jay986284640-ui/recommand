# Contract: H5 ↔ 主 Agent 入出参

**Owner**: H5 前端 + 主 Agent
**Date**: 2026-06-12
**Status**: Phase 1 — 契约
**Spec**: [spec.md §设计——交互方式](../spec.md)

> H5 与主 Agent 之间的对话协议:HTTP/JSON(SSE 流式)。

---

## 1. 入参(POST /agent/chat)

```yaml
ChatRequest:
  user_id: string                        # 用户 id(主 Agent 校验登录态)
  session_id: string                     # 会话 id(可由 H5 生成,持久化在 localStorage)
  device_id: string                      # 当前设备 id(用于多端同步)
  text: string                           # 用户输入文本
  voice_transcript: string?              # 若来自语音输入
  location: GeoPoint?                    # 用户位置(若有)
  client_meta: ClientMeta                # 客户端元信息

GeoPoint:
  lat: float
  lng: float
  accuracy_m: int?                       # 定位精度

ClientMeta:
  app_version: string
  h5_version: string
  locale: string                         # zh-CN / en-US
  network_type: string                   # wifi / 4g / 5g
```

**示例**:
```json
POST /agent/chat
{
  "user_id": "u_12345",
  "session_id": "s_abc123",
  "device_id": "d_phone_x",
  "text": "附近有什么咖啡优惠",
  "location": { "lat": 39.9, "lng": 116.4, "accuracy_m": 50 },
  "client_meta": { "app_version": "1.0.0", "h5_version": "1.0.0", "locale": "zh-CN" }
}
```

---

## 2. 出参(SSE 流式)

每个 chunk 是一个 JSON 对象,以 `\n\n` 分隔(标准 SSE 协议)。

```yaml
ChatChunk:
  chunk_type: enum                       # `text_delta` | `envelope` | `actions` | `error` | `done`
  delta: string?                         # chunk_type=text_delta 时,增量文本
  envelope: Envelope?                    # chunk_type=envelope 时,完整 Envelope(在最后一个 chunk)
  actions: list[Action]?                 # chunk_type=actions 时,H5 按钮
  error: ErrorPayload?                   # chunk_type=error 时
  final_meta: FinalMeta?                 # chunk_type=done 时

FinalMeta:
  trace_id: string
  total_duration_ms: int
  llm_call_count: int
  state_version: int                     # 用于多端同步

ErrorPayload:
  code: string                           # `OUT_OF_SCOPE` | `RATE_LIMITED` | `INTERNAL` | `EXTERNAL_DOWN`
  message: string                        # 用户友好提示
  retry_after_ms: int?                   # 限流时建议
```

**示例**(SSE 流):
```text
event: chunk
data: {"chunk_type":"text_delta","delta":"附近"}

event: chunk
data: {"chunk_type":"text_delta","delta":"有 3 家咖啡店有优惠..."}

event: chunk
data: {"chunk_type":"actions","actions":[{"action_id":"view_item_0","label":"查看详情","style":"primary","payload":{...}}]}

event: chunk
data: {"chunk_type":"envelope","envelope":{"summary":"...","items":[...],"slots_used":{...},"sort_key":"distance","trace_meta":{...}}}

event: chunk
data: {"chunk_type":"done","final_meta":{"trace_id":"t_xyz","total_duration_ms":2400,"llm_call_count":2,"state_version":17}}
```

---

## 3. 多端同步(H5 主动订阅 SSE)

```yaml
# 端点:GET /agent/session/stream?user_id=u_12345&device_id=d_phone_x
# 协议:SSE
# 触发:另一端修改 session state(排序 / 排除 / 下单草稿等)
# 频率:按需推送,不发空消息

SyncEvent:
  event_type: enum                       # `state_diff` | `list_changed` | `draft_changed` | `lock_acquired` | `lock_released`
  state_version: int
  diff: SessionStateDiff?                # 仅发送变更的字段

SessionStateDiff:
  current_list: RecommendationList?
  draft_order: DraftOrder?
  sort_key: SortKey?
  session_excludes_delta: SessionExcludesDelta?
  multi_device_lock: MultiDeviceLock?

SessionExcludesDelta:
  added: list[string]
  removed: list[string]

MultiDeviceLock:
  state: enum                            # `acquired` | `released` | `expired`
  holder_device: string?
  locked_at: datetime?
  lock_ttl_seconds: int?
```

**示例**:
```text
event: sync
data: {"event_type":"state_diff","state_version":18,"diff":{"current_list":{...},"sort_key":"price_asc"}}

event: sync
data: {"event_type":"lock_acquired","state_version":19,"diff":{"multi_device_lock":{"state":"acquired","holder_device":"d_pc_y","locked_at":"2026-06-12T10:30:00Z","lock_ttl_seconds":300}}}
```

---

## 4. 限流响应

当用户触发限流(FR-055,per-user 50 次/分钟):

```yaml
ErrorPayload:
  code: "RATE_LIMITED"
  message: "操作太频繁,请稍候再试"
  retry_after_ms: 60000                  # 1 分钟后重试
```

H5 **必须**展示该提示,且**不**自动重试。

---

## 5. 错误兜底

| 错误码 | 用户提示 | H5 行为 |
|--------|----------|---------|
| `OUT_OF_SCOPE` | "我暂时只能帮您找优惠 / 查券包 / 下单,试试别的问题?" | 继续接收输入 |
| `RATE_LIMITED` | "操作太频繁,请稍候再试" | 禁用输入框 60s |
| `INTERNAL` | "抱歉,系统繁忙,请稍候再试" | 显示重试按钮 |
| `EXTERNAL_DOWN` | "推荐服务暂时不可用,试试其他品类?" | 引导用户改 query |
| `BOTH_DOWN` | "系统维护中,请稍候再试" | 显示重试按钮 |

---

## 6. 流式 + Envelope 顺序约定

主 Agent 在生成响应时:

1. 先推 `text_delta` chunk(可能多个,直到文本生成完毕)
2. 再推 `actions` chunk(若有按钮)
3. 再推 `envelope` chunk(完整结构化数据,必须在 `done` 之前)
4. 最后推 `done` chunk(带 final_meta)

**H5 必须**:
- 累积所有 `text_delta` 后再渲染聊天气泡(避免抖动);
- 把 `envelope` 与同一气泡绑定(用 `trace_id` 关联);
- `envelope.items` 渲染为商品卡,`envelope.actions` 渲染为按钮;
- `state_version` 用于本地缓存(乐观更新)。

---

## 7. Action 回调(H5 → 主 Agent POST /agent/action)

```yaml
ActionRequest:
  user_id: string
  session_id: string
  device_id: string
  action_id: string                      # 来自 Envelope.actions[i].action_id
  payload: dict[str, Any]                # 该 action 的 payload
  trace_id: string                       # 关联 id
```

**响应**:同 `ChatChunk`(SSE 流式)。H5 复用同一渲染管线。
