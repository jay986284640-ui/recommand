# Quickstart: 优惠推荐 Agent 端到端验证

**Date**: 2026-06-12
**Status**: Phase 1 — 验证指南
**Spec**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)

> 本文件给出**可运行的端到端验证场景**,作为 `/speckit-implement` 阶段的 smoke / e2e 入口。**不**包含实现代码;只列出"跑通什么 + 怎么验"。

---

## 0. 验证前置

### 0.1 服务栈(本地 / 测试环境)

| 服务 | 端点 | 启动方式 |
|------|------|----------|
| 主 Agent | `localhost:8080` (HTTP) / `localhost:8081` (SSE) | `docker compose up main-agent` |
| LP 子 Agent | `localhost:50051` (gRPC) | `docker compose up local-promo-agent` |
| Redis | `localhost:6379` | `docker compose up redis` |
| Elasticsearch | `localhost:9200` | `docker compose up elasticsearch` |
| Mock LLM 服务 | `localhost:9000` | `docker compose up mock-llm`(用 mock-llm 模拟大模型平台) |
| Mock 外部服务 | `localhost:9100` | `docker compose up mock-externals`(模拟推荐 / 偏好 / 用户资产 / 收银台) |

### 0.2 初始化数据

```bash
# 初始化 ES 索引(商品 + 门店)
curl -X POST localhost:9200/_bulk --data-binary @fixtures/products.ndjson
curl -X POST localhost:9200/_bulk --data-binary @fixtures/stores.ndjson

# 注入 mock 数据
python scripts/seed_mock_data.py
#  - 50 个商品(美团券 / 自拓展券 / 买单 / 外部券)
#  - 20 个门店
#  - 3 个用户(u_test_new, u_test_active, u_test_with_history)
```

---

## 1. 核心场景验证

### 场景 1:对话式发现(P1,US 1)

**目标**:验证自然语言查询 → 推荐列表返回。

```bash
# 调用
curl -X POST localhost:8080/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u_test_active",
    "session_id": "s_quickstart_1",
    "device_id": "d_test",
    "text": "附近有什么咖啡优惠"
  }'

# 预期:
# - HTTP 200,SSE 流式返回
# - 最后一个 chunk.envelope.items 长度 ≥ 3
# - 响应中含 meituan_coupon / self_operated_coupon 等多种 content_type
# - envelope.slots_used 含 category=咖啡
# - envelope.sort_key = "model"(默认)
# - final_meta.llm_call_count ≤ 2
# - 端到端 p95 ≤ 4s
```

**断言**:
- [ ] 返回 ≥ 3 条推荐
- [ ] 至少 2 种 content_type
- [ ] trace_id 可在 Redis / 日志中查到
- [ ] SSE 推送后,另一端订阅 session stream 能收到 state_diff

---

### 场景 2:排除 + 持久化追问(Q1,FR-018,US 5)

**目标**:验证"我不要瑞幸" → 过滤 + 追问持久化。

```bash
# 第一步:触发排除
curl -X POST localhost:8080/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u_test_active",
    "session_id": "s_quickstart_2",
    "device_id": "d_test",
    "text": "我不要瑞幸"
  }'

# 预期:
# - envelope.summary 含"已过滤"提示
# - envelope.items 中无瑞幸相关项
# - envelope.actions 至少含 2 个:["是,以后都不再推荐", "本次就好"]

# 第二步:用户点"是,以后都不再推荐"(模拟 action 回调)
curl -X POST localhost:8080/agent/action \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u_test_active",
    "session_id": "s_quickstart_2",
    "device_id": "d_test",
    "action_id": "persist_exclude_brand_x",
    "payload": {
      "intent": "persist_preference",
      "target_type": "brand",
      "target_value": "瑞幸",
      "direction": "dislike",
      "source": "explicit"
    }
  }'

# 预期:
# - Preference Store 中写入 1 条显式 dislike(180 天 TTL)
# - 后续该用户查询咖啡,瑞幸不再出现

# 第三步:验证持久化生效
curl -X POST localhost:8080/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u_test_active",
    "session_id": "s_quickstart_2_new",      # 新会话
    "device_id": "d_test",
    "text": "附近有什么咖啡优惠"
  }'

# 预期:
# - 瑞幸相关项仍不出现(跨会话生效)
# - envelope.trace_meta 中能看到 preference filter applied
```

