# Data Model: 优惠推荐 Agent (Promo Recommend Agent)

**Date**: 2026-06-12
**Status**: Phase 1 — Data Model
**Spec**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)

> 本文件锁定 Agent 系统内 / 与外部服务交互的所有核心实体的字段、关系、状态机与校验规则。**Agent 不拥有数据,只编排工具**——下述实体的持久化与一致性由各自的服务负责,Agent 端只在 Session State(Redis)中持有 view / cache。

---

## 1. 实体关系总览

```text
                          ┌─────────────────────┐
                          │   Session State     │  ← 主 Agent 持有(per user,Redis)
                          │   (per-user view)   │
                          └──────────┬──────────┘
                                     │ 引用
        ┌─────────────────┬──────────┼──────────┬────────────────┐
        │                 │          │          │                │
        ▼                 ▼          ▼          ▼                ▼
   Recommendation   Slots         Sort Key   Draft Order    Session Summary
   List (active)                                                  (compressed)
        │
        │ 包含
        ▼
   Recommendation Item (N 条)
        │
        │ 引用
        ▼
   Coupon / Store (4 种 content_type)
```

外部服务持有的实体(Agent 不直接持久化,通过服务 API 读写):
- **User Profile**(用户画像服务)
- **User Behaviour Sequence**(行为序列服务)
- **Owned Coupon**(用户资产查询服务)
- **Preference / Preference Store**(per-user 偏好)
- **Conversation Trace**(OLAP 列存,异步写入)
- **Order / Payment Result**(订单 / 收银台服务)
- **Sub-Agent Registry**(主 Agent 启动时读)

---

## 2. Session State(per-user,主 Agent 持有)

**存储**:Redis(`sess:{user_id}`)
**TTL**:24h(可配);**A-017** 跨多端共享;**FR-003** 按用户隔离

```yaml
SessionState:
  user_id: string                       # 用户 id
  session_id: string                    # 会话 id(用于 SSE 推送关联;与 user_id 解耦,便于多端)
  state_version: int                    # 单调递增,用于多端同步的 diff 比较
  last_active_device: string            # 最近活跃的 device id
  current_list: RecommendationList?     # 当前推荐列表(若有)
  draft_order: DraftOrder?              # 当前草稿订单(若有)
  slots: Slots                          # 最近的槽位
  sort_key: SortKey?                    # 当前排序键
  session_excludes: list[string]        # 本次会话的临时排除项(品牌 / 品类 / 商品 id)
  preference_overrides: list[string]    # 临时覆盖的持久化偏好(本轮内有效)
  session_summary: SessionSummary?      # 上下文压缩后的摘要(若有)
  compression_state:                    # 压缩状态
    compressed_turns: int               # 已被压缩的早期轮次数
    original_total_turns: int           # 压缩前的总轮次数
  last_intent: Intent                   # 最近一次意图分类结果
  multi_device_lock:                    # 多端互斥(FR-023b)
    holder_device: string?              # 持有"正在支付"锁的 device id
    locked_at: datetime?                # 加锁时间
    lock_ttl_seconds: int               # 锁 TTL(默认 300)
  created_at: datetime
  updated_at: datetime
```

---

## 3. Recommendation List

**存储**:Session State 内的子对象
**关系**:per user / per session 单实例

```yaml
RecommendationList:
  list_id: string                       # 唯一 id(UUID)
  items: list[RecommendationItem]       # 列表项(按当前 sort_key 排序)
  sort_key: SortKey                     # 排序键
  total_candidates: int                 # 候选集大小(原始,排序前)
  recall_strategy: string               # 召回策略:`es_keyword` | `es_vector` | `hybrid` | `llm_relax` | `cache_fallback`
  llm_rank_called: bool                 # 是否调用了 LLM 排序
  degradation_level: string             # `none` | `es_cache` | `no_llm_rank` | `error`(FR-012b / FR-014b)
  generated_at: datetime
  consumed_at: datetime                 # 最后一次被用户浏览的时间
```

---

## 4. Recommendation Item

**存储**:Session State 内的子对象 / H5 payload 内
**关系**:list 的 N 条

