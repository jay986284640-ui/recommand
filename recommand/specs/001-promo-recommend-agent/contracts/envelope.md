# Contract: 统一响应 Envelope

**Owner**: 主 Agent + 所有子 Agent
**Date**: 2026-06-12
**Status**: Phase 1 — 契约
**Spec**: [spec.md §设计——交互方式](../spec.md)

> 每个子 Agent 在响应主 Agent 时,以及主 Agent 在响应 H5 时,都**必须**用本 Envelope 包裹结果。这是 spec FR-041 的具体落地。

---

## 1. Envelope Schema(子 Agent → 主 Agent)

```yaml
Envelope:
  # 必填
  summary: string                       # 面向用户的一句话(已使用用户语言)
  slots_used: Slots                      # 实际生效的槽位

  # 推荐列表场景
  items: list[RecommendationItem]?       # 结果列表(若有)
  sort_key: SortKey?                     # 当前排序键

  # 排序 / 排除 / 改单 / 券包等场景(可与 items 互斥)
  actions: list[Action]?                 # H5 按钮建议
  follow_up: string?                     # 追问话术(主 Agent 可原样回传)

  # 调试 / 追踪
  trace_meta: TraceMeta                  # 关联 id、降级标记等

TraceMeta:
  trace_id: string                       # 关联 id(FR-051)
  degradation_level: string              # `none` | `es_cache` | `no_llm_rank` | `error`
  llm_call_count: int                    # 本轮 LLM 调用次数(SC-008 监控)
  duration_ms: int                       # 子 Agent 处理时长
```

---

## 2. 字段必填规则

| 场景 | summary | slots_used | items | sort_key | actions | follow_up |
|------|---------|------------|-------|----------|---------|-----------|
| 推荐 / 发现 | ✅ | ✅ | ✅ | ✅ | optional | optional |
| 排序 | ✅(说明新排序) | ✅ | ❌ | ✅ | optional | ❌ |
| 排除 | ✅(说明已过滤) | ✅ | ✅(过滤后) | unchanged | ✅(持久化追问) | optional |
| 下单草稿 | ✅ | ✅ | ❌(草稿在 SessionState) | unchanged | ✅(确认支付) | optional |
| 改单 | ✅ | ✅ | unchanged | unchanged | optional | optional |
| 取消 | ✅ | ✅ | unchanged | unchanged | optional | ❌ |
| 支付结果 | ✅ | ✅ | unchanged | unchanged | optional | ❌ |
| 券包列表 | ✅ | ❌(非发现) | ✅(券) | optional | ✅(查详情) | optional |
| 券详情 | ✅ | ❌ | ❌ | ❌ | optional | optional |
| 券对比 | ✅ | ❌ | ❌(对比卡由 H5 渲染) | ❌ | optional | optional |
| out_of_scope | ✅(引导话术) | ❌ | ❌ | ❌ | optional | ❌ |

**通用规则**:`summary` 永远必填(用户看到的全部文字);`actions` 在需要用户做选择时必填;`follow_up` 仅在需要进一步消解时填写。

---

## 3. Action Schema(H5 按钮)

```yaml
Action:
  action_id: string                      # 唯一 id
  label: string                          # 按钮文案
  style: enum                            # `primary` | `secondary` | `danger` | `ghost`
  payload: dict[str, Any]                # 用户点击时,H5 回调主 Agent 的载荷
  expires_after_turns: int?              # 若指定,该 action 在 N 轮后自动失效
```

**示例**:
```yaml
# 排除后追问持久化
- action_id: persist_exclude_brand_x
  label: "是,以后都不再推荐"
  style: primary
  payload:
    intent: persist_preference
    target_type: brand
    target_value: "瑞幸"
    direction: dislike
    source: explicit

- action_id: skip_persist
  label: "本次就好"
  style: secondary
  payload:
    intent: skip_persist
```

---

## 4. 向后兼容(Versioning)

- Envelope 是 **MAJOR.MINOR** 演进:
  - **MAJOR** 变更(字段重命名 / 删除)需要主 Agent 同步升级;
  - **MINOR** 变更(新增字段)向后兼容,旧主 Agent 忽略未知字段;
- 子 Agent 端版本由 Sub-Agent Registry 标记;主 Agent 调用时按版本路由。

---

## 5. 错误响应

子 Agent 在异常时**不**返回异常堆栈;改用:

```yaml
Envelope:
  summary: "抱歉,系统繁忙,请稍候再试"
  slots_used: { ... 原样 ... }
  trace_meta:
    trace_id: "..."
    degradation_level: "error"
    error_code: "ES_DOWN" | "RANK_DOWN" | "BOTH_DOWN" | "INTERNAL"
    error_reason: "人类可读原因(可选)"
  actions:
    - action_id: retry
      label: "重试"
      style: primary
      payload: { intent: retry }
```

`degradation_level = error` 走 FR-014b 的错误页;`degradation_level = es_cache` 或 `no_llm_rank` 仍返回列表(降级)。