**断言**:
- [ ] 第一步:envelope.actions 包含 2 个按钮
- [ ] 第二步:Preference Store 中 `u_test_active` 出现新偏好
- [ ] 第三步:新会话中瑞幸不出现
- [ ] Conversation Trace 中"排除事件"被记录

---

### 场景 3:联想召回(Q3,FR-017,US 1 场景 7)

**目标**:验证小众品类 → LLM 扩词 → ES 双路召回。

```bash
# 准备:故意查询一个不在 ES 索引中的冷门品类
curl -X POST localhost:8080/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u_test_active",
    "session_id": "s_quickstart_3",
    "device_id": "d_test",
    "text": "想吃个老北京豆汁"
  }'

# 预期:
# - ES 直接检索"老北京豆汁"可能返回 0 条
# - 触发联想召回(FR-017):LLM 扩词为"豆汁 / 北京小吃 / 传统早餐 / 护国寺小吃"等
# - ES 用扩词做关键词+向量双路召回
# - 合并去重后,返回相关小吃
# - envelope.trace_meta.recall_strategy = "llm_relax"
```

**断言**:
- [ ] 返回 ≥ 1 条相关推荐(传统小吃 / 早餐 / 北京特色)
- [ ] trace_meta.recall_strategy = "llm_relax"
- [ ] 没有任何商品不在 ES 召回结果中(幻觉护栏)

---

### 场景 4:下单闭环(P2,US 2)

**目标**:验证列表 → 草稿 → 改数量 → 互斥 → 支付。

```bash
# 第一步:获取列表(同场景 1)
# 第二步:用户说"下第 2 个"
curl -X POST localhost:8080/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "u_test_active",
    "session_id": "s_quickstart_4",
    "device_id": "d_test",
    "text": "下第 2 个"
  }'

# 预期:
# - DraftOrder 创建,status = "draft"
# - envelope.actions 含"确认支付"按钮

# 第三步:用户说"改成 3 份"
curl -X POST localhost:8080/agent/chat -d '{
  "user_id": "u_test_active", "session_id": "s_quickstart_4",
  "device_id": "d_test", "text": "改成 3 份"
}'

# 预期:DraftOrder.quantity = 3

# 第四步:模拟另一端同时进入支付(测试互斥)
# 在 device_id="d_test_other" 上同时说"确认支付"
# 预期:第一个调用成功,第二个被拒(LOCK_HELD)

# 第五步:确认支付
curl -X POST localhost:8080/agent/chat -d '{
  "user_id": "u_test_active", "session_id": "s_quickstart_4",
  "device_id": "d_test", "text": "确认支付"
}'

# 预期:
# - 主 Agent 校验互斥锁(单端通过)
# - LP 调 pre_payment_validate
# - 路由到 H5 收银台(此处 mock 收银台直接返回 success)
# - 回调后 DraftOrder.status = "paid"
# - Conversation Trace 写入(状态 = success)
```

**断言**:
- [ ] 草稿状态机正确转移
- [ ] 多端并发时只有一个能进入 awaiting_payment
- [ ] 支付成功后 Conversation Trace 含 order_id

---

### 场景 5:券包管理(P3,US 7)

**目标**:验证"我的券包" + 状态过滤。

```bash
# 准备:确保 u_test_active 有 3 张可用券 + 1 张已用 + 1 张过期
python scripts/seed_user_coupons.py --user u_test_active

# 第一步:查询券包
curl -X POST localhost:8080/agent/chat -d '{
  "user_id": "u_test_active", "session_id": "s_quickstart_5",
  "device_id": "d_test", "text": "看看我的券包"
}'

# 预期:
# - envelope.items 是 OwnedCoupon 列表
# - 状态分组:可用(3) / 已用(1) / 过期(1)
# - 快过期券(剩余 ≤ 7 天)有 expires_soon = true

# 第二步:过滤"我还能用的券"
curl -X POST localhost:8080/agent/chat -d '{
  "user_id": "u_test_active", "session_id": "s_quickstart_5",
  "device_id": "d_test", "text": "我还能用的券有哪些"
}'

# 预期:仅 3 张 available 券返回
```

**断言**:
- [ ] 默认查询返回 5 张(3 可用 + 1 已用 + 1 过期)
- [ ] "我还能用的"仅返回 3 张 available
- [ ] 快过期券角标正确

---