```yaml
RecommendationItem:
  id: string                            # 唯一 id
  content_type: enum                    # meituan_coupon | self_operated_coupon | discount_checkout | external_coupon
  title: string                         # 主标题
  subtitle: string?                     # 副标题
  image_url: string?                    # 图片
  price: decimal                        # 价格
  discount: decimal?                    # 折扣
  bound_store_ids: list[string]         # 绑定门店
  distance_meters: int?                 # 距用户距离
  validity_start: datetime
  validity_end: datetime
  deep_link: string                     # H5 深链
  is_new_user_badge: bool               # 新用户推荐标识(由 spec:Q5 决定 = false,字段保留以备未来)
  expires_soon: bool                    # 剩余 ≤ 7 天(用于"快过期"角标)
```

---

## 5. Slots(槽位)

**存储**:Session State 内的子对象
**关系**:主 Agent ↔ LP 子 Agent 之间的契约

```yaml
Slots:
  category: string?                     # 品类
  name: string?                         # 商家名称
  number: int?                          # 套餐人数
  time: TimeWindow?                     # 营业时间
  distance: int?                        # 距离(米)
  discount_keyword: string?             # 折扣关键词(由 LP 抽取)
  store_keyword: string?                # 门店关键词(由 LP 抽取)
  extras: dict[str, Any]                # 各垂直私有槽位(预留)

TimeWindow:
  start: datetime
  end: datetime
```

---

## 6. Sort Key(枚举)

```yaml
SortKey: enum
  - distance       # 按距离升序
  - popularity     # 按热度降序
  - price_asc      # 按价格升序
  - price_desc     # 按价格降序
  - model          # 推荐模型默认(综合)
```

---

## 7. Draft Order(草稿订单)

**存储**:Session State 内的子对象
**关系**:per session 0 或 1 实例
**状态机**:见 §14

```yaml
DraftOrder:
  order_id: string                      # 草稿订单 id
  user_id: string
  items: list[OrderItem]                # 商品列表(可多条,FR-025 支持多张券合并)
  applied_coupon_id: string?            # 使用的券 id
  total_amount: decimal                 # 总价
  status: OrderStatus                   # 状态机
  source: enum                          # `recommendation` | `coupon_wallet` | `manual`(溯源)
  created_at: datetime
  updated_at: datetime

OrderItem:
  item_id: string                       # 商品 / 券 id
  content_type: enum                    # 同 RecommendationItem.content_type
  title: string
  unit_price: decimal
  quantity: int                         # 数量
  subtotal: decimal
  bound_store_id: string?
```

---

## 8. Order Status(状态机)

```text
       ┌─────────┐
       │  draft  │ ← LP 工具 prepare_draft 后进入
       └────┬────┘
            │ update_draft(改数量 / 换品)
            ▼
       ┌──────────────────┐
       │  draft (修改中)  │ ← 任何 update_draft 重新进入
       └────┬─────────────┘
            │ confirm_and_pay
            ▼
       ┌────────────────────┐
       │ awaiting_payment   │ ← 进入此态时主 Agent 设多端互斥锁(FR-023b)
       └────┬───────────────┘
       ┌────┴────┐
       ▼         ▼
   ┌────────┐ ┌────────┐
   │ paid   │ │cancelled│
   └────────┘ └────────┘
       │
       │ 支付回调失败
       ▼
   ┌──────────┐
   │ payment_ │ ← 草稿保留,允许用户重试
   │  failed │
   └──────────┘
```

**OrderStatus 枚举**:`draft` | `awaiting_payment` | `paid` | `cancelled` | `payment_failed`

---

## 9. Coupon(券定义)

**存储**:由券服务持有;Agent 只读不写
**关系**:RecommendationItem.content_type ∈ {meituan_coupon, self_operated_coupon, external_coupon} 时,引用此实体

```yaml
Coupon:
  coupon_id: string
  title: string
  description: string
  bound_store_ids: list[string]
  eligibility_rules: list[EligibilityRule]
  per_user_limit: int
  total_quota: int
  claimed_count: int
  validity_start: datetime
  validity_end: datetime
  claim_status: enum                    # `claimable` | `claimed_out` | `expired`

EligibilityRule:
  rule_type: enum                       # `category` | `price_threshold` | `time_window` | `user_segment`
  params: dict[str, Any]
```

---

## 10. Owned Coupon(用户已持有的券)

**存储**:由"用户资产查询服务"持有;Agent 调用
**状态机**:见 §15

```yaml
OwnedCoupon:
  owned_id: string
  user_id: string
  coupon_id: string                     # 引用 Coupon
  status: OwnedCouponStatus             # 状态机
  claimed_at: datetime
  used_at: datetime?                    # 状态 = used 时有值
  used_order_id: string?                # 关联订单
  expire_at: datetime
  remaining_days: int                   # 剩余有效期(派生字段,UI 用于"快过期"角标)
  bound_order_id: string?
```

---

## 11. Owned Coupon Status(状态机)

```text
   ┌──────────────┐
   │ claimed_but_ │ ← 领券成功但尚未"激活"为可用的中间态
   │ unavailable  │   (例:外部券刚导入、待资格校验)
   └──────┬───────┘
          │ 资格校验通过 / 激活
          ▼
   ┌──────────────┐
   │  available   │ ← 可用
   └──────┬───────┘
       ┌──┴───┐
       ▼      ▼
   ┌──────┐ ┌────────┐
   │ used │ │expired │  ← used:核销完成;expired:过期未用
   └──────┘ └────────┘
```

**OwnedCouponStatus 枚举**:`claimed_but_unavailable` | `available` | `used` | `expired`

---

## 12. Preference(偏好项)

**存储**:Preference Store 服务
**TTL**:180d(显式) / 30d(隐式)

```yaml
Preference:
  preference_id: string
  user_id: string
  target_type: enum                     # `brand` | `category` | `item_id`
  target_value: string                  # 品牌名 / 品类名 / 商品 id
  direction: enum                       # `dislike` | `like`
  source: enum                          # `explicit` | `implicit`
  confidence: float?                    # 仅隐式(0.0~1.0)
  created_at: datetime
  expire_at: datetime                   # source=explicit → +180d;source=implicit → +30d
  override_active: bool                 # 本轮是否有临时覆盖
  override_expires_at: datetime?        # 临时覆盖失效时间
```

---

## 13. Session Summary(上下文压缩摘要)

**存储**:Redis(Session State 内子对象)
**触发**:FR-054(轮次 > 20 或字符 > 8000)
**生成**:独立 service(便宜模型)

```yaml
SessionSummary:
  summary_id: string
  covered_turns_range:                  # 覆盖的轮次范围
    from: int
    to: int
  total_turns_at_compression: int       # 压缩时总轮次
  user_intent_evolution: string         # 用户核心意图演变
  key_slot_changes: list[SlotChange]    # 关键槽位变化
  displayed_lists_summaries: list[string]  # 已展示列表的摘要
  key_actions: list[KeyAction]          # 关键动作(下单 / 改单 / 排除 / 排序)
  persistent_preferences: list[string]  # 持久化偏好项
  recent_turns: list[Turn]              # 最近 N 轮原样(不被压缩)
  generated_at: datetime
  failed_attempts: int                  # 压缩失败次数(累积)

SlotChange:
  slot_name: string
  old_value: Any
  new_value: Any
  at_turn: int

KeyAction:
  action_type: enum                     # `order` | `update_draft` | `exclude` | `sort` | `coupon_query`
  params: dict[str, Any]
  at_turn: int

Turn:
  turn_id: int
  role: enum                            # `user` | `assistant` | `tool`
  content: string                       # 原文(可能已被去标识)
  tool_calls: list[ToolCall]?           # 工具调用(若有)
```

---

## 14. Conversation Trace(会话回溯记录)

**存储**:OLAP 列存(异步,主 Agent 推消息队列 → 消费者写入)
**TTL**:6 个月(A-019)
**写入时机**:会话结束 OR 关键事件(支付成功 / 失败 / 草稿取消 / 列表无点击超时)