### 场景 6:对话式重排(P4,US 3)

**目标**:验证 4 种排序键。

```bash
# 准备:在 s_quickstart_6 上先获得一张列表(同场景 1)
# 验证:对同一列表发 4 个排序指令,各响应 sort_key 不同
for SORT in "按距离排" "按热度排" "按价格排" "综合"; do
  curl -X POST localhost:8080/agent/chat -d "{
    \"user_id\": \"u_test_active\", \"session_id\": \"s_quickstart_6\",
    \"device_id\": \"d_test\", \"text\": \"$SORT\"
  }"
done

# 预期:
# - sort_key 依次为 distance / popularity / price_asc / model
# - items 内容集合完全一致(只是顺序变)
# - 响应文案中明确告知排序键
```

**断言**:
- [ ] 4 个 sort_key 都被正确识别
- [ ] 列表内容集合一致(SC-005)
- [ ] 响应文案明示排序键

---

### 场景 7:上下文压缩(P6,US 8)

**目标**:验证长会话触发压缩 + 降级。

```bash
# 模拟 30 轮对话(超过默认 20 轮阈值)
python scripts/simulate_long_session.py --user u_test_active --turns 30

# 检查 Redis 中 session state
redis-cli GET sess:u_test_active | jq .session_summary

# 预期:
# - session_summary 存在
# - recent_turns 数组长度 < 20(最近 N 轮)
# - summary 字段含 user_intent_evolution / key_actions 等
```

**断言**:
- [ ] 压缩触发后,Session Summary 字段齐全
- [ ] 最近 N 轮原样保留
- [ ] 压缩失败(把 mock-llm 关闭)→ 降级为丢早期轮次
- [ ] 用户在第 30 轮仍能引用"我之前说的 X"——摘要保留了关键信息

---

### 场景 8:失败交易回溯(P7,US 6)

**目标**:验证未完成交易的回溯写入。

```bash
# 模拟:用户走到草稿订单后不支付,直接关闭
python scripts/simulate_abandoned_session.py --user u_test_active

# 检查 OLAP 存储
clickhouse-client --query "SELECT * FROM conversation_trace WHERE user_id_hash = '...' ORDER BY started_at DESC LIMIT 1 FORMAT Vertical"

# 预期:
# - 1 条 trace 记录
# - final_state.state_type = "user_abandoned" 或 "no_click_session_end"
# - 含完整的 slot_extraction_trace / top_k_returned / user_actions_trace
```

**断言**:
- [ ] 异步写入不阻塞主流程
- [ ] 写入失败(把消息队列挂掉)→ 用户响应不受影响
- [ ] trace 不含 PII
- [ ] 6 个月后自动过期(A-019)

---

## 2. 边界 / 异常场景验证

### E-1:超出范围查询

```bash
curl -X POST localhost:8080/agent/chat -d '{
  "user_id": "u_test_active", "session_id": "s_e1",
  "device_id": "d_test", "text": "今天天气怎么样"
}'
# 预期:envelope.summary 含"我暂时只能帮您找优惠..."引导话术(SC-007)
```

### E-2:ES 故障降级(FR-012b)

```bash
# 关闭 ES
docker stop elasticsearch

curl -X POST localhost:8080/agent/chat -d '{
  "user_id": "u_test_active", "session_id": "s_e2",
  "device_id": "d_test", "text": "附近有什么咖啡优惠"
}'

# 预期:
# - envelope.trace_meta.degradation_level = "es_cache"
# - 仍返回列表(从缓存)
# - 响应中标"已启用降级,可能不是最新"
# - 告警触发
```

### E-3:推荐服务故障降级(FR-014b)

```bash
# 关闭推荐服务
docker stop mock-recommendation

curl -X POST localhost:8080/agent/chat -d '{
  "user_id": "u_test_active", "session_id": "s_e3",
  "device_id": "d_test", "text": "附近有什么咖啡优惠"
}'

# 预期:
# - envelope.trace_meta.degradation_level = "no_llm_rank"
# - 仍返回列表(用热度榜规则排序)
# - 响应中标"已启用降级,推荐精度下降"
```

### E-4:两路全挂(FR-014b 错误页)