```yaml
ConversationTrace:
  trace_id: string                      # 主键
  user_id_hash: string                  # 脱敏(user id hash,不可逆)
  session_id: string
  started_at: datetime
  ended_at: datetime
  initial_query: string
  slot_extraction_trace: list[SlotChange]    # 槽位抽取轨迹
  candidate_set_size: int                    # ES 候选集大小
  recall_strategy: string                    # 同 RecommendationList
  llm_relax_triggered: bool                  # 是否触发联想召回
  top_k_returned: list[RecommendationItem]   # 实际返回的 top-K(用于归因)
  user_actions_trace: list[UserAction]       # 用户对列表的每一步动作
  final_state: FinalState                    # 最终态
  intent_switches: list[IntentSwitch]        # 同一会话内的意图切换
  compression_occurred: bool                 # 是否触发压缩
  compression_failures: int                  # 压缩失败次数
  result_outcome: enum                       # 成功 / 失败
  related_order_id: string?                  # 成功订单(若有)

UserAction:
  at_turn: int
  action_type: enum                     # `view` | `sort` | `exclude` | `order` | `update_draft` | `cancel` | `click_item`
  target_id: string?
  params: dict[str, Any]?

FinalState:
  state_type: enum                      # `success` | `draft_cancelled` | `payment_failed` | `no_click_session_end` | `user_abandoned`
  order_id: string?
  failure_reason: string?

IntentSwitch:
  from_intent: Intent
  to_intent: Intent
  at_turn: int
```

---

## 15. Intent(意图分类结果)

**存储**:Session State 内 + 主 Agent 内部流转
**枚举**:`local_promotion` | `order` | `coupon_wallet` | `points_mall` | `out_of_scope`

```yaml
Intent:
  intent_type: enum
  confidence: float                     # 0.0~1.0
  fallback_used: bool                   # 是否走了"低置信度兜底"
```

---

## 16. Sub-Agent Registry(子 Agent 注册表)

**存储**:主 Agent 启动时从配置 / 服务发现读取
**只读**

```yaml
SubAgentRegistryEntry:
  intent: string                        # 意图名
  sub_agent_id: string
  endpoint: string                      # gRPC endpoint
  version: string                       # semver
  enabled: bool
  fallback_message: string              # 不可用时的兜底文案

# 第一期配置示例:
- intent: local_promotion
  sub_agent_id: local-promo-agent
  endpoint: local-promo-agent:50051
  version: 1.0.0
  enabled: true

- intent: order
  sub_agent_id: local-promo-agent       # 共享 LP
  endpoint: local-promo-agent:50051
  version: 1.0.0
  enabled: true

- intent: coupon_wallet
  sub_agent_id: local-promo-agent       # 共享 LP
  endpoint: local-promo-agent:50051
  version: 1.0.0
  enabled: true

- intent: points_mall                   # 第二期,首期 enabled=false
  sub_agent_id: (空)
  endpoint: (空)
  version: (空)
  enabled: false
  fallback_message: "积分商城即将上线,敬请期待"
```

---

## 17. 关键校验规则(Validation Rules)

| 实体 | 规则 | 失败行为 |
|------|------|----------|
| DraftOrder | `total_amount >= 0` | 工具调用失败 |
| DraftOrder | `quantity >= 1` | 工具调用失败 |
| Preference | `expire_at > created_at` | 写入失败 |
| Preference | 显式偏好 180 天,隐式 30 天 | 由 Preference Store 校验 |
| RecommendationList | `len(items) <= top_K` | LP 内部截断 |
| RecommendationItem | `validity_end > validity_start` | 候选过滤掉 |
| Session State | 跨 user 不可读 | 主 Agent 内部强制按 user_id 持有 |
| 多端互斥锁 | TTL 5 分钟(可配) | 自动过期释放 |
| Conversation Trace | 不可包含 PII | 主 Agent 写入前过滤 |

---

## 18. 数据流(端到端)

### 18.1 用户输入 → 推荐列表

```text
H5 → Main Agent
  ├─ 接收:user query, session id, user id, device id, location
  ├─ 限流校验(FR-055, Redis INCR)
  ├─ 加载 Session State(Redis GET)
  ├─ 意图分类(Intent)
  ├─ 路由到 LP 子 Agent(gRPC)
  │
LP Sub-Agent
  ├─ 抽取槽位(Slots)
  ├─ 读取 Preference Store(显式 + 隐式,FR-019)
  ├─ ES 检索(关键词 + 向量双路;候选不足时触发联想召回 FR-017)
  │   └─ 降级:异常 → 缓存候选(FR-012b)
  ├─ 拉取用户画像 / 行为序列
  ├─ 调用推荐服务(候选集 + 用户上下文 → top-K)
  │   └─ 降级:异常 → 跳过 LLM 排序,用热度榜(FR-014b)
  ├─ 券门店资格 / 单人限额补全
  ├─ 内部券与门店合并
  └─ 返回 Envelope(items, summary, slots_used, sort_key, actions?)
  │
Main Agent
  ├─ 更新 Session State(current_list, slots, sort_key)
  ├─ 触发 SSE 推送到所有活跃 device(D-004)
  └─ 返回 H5:流式文本 + Envelope payload
```

### 18.2 用户下单 → 支付

```text
H5 → Main Agent
  ├─ 限流校验(敏感操作更严格)
  ├─ 加载 Session State
  ├─ 路由到 LP(order 意图)
  │
LP Sub-Agent
  ├─ 调用 prepare_draft(列表引用 / 名称引用 / id 引用)
  │   └─ 歧义 → 最多 1 次追问
  ├─ 写入 DraftOrder(status=draft)
  └─ 返回 Envelope
  │
[用户对话:改数量 / 换品 / 取消 / 确认]
  └─ update_draft / cancel_draft / confirm_and_pay
  │
Main Agent(confirm_and_pay 时)
  ├─ 互斥校验(FR-023b):Redis SETNX 草稿锁,TTL 5 分钟
  │   └─ 锁已被另一端持有 → 拒绝,提示用户
  ├─ LP 调 pre_payment_validate(FR-023):库存 / 资格 / 限额
  │   └─ 失效 → 友好重选流程
  ├─ 路由到 H5 收银台(不直接调)
  │
H5 收银台 → 用户支付 → 回调
  │
Main Agent
  ├─ 支付结果回传 → Session State 写支付结果
  ├─ 释放互斥锁
  ├─ 写 Conversation Trace(FR-053,异步)
  └─ 返回 H5:成功/失败 + order id / 原因
```

### 18.3 排除 + 持久化

```text
H5 → Main Agent
  ├─ "我不要瑞幸"
  │
LP Sub-Agent
  ├─ 调用 exclude_items(brand="瑞幸")
  ├─ 当前列表过滤(不持久化)
  └─ 返回 Envelope(过滤后列表 + 标记"已过滤,需追问")
  │
Main Agent
  ├─ 更新 Session State(session_excludes += "瑞幸")
  ├─ 渲染 H5 actions:["是,以后都不再推荐", "本次就好"]
  │
[用户选择]
  ├─ "是" → Main Agent 调 Preference Store 写入(显式 dislike,180d)
  └─ "本次就好" → 仅保留 session_excludes,会话结束失效
```

### 18.4 上下文压缩(异步触发)

```text
Main Agent
  ├─ 每轮 LLM 调用前:检查字符数 / 轮次
  ├─ 触发 → 调用压缩 service(D-005)
  │   ├─ 成功 → Session State 写 session_summary + recent_turns
  │   └─ 失败 → 降级:丢早期轮次,失败信息入 trace
  └─ 下一轮 LLM 调用:session_summary + recent_turns 拼接输入
```

### 18.5 失败交易回溯

```text
Main Agent
  ├─ 监听"会话结束 / 关键事件"事件
  ├─ 组装 Conversation Trace(D-006)
  ├─ 异步推到消息队列
  │   └─ 队列消费者写入 OLAP 列存
  └─ 写失败不阻塞用户响应
```

---

## 19. 实体间引用关系图(简化)

```text
SessionState (per user, Redis)
├── current_list → RecommendationList
│   └── items[] → RecommendationItem (引用 Coupon / Store)
├── draft_order → DraftOrder (引用 Coupon)
├── slots → Slots
├── session_summary → SessionSummary
│   └── recent_turns[] → Turn
├── last_intent → Intent
└── multi_device_lock → (device_id, locked_at)

SubAgentRegistry (启动时读)
└── entries[] → SubAgentRegistryEntry

ConversationTrace (OLAP, 异步)
├── top_k_returned[] → RecommendationItem
├── user_actions_trace[] → UserAction
├── intent_switches[] → IntentSwitch
└── final_state → FinalState

外部服务(Agent 不直接持有):
- User Profile (用户画像服务)
- User Behaviour Sequence (行为序列服务)
- Owned Coupon (用户资产查询服务)
- Preference (Preference Store)
- Order / Payment (订单 / 收银台服务)
- Coupon (券服务,只读)
- Store (门店服务,只读)
```