```bash
docker stop elasticsearch mock-recommendation

curl -X POST localhost:8080/agent/chat -d '{
  "user_id": "u_test_active", "session_id": "s_e4",
  "device_id": "d_test", "text": "附近有什么咖啡优惠"
}'

# 预期:
# - envelope.trace_meta.degradation_level = "error"
# - 不返回列表(避免空列表伪装)
# - 返回友好错误 + "重试"按钮
```

### E-5:限流触发(FR-055)

```bash
# 模拟 1 分钟内 60 次输入
python scripts/flood_requests.py --user u_test_active --count 60

# 预期:
# - 前 50 次成功
# - 后 10 次返回 RATE_LIMITED 错误
# - H5 显示"操作太频繁,请稍候再试"
# - 1 分钟后自动恢复
```

### E-6:多端并发下单(FR-023b)

```bash
# 在两个 device 上同时说"确认支付"
curl -X POST localhost:8080/agent/chat -d '{
  "user_id": "u_test_active", "session_id": "s_e6",
  "device_id": "d_test_a", "text": "确认支付"
}' &
curl -X POST localhost:8080/agent/chat -d '{
  "user_id": "u_test_active", "session_id": "s_e6",
  "device_id": "d_test_b", "text": "确认支付"
}' &

# 预期:
# - 一个 device 成功进入支付
# - 另一个被拒,提示"另一端正在支付"
# - Redis 上的 multi_device_lock 只有一份
```

### E-7:删除我的偏好(FR-019b)

```bash
# 假设 u_test_active 已有 1 条显式 dislike(场景 2 写入)
curl -X POST localhost:8080/agent/action -d '{
  "user_id": "u_test_active", "session_id": "s_e7",
  "device_id": "d_test",
  "action_id": "delete_my_preferences",
  "payload": {"intent": "delete_all_preferences"}
}'

# 验证 1 分钟内 Preference Store 中该 user 无任何偏好
# 验证:新查询中瑞幸出现(偏好已清除)
```

### E-8:无位置的新用户(FR-014c)

```bash
# 准备:用全新用户 u_test_new(无画像 / 无行为)
curl -X POST localhost:8080/agent/chat -d '{
  "user_id": "u_test_new", "session_id": "s_e8",
  "device_id": "d_test", "text": "有什么优惠"
}'

# 预期:
# - 仍返回列表(走全站热度榜)
# - 响应中**不**含"新用户"角标(spec Q5 选择 B)
# - envelope.trace_meta.degradation_level = "none" 但 llm_rank_called = false
```

---

## 3. 性能与稳定性

### P-1:延迟基线

```bash
# 跑 1000 次"对话式发现"压测
python scripts/load_test.py --scenario discovery --qps 50 --duration 60s

# 验证:p95 < 4s, p99 < 6s
```

### P-2:成本基线

```bash
# 检查 LLM 调用次数分布
python scripts/cost_audit.py --duration 24h

# 验证:典型推荐轮次 LLM 调用次数 P95 ≤ 2
```

### P-3:隔离性(SC-009)

```bash
# 两个用户同时打开
python scripts/test_isolation.py

# 验证:
# - 用户的 session state 完全隔离
# - 跨用户读取 / 写入均被拒
```

---

## 4. 自动化集成

### 4.1 单元测试(per service)

```bash
cd agent-platform/main-agent
pytest tests/unit/ -v

cd ../local-promo-agent
pytest tests/unit/ -v
```

### 4.2 契约测试(per integration)

```bash
cd agent-platform/main-agent
pytest tests/contract/ -v
# 与 Preference / 用户画像 / ES / 推荐服务 / 收银台 的契约
```

### 4.3 端到端(场景 1~8 + E-1~E-8)

```bash
cd agent-platform
pytest tests/e2e/ -v --scenario=quickstart
```

### 4.4 冒烟(降级路径)

```bash
pytest tests/smoke/ -v
# FR-012b / FR-014b 的降级路径必须有覆盖
```

---

## 5. 验证清单(交付门)

Phase 1 设计的"可交付"必须满足:

- [ ] 场景 1~8 + E-1~E-8 全部 ✅
- [ ] 性能基线(p95 < 4s,LlmCallCount P95 ≤ 2)
- [ ] 隔离性测试 ✅
- [ ] 降级冒烟 ✅
- [ ] 所有契约测试 ✅
- [ ] Constitution Check 通过(I~V 五项)

进入 `/speckit-tasks` 阶段时,本文件应作为"哪些场景必须有自动化 e2e 覆盖"的总输入。
