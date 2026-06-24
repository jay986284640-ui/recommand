---
description: "Task list for 优惠推荐 Agent (Promo Recommend Agent)"
---

# Tasks: 优惠推荐 Agent (Promo Recommend Agent)

**Input**: Design documents from `/opt/recommand/recommand/specs/001-promo-recommend-agent/`
- [plan.md](./plan.md) · [spec.md](./spec.md) · [research.md](./research.md) · [data-model.md](./data-model.md) · [contracts/](./contracts/) · [quickstart.md](./quickstart.md)

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Constitution III (Test-First) is non-negotiable. **每个用户故事必须先写测试并确认失败,再写实现**。

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

**Service split** (per plan.md):
- `agent-platform/main-agent/` — 主 Agent(意图分类、会话状态、限流、压缩、Trace、多端同步)
- `agent-platform/local-promo-agent/` — LP 子 Agent(推荐 / 下单 / 券包 / 排除 四大工具层)
- `contracts/` — 共享契约(Pydantic / proto)

**Priority order (per spec.md)**: P1 → P2 → P3 → P4 → P5 → P6 → P7 → P8

## Format: `[ID] [P?] [Story] Description with file path`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US5, US6, US7, US8)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure (both services + shared contracts + dev infra)

- [ ] T001 Create monorepo structure: `agent-platform/main-agent/`, `agent-platform/local-promo-agent/`, `contracts/`, `deploy/`, `tests/`
- [ ] T002 [P] Initialize `agent-platform/main-agent/` Python project with FastAPI / Pydantic / pytest / grpcio / redis / opentelemetry deps in `agent-platform/main-agent/pyproject.toml`
- [ ] T003 [P] Initialize `agent-platform/local-promo-agent/` Python project with grpcio / Pydantic / pytest / elasticsearch / httpx deps in `agent-platform/local-promo-agent/pyproject.toml`
- [ ] T004 [P] Create `contracts/proto/local_promo_agent.proto` matching `contracts/sub-agent-call.md` (gRPC service definition + messages)
- [ ] T005 [P] Generate Python stubs from proto: `agent-platform/local-promo-agent/src/grpc_gen/` and `agent-platform/main-agent/src/grpc_gen/`
- [ ] T006 [P] Create `docker-compose.yml` with: redis, elasticsearch (8.x with dense_vector), mock-llm, mock-externals (recommendation / preference / user-asset / payment), main-agent, local-promo-agent
- [ ] T007 [P] Configure ruff + black + mypy + isort in `pyproject.toml` for both services
- [ ] T008 [P] Create `contracts/envelope.py` Pydantic models matching `contracts/envelope.md` (Envelope, Action, TraceMeta, ErrorPayload)
- [ ] T009 [P] Create `contracts/tool_schemas/` Pydantic models for all 13 LP tools (per `contracts/sub-agent-call.md §5`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that **MUST** be complete before ANY user story can start. Constitution III / IV / V 五项检查的所有横向能力都集中在这里。

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T010 [P] Implement Envelope serialization (to_dict / from_dict / to_json / from_json with MAJOR.MINOR versioning) in `contracts/envelope.py` (FR-041)
- [ ] T011 [P] Contract test: Envelope round-trip preserves all fields in `tests/contract/test_envelope.py` (FR-041)
- [ ] T012 [P] Contract test: Envelope backward compatibility (MINOR changes ignored by old consumers) in `tests/contract/test_envelope_versioning.py` (FR-041)
- [ ] T013 [P] Implement OpenTelemetry SDK + `trace_id` middleware in `agent-platform/main-agent/src/observability/otel.py` (FR-051:关联 id 贯穿)
- [ ] T014 [P] Implement structured logging with PII redaction in `agent-platform/main-agent/src/observability/logging.py`
- [ ] T015 [P] Implement Session State Redis client in `agent-platform/main-agent/src/session/redis_client.py` (D-003: per-user, JSON 序列化)
- [ ] T016 [P] Implement `SessionState` Pydantic model in `agent-platform/main-agent/src/session/state.py` (per data-model §2)
- [ ] T017 [P] Implement Sub-Agent Registry in `agent-platform/main-agent/src/registry/registry.py` (FR-040, data-model §16)
- [ ] T018 [P] Implement multi-device Redis lock in `agent-platform/main-agent/src/multi_device/lock.py` (FR-003 / FR-023b, D-004)
- [ ] T019 [P] Implement per-user rate limiter (Redis counter) in `agent-platform/main-agent/src/ratelimit/limiter.py` (FR-055, D-009)
- [ ] T020 [P] Implement SSE streaming client for H5 sync in `agent-platform/main-agent/src/api/sse.py` (D-004, h5-payload §3)
- [ ] T021 [P] Implement H5 chat API endpoint skeleton in `agent-platform/main-agent/src/api/chat.py` (POST /agent/chat, contracts/h5-payload.md)
- [ ] T022 [P] Implement H5 action callback endpoint skeleton in `agent-platform/main-agent/src/api/action.py` (POST /agent/action, contracts/h5-payload.md)
- [ ] T023 [P] Implement gRPC server skeleton in `agent-platform/local-promo-agent/src/grpc_server.py` (InvokeTool handler)
- [ ] T024 [P] Implement circuit breaker (pybreaker wrapper) in `agent-platform/local-promo-agent/src/degradation/breaker.py` (D-008)
- [ ] T025 [P] Implement error code registry in `contracts/error_codes.py` (per `sub-agent-call.md §6`)
- [ ] T026 [P] Setup ES client + dense_vector helpers in `agent-platform/local-promo-agent/src/tools/recommend/es_client.py` (D-007)
- [ ] T027 [P] Setup seed script `scripts/seed_mock_data.py` (50 products / 20 stores / 3 users, per quickstart §0.2)
- [ ] T028 [P] Setup seed script `scripts/seed_user_coupons.py` (3 available + 1 used + 1 expired per user)

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 — 对话式本地优惠发现 (Priority: P1) 🎯 MVP

**Goal**: 用户输入自然语言查询 → 返回 ≥ 3 条个性化推荐列表,延迟 p95 ≤ 4s,LLM 调用次数 ≤ 2。

**Independent Test**: 跑 `quickstart.md` 场景 1 + 场景 3(联想召回)+ 场景 8(失败回溯在本阶段不写,只覆盖发现路径)。E2E 测试通过 + 性能基线满足即可视为 US1 完成。

### Tests for User Story 1 ⚠️ Write FIRST, ensure they FAIL

- [ ] T029 [P] [US1] E2E test: conversational discovery returns 3+ items in `tests/e2e/test_discovery.py` (scenario 1)
- [ ] T030 [P] [US1] E2E test: LLM relax recall for cold category in `tests/e2e/test_llm_relax.py` (scenario 3, FR-017)
- [ ] T031 [P] [US1] E2E test: out-of-scope returns graceful redirect in `tests/e2e/test_out_of_scope.py` (SC-007, FR-011, scenario E-1)
- [ ] T032 [P] [US1] Contract test: ES 双路召回 (keyword + vector) in `agent-platform/local-promo-agent/tests/contract/test_es_search.py` (FR-012, FR-017)
- [ ] T033 [P] [US1] Contract test: recommendation service integration in `agent-platform/local-promo-agent/tests/contract/test_recommendation_service.py` (FR-014)
- [ ] T034 [P] [US1] Smoke test: ES down → cache fallback in `agent-platform/local-promo-agent/tests/smoke/test_es_degradation.py` (FR-012b, scenario E-2)
- [ ] T035 [P] [US1] Smoke test: recommendation service down → skip LLM rank in `agent-platform/local-promo-agent/tests/smoke/test_rank_degradation.py` (FR-014b, scenario E-3)
- [ ] T036 [P] [US1] Unit test: slot extraction (5 slots + LLM fallback) in `agent-platform/local-promo-agent/tests/unit/test_slot_extraction.py` (FR-010)
- [ ] T037 [P] [US1] Unit test: intent classifier routes local_promotion / out_of_scope in `agent-platform/main-agent/tests/unit/test_intent_classifier.py` (FR-001, FR-011)

### Additional Tests for User Story 1 (C1 SC compliance + C2 FR-014c)

- [ ] T038 [P] [US1] Eval: recall rate ≥ 90% + constraint satisfaction ≥ 95% on labeled queries in `tests/eval/test_recall_quality.py` (SC-002)
- [ ] T039 [P] [US1] Eval: intent classification precision ≥ 95% on labeled set in `tests/eval/test_intent_precision.py` (SC-003)
- [ ] T040 [P] [US1] Compliance: 100% out-of-scope returns graceful redirect (asserts no error, no list) in `tests/compliance/test_out_of_scope_coverage.py` (SC-007)
- [ ] T041 [P] [US1] Implement new-user fallback (skip LLM rank, hot list, no badge) in `agent-platform/local-promo-agent/src/recommend/new_user.py` (FR-014c, A-009)
- [ ] T042 [P] [US1] E2E: new user without profile returns hot list without "新用户" badge in `tests/e2e/test_new_user.py` (FR-014c, scenario E-8)

### Implementation for User Story 1

- [ ] T043 [P] [US1] Implement slot extraction in `agent-platform/local-promo-agent/src/tools/recommend/slot_extractor.py` (FR-010)
- [ ] T044 [P] [US1] Implement `search_candidates` tool (ES keyword + vector 双路 + merge) in `agent-platform/local-promo-agent/src/tools/recommend/search.py` (FR-012, D-007)
- [ ] T045 [P] [US1] Implement `llm_relax_and_recall` (LLM 扩词 → ES 双路 → 去重) in `agent-platform/local-promo-agent/src/tools/recommend/llm_relax.py` (FR-017, 幻觉护栏)
- [ ] T046 [P] [US1] Implement `get_user_profile` in `agent-platform/local-promo-agent/src/tools/recommend/user_profile.py` (FR-013)
- [ ] T047 [P] [US1] Implement `get_user_behavior_sequence` in `agent-platform/local-promo-agent/src/tools/recommend/user_behavior.py` (FR-013)
- [ ] T048 [P] [US1] Implement `call_recommendation_service` (top-K, latency budget) in `agent-platform/local-promo-agent/src/tools/recommend/rank.py` (FR-014)
- [ ] T049 [P] [US1] Implement `enrich_coupon` (券门店资格 + 单人限额 + 内部券合并) in `agent-platform/local-promo-agent/src/tools/recommend/enrich.py` (FR-015)
- [ ] T050 [US1] Implement ES degradation path (circuit breaker → cache fallback) in `agent-platform/local-promo-agent/src/degradation/es_fallback.py` (FR-012b, A-018)
- [ ] T051 [US1] Implement recommendation service degradation (skip LLM rank → 热度榜) in `agent-platform/local-promo-agent/src/degradation/rank_fallback.py` (FR-014b)
- [ ] T052 [US1] Implement LP core orchestrator (槽位→检索→排序→补全→Envelope) in `agent-platform/local-promo-agent/src/core/orchestrator.py` (FR-016)
- [ ] T053 [US1] Implement intent classifier in `agent-platform/main-agent/src/core/intent_classifier.py` (FR-001)
- [ ] T054 [US1] Wire main-agent core loop (intent → registry → RPC → Envelope → session update) in `agent-platform/main-agent/src/core/agent_loop.py` (FR-005: no internal tool name leakage)
- [ ] T055 [US1] Implement SSE push on state change in `agent-platform/main-agent/src/api/sse.py` (D-004)

**Checkpoint**: US1 fully functional. 跑 `quickstart.md` 场景 1 + 3 + E-1 + E-2 + E-3 全部 ✅ 即可视为 MVP。

---

## Phase 4: User Story 2 — Agent 协助下单 (Priority: P2)

**Goal**: 推荐列表 → 草稿订单 → 改单 / 改数量 / 取消 / 确认支付 → 收银台 → 回调;**多端互斥**(FR-023b)。

**Independent Test**: 跑 `quickstart.md` 场景 4(下单闭环)+ 场景 E-6(多端并发);E2E 通过 + 多端互斥测试通过即可。

### Tests for User Story 2 ⚠️ Write FIRST

- [ ] T056 [P] [US2] E2E test: prepare_draft via list index in `tests/e2e/test_order.py` (FR-020, scenario 4 step 2)
- [ ] T057 [P] [US2] E2E test: update quantity in draft in `tests/e2e/test_order_modify.py` (FR-021, scenario 4 step 3)
- [ ] T058 [P] [US2] E2E test: payment handoff + callback in `tests/e2e/test_payment.py` (FR-022, scenario 4 step 5)
- [ ] T059 [P] [US2] E2E test: multi-device mutual exclusion in `tests/e2e/test_multi_device_lock.py` (FR-023b, scenario E-6)
- [ ] T060 [P] [US2] E2E test: pre-payment validate catches stale coupon in `tests/e2e/test_payment_validate.py` (FR-023)
- [ ] T061 [P] [US2] E2E test: order before list exists triggers clarification in `tests/e2e/test_order_clarify.py` (US2 场景 5)

### Additional Tests for User Story 2 (C1 SC-004)

- [ ] T062 [P] [US2] E2E: end-to-end order completion in ≤ 5 conversational turns in `tests/e2e/test_order_turns.py` (SC-004)
- [ ] T063 [P] [US2] Contract test: payment handoff mock in `agent-platform/local-promo-agent/tests/contract/test_payment_handoff.py`

### Implementation for User Story 2

- [ ] T064 [P] [US2] Implement `prepare_draft` tool (index / name / id references + 最多 1 次追问) in `agent-platform/local-promo-agent/src/tools/order/prepare_draft.py` (FR-020)
- [ ] T065 [P] [US2] Implement `update_draft` tool (改数量 / 换品 / 换券 / 取消) in `agent-platform/local-promo-agent/src/tools/order/update_draft.py` (FR-021)
- [ ] T066 [P] [US2] Implement `pre_payment_validate` (库存 / 资格 / 限额) in `agent-platform/local-promo-agent/src/tools/order/validate.py` (FR-023)
- [ ] T067 [P] [US2] Implement `handoff_to_payment` (返回 H5 收银台 url + 锁 TTL) in `agent-platform/local-promo-agent/src/tools/order/payment_handoff.py` (FR-022)
- [ ] T068 [P] [US2] Implement `handle_payment_result` (回填 session state + 释放锁) in `agent-platform/local-promo-agent/src/tools/order/payment_result.py` (FR-022)
- [ ] T069 [US2] Wire payment callback endpoint in `agent-platform/main-agent/src/api/payment_callback.py` (H5 → 主 Agent)
- [ ] T070 [US2] Add `order` intent to intent classifier in `agent-platform/main-agent/src/core/intent_classifier.py` (FR-001, 共享 LP)
- [ ] T071 [US2] Wire order routing in main-agent core loop in `agent-platform/main-agent/src/core/agent_loop.py`

**Checkpoint**: US2 functional;可以完成"发现 → 下单 → 支付"全流程。

---

## Phase 5: User Story 7 — 券包管理 (Priority: P3)

**Goal**: 用户查询"我的券包" → 返回 per-user 资产视图(可用 / 已用 / 过期 / 详情 / 横向对比);与下单工具衔接(FR-025)。

**Independent Test**: 跑 `quickstart.md` 场景 5(券包)+ 场景 E-7(删除偏好——本阶段不写,只覆盖券包);E2E 通过 + 状态过滤正确即可。

### Tests for User Story 7 ⚠️ Write FIRST

- [ ] T072 [P] [US7] E2E test: query coupon wallet returns all 3 statuses in `tests/e2e/test_coupon_wallet.py` (US7 场景 2)
- [ ] T073 [P] [US7] E2E test: filter by status (available / used / expired) in `tests/e2e/test_coupon_wallet_filter.py` (US7 场景 6)
- [ ] T074 [P] [US7] E2E test: get_coupon_detail in `tests/e2e/test_coupon_detail.py` (US7 场景 3)
- [ ] T075 [P] [US7] E2E test: compare_coupons horizontal card in `tests/e2e/test_coupon_compare.py` (US7 场景 4)
- [ ] T076 [P] [US7] E2E test: 7-day expiry badge in `tests/e2e/test_coupon_expiry_badge.py` (FR-026, US7 场景 5)
- [ ] T077 [P] [US7] E2E test: empty wallet returns friendly empty state in `tests/e2e/test_coupon_wallet_empty.py` (US7 场景 1)
- [ ] T078 [P] [US7] E2E test: from wallet "用这张" → order handoff in `tests/e2e/test_wallet_to_order.py` (FR-025)
- [ ] T079 [P] [US7] Contract test: user asset query service in `agent-platform/local-promo-agent/tests/contract/test_user_asset_service.py` (A-015)

### Implementation for User Story 7

- [ ] T080 [P] [US7] Implement `list_my_coupons` (status / sort / filters) in `agent-platform/local-promo-agent/src/tools/wallet/list.py` (FR-024)
- [ ] T081 [P] [US7] Implement `get_coupon_detail` in `agent-platform/local-promo-agent/src/tools/wallet/detail.py` (FR-024)
- [ ] T082 [P] [US7] Implement `compare_coupons` (横向对比卡) in `agent-platform/local-promo-agent/src/tools/wallet/compare.py` (FR-024)
- [ ] T083 [P] [US7] Implement fast-expiry detector (剩余 ≤ 7 天角标) in `agent-platform/local-promo-agent/src/tools/wallet/expiry.py` (FR-026)
- [ ] T084 [P] [US7] Add `coupon_wallet` intent to intent classifier in `agent-platform/main-agent/src/core/intent_classifier.py` (FR-001)
- [ ] T085 [US7] Wire wallet→order handoff in LP orchestrator in `agent-platform/local-promo-agent/src/core/orchestrator.py` (FR-025)
- [ ] T086 [US7] Wire coupon_wallet routing in main-agent core loop in `agent-platform/main-agent/src/core/agent_loop.py`

**Checkpoint**: US7 functional;可独立交付"查券包"体验。

---

## Phase 6: User Story 3 — 对话式重排 (Priority: P4)

**Goal**: 4 种排序键(`distance` / `popularity` / `price_asc/desc` / `model`)作用于当前列表,不重新检索。

**Independent Test**: 跑 `quickstart.md` 场景 6;4 个 sort_key 各响应正确 + 列表内容集合一致(SC-005)。

### Tests for User Story 3 ⚠️ Write FIRST

- [ ] T087 [P] [US3] E2E test: 4 sort keys each preserve item set in `tests/e2e/test_sort.py` (SC-005, scenario 6)
- [ ] T088 [P] [US3] Unit test: sort key parser (按距离/热度/价格/默认, 升降序) in `agent-platform/main-agent/tests/unit/test_sort_parser.py` (FR-030)
- [ ] T089 [P] [US3] Unit test: sort applier in-place reorder in `agent-platform/main-agent/tests/unit/test_sort_applier.py` (FR-031)

### Implementation for User Story 3

- [ ] T090 [P] [US3] Implement sort command parser in `agent-platform/main-agent/src/core/sort_parser.py` (FR-030)
- [ ] T091 [P] [US3] Implement sort applier (in-place reorder on SessionState) in `agent-platform/main-agent/src/core/sort_applier.py` (FR-031)
- [ ] T092 [US3] Wire sort routing in main-agent core loop (no LP call) in `agent-platform/main-agent/src/core/agent_loop.py`

**Checkpoint**: US3 functional;轻量控制无 LP 依赖,实现成本低。

---

## Phase 7: User Story 5 — 对话式排除 + 跨会话偏好记忆 (Priority: P5)

**Goal**: "我不要瑞幸" → 当前列表过滤 + 主动追问持久化(FR-018)+ Preference Store 写入(FR-019)+ 立即清除(FR-019b);**多端共享**计数。

**Independent Test**: 跑 `quickstart.md` 场景 2(排除 + 持久化)+ 场景 E-7(立即清除);E2E 通过即可。

### Tests for User Story 5 ⚠️ Write FIRST

- [ ] T093 [P] [US5] E2E test: exclude brand with persist ask in `tests/e2e/test_exclude.py` (FR-018, scenario 2)
- [ ] T094 [P] [US5] E2E test: cross-session preference applied in new session in `tests/e2e/test_preference_persist.py` (FR-019, scenario 2 step 3)
- [ ] T095 [P] [US5] E2E test: delete_my_preferences within 1 minute in `tests/e2e/test_preference_delete.py` (FR-019b, scenario E-7)
- [ ] T096 [P] [US5] E2E test: explicit override (今天给我看看) doesn't lose persistence in `tests/e2e/test_preference_override.py` (FR-019)
- [ ] T097 [P] [US5] Contract test: Preference Store write/read in `agent-platform/main-agent/tests/contract/test_preference_store.py` (A-011)
- [ ] T098 [P] [US5] Unit test: implicit preference opt-in default off in `agent-platform/main-agent/tests/unit/test_implicit_pref_default.py` (A-012)

### Implementation for User Story 5

- [ ] T099 [P] [US5] Implement `exclude_items` tool (default 临时;只过滤不持久化) in `agent-platform/local-promo-agent/src/tools/exclude/exclude.py` (FR-018)
- [ ] T100 [P] [US5] Implement `get_active_preferences` (读 Preference Store;过滤过期) in `agent-platform/local-promo-agent/src/tools/exclude/preferences.py` (FR-019)
- [ ] T101 [P] [US5] Implement `persist_preference` (主 Agent 端,走 action 回调) in `agent-platform/main-agent/src/preferences/writer.py` (FR-019, A-011)
- [ ] T102 [P] [US5] Implement `delete_my_preferences` (1 分钟内物理清除) in `agent-platform/main-agent/src/preferences/delete.py` (FR-019b)
- [ ] T103 [US5] Wire preference read in LP orchestrator (检索 / 排序前) in `agent-platform/local-promo-agent/src/core/orchestrator.py` (FR-019)
- [ ] T104 [US5] Wire persist-ask flow in main-agent core loop in `agent-platform/main-agent/src/core/agent_loop.py` (FR-018)

**Checkpoint**: US5 functional;推荐"越用越懂你"。

---

## Phase 8: User Story 8 — 上下文压缩 (Priority: P6)

**Goal**: 长会话触发压缩(轮次 > 20 或字符 > 8000)→ 早期轮次压缩为 Session Summary;失败降级为丢早期轮次;**透明**(对用户)。

**Independent Test**: 跑 `quickstart.md` 场景 7 + 场景 7 失败路径;30 轮触发压缩 + 引用早期内容 + 失败降级均通过即可。

### Tests for User Story 8 ⚠️ Write FIRST

- [ ] T105 [P] [US8] E2E test: 30-turn session triggers compression in `tests/e2e/test_compression.py` (FR-054, US8 场景 1)
- [ ] T106 [P] [US8] E2E test: compression failure degrades to drop early turns in `tests/e2e/test_compression_failure.py` (US8 场景 4)
- [ ] T107 [P] [US8] E2E test: user can still reference early intent via summary in `tests/e2e/test_compression_recall.py` (US8 场景 2)
- [ ] T108 [P] [US8] Unit test: threshold detection (轮次 / 字符 二选一) in `agent-platform/main-agent/tests/unit/test_compression_threshold.py` (A-016)
- [ ] T109 [P] [US8] Unit test: PII redaction in summary in `agent-platform/main-agent/tests/unit/test_summary_pii.py` (A-016, FR-054)

### Implementation for User Story 8

- [ ] T110 [P] [US8] Implement compression service client in `agent-platform/main-agent/src/compression/client.py` (D-005)
- [ ] T111 [P] [US8] Implement threshold monitor (轮次 + 字符 双触发) in `agent-platform/main-agent/src/compression/monitor.py` (FR-054, A-016)
- [ ] T112 [P] [US8] Implement SessionSummary generator in `agent-platform/main-agent/src/compression/summarizer.py` (D-005, 摘要字段锁)
- [ ] T113 [P] [US8] Implement PII redactor in `agent-platform/main-agent/src/compression/redact.py` (A-016)
- [ ] T114 [US8] Wire compression trigger in main-agent core loop in `agent-platform/main-agent/src/core/agent_loop.py` (FR-054)
- [ ] T115 [US8] Implement compression failure degradation (丢早期轮次 + 写 trace) in `agent-platform/main-agent/src/compression/fallback.py`

**Checkpoint**: US8 functional;长会话不再爆炸。

---

## Phase 9: User Story 6 — 失败交易归因 (Priority: P7)

**Goal**: 失败 / 放弃 / 成功的会话都写入 Conversation Trace(异步、不阻塞);6 个月 TTL;不含 PII。

**Independent Test**: 跑 `quickstart.md` 场景 8(归因样本)+ 异步不阻塞;E2E 通过即可。

### Tests for User Story 6 ⚠️ Write FIRST

- [ ] T116 [P] [US6] E2E test: abandoned session writes trace in `tests/e2e/test_trace.py` (US6 场景 1)
- [ ] T117 [P] [US6] E2E test: trace write failure does NOT block user response in `tests/e2e/test_trace_async.py` (FR-053, A-014)
- [ ] T118 [P] [US6] E2E test: successful session also writes trace (success/failure contrast) in `tests/e2e/test_trace_success.py` (US6 场景 3)
- [ ] T119 [P] [US6] Unit test: PII filter strips phone / id / bank in `agent-platform/main-agent/tests/unit/test_trace_pii_filter.py` (FR-053, A-014)
- [ ] T120 [P] [US6] Unit test: trace schema includes all FR-053 required fields in `agent-platform/main-agent/tests/unit/test_trace_schema.py`

### Implementation for User Story 6

- [ ] T121 [P] [US6] Implement ConversationTrace Pydantic model in `agent-platform/main-agent/src/trace/model.py` (data-model §14, FR-053)
- [ ] T122 [P] [US6] Implement trace queue producer (Kafka / RocketMQ producer) in `agent-platform/main-agent/src/trace/producer.py` (D-006)
- [ ] T123 [P] [US6] Implement PII filter for trace payloads in `agent-platform/main-agent/src/trace/pii_filter.py` (A-014)
- [ ] T124 [P] [US6] Implement trace writer consumer in `deploy/trace-consumer/consumer.py` (写 OLAP,默认 6 月 TTL)
- [ ] T125 [US6] Wire trace recording on session events in `agent-platform/main-agent/src/core/agent_loop.py` (FR-053)
- [ ] T126 [US6] Implement 6-month TTL retention policy in `deploy/trace-consumer/retention.py` (A-019)

**Checkpoint**: US6 functional;运营/分析可消费。

---

## Phase 10: User Story 4 — 第二期扩展点(契约级 stub, Priority: P8)

**Goal**: 注册"积分商城"占位,确保主 Agent 路由能优雅兜底"暂未支持",**不**写实现。

**Independent Test**: 跑 `quickstart.md` 场景 E-(本故事无新 e2e,沿用 US1 兜底流程);验证未注册意图返回 graceful fallback。

### Tests for User Story 4 ⚠️ Write FIRST

- [ ] T127 [P] [US4] E2E test: points_mall query returns "暂未支持" without crash in `tests/e2e/test_unregistered_intent.py` (FR-002, US4 场景 1)

### Implementation for User Story 4

- [ ] T128 [P] [US4] Register `points_mall` stub in Sub-Agent Registry in `agent-platform/main-agent/src/registry/registry.py` (FR-040, FR-042, data-model §16)
- [ ] T129 [P] [US4] Add `points_mall` to intent classifier in `agent-platform/main-agent/src/core/intent_classifier.py` (FR-001, FR-002, FR-004 stub for Phase 2 cross-vertical chaining)

### Additional Tests for User Story 4 (C1 SC-006)

- [ ] T130 [P] [US4] Regression: add stub points_mall + re-run US1 e2e tests all green in `tests/regression/test_extensibility.py` (SC-006)

**Checkpoint**: US4 stub ready;第二期接入时无需改主 Agent 代码。

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: Cross-cutting improvements;run quickstart validation as final gate.

- [ ] T131 [P] Run full `quickstart.md` end-to-end validation in `tests/e2e/test_quickstart_full.py`
- [ ] T132 [P] Performance baseline: p95 < 4s, llm_call_count P95 ≤ 2 in `tests/perf/test_baseline.py` (SC-001, SC-008)
- [ ] T133 [P] Isolation test: cross-user session state zero overlap in `tests/security/test_user_isolation.py` (SC-009, FR-003)
- [ ] T134 [P] Setup monitoring dashboards (Grafana) in `deploy/observability/grafana_dashboards/`
- [ ] T135 [P] Setup alerting rules (Prometheus) for降级 / 限流 / Trace 失败 in `deploy/observability/prometheus_rules.yml`
- [ ] T136 [P] Security hardening: secrets management via env / Vault, mTLS config in `deploy/security/`
- [ ] T137 [P] Documentation: update `CLAUDE.md` with full architecture diagram in `docs/architecture.md`
- [ ] T138 [P] Code cleanup: isort, remove dead code, type-hint coverage in both services in `agent-platform/{main-agent,local-promo-agent}/`
- [ ] T139 [P] Final review: Constitution Check verification (I~V 五项) in `docs/constitution_check.md`
- [ ] T140 [P] Backlog capture: documented "deferred to plan / Phase 2" items in `docs/backlog.md`(对齐 research.md 的 Open Questions)

**Checkpoint**: All polish tasks done;ready for production hand-off.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — can start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — **BLOCKS all user stories**
- **Phase 3~10 (User Stories)**: All depend on Phase 2 completion
  - User stories can proceed in parallel (if staffed) or sequentially in priority order
- **Phase 11 (Polish)**: Depends on all user stories

### User Story Dependencies

| Story | Priority | Depends On | Notes |
|-------|----------|------------|-------|
| US 1 对话式发现 | P1 | Foundational only | **MVP**;可独立交付 |
| US 2 协助下单 | P2 | Foundational + US 1 (草稿状态机需要 current_list 概念) | 但下单工具有自身的 list index 引用,可视为独立可测 |
| US 7 券包管理 | P3 | Foundational only | 独立可交付 |
| US 3 重排 | P4 | Foundational + US 1 (需要 current_list) | 排序作用于列表 |
| US 5 排除 + 记忆 | P5 | Foundational + US 1 (需要 list 上下文) | |
| US 8 上下文压缩 | P6 | Foundational only | 独立,但价值依赖于"长会话" |
| US 6 失败归因 | P7 | Foundational + Phase 2 事件钩子 | 独立;可在任何用户故事完成后接入 |
| US 4 扩展点 stub | P8 | Foundational only | 纯契约,几乎无实现 |

**MVP (User Story 1 only)** = Phase 1 + Phase 2 + Phase 3 = **约 32 个任务**(T001~T032 / T033 部分)。

### Within Each User Story

- **Tests (T###) MUST be written and FAIL before implementation**(Constitution III)
- Models / schemas / tools before services
- LP 工具 before LP 编排
- LP 编排 before main-agent 路由
- main-agent 路由 before API 入口
- 完成一个故事再进下一个(若团队规模允许,可多个故事并行)

### Parallel Opportunities

- Phase 1: T002 + T003 + T004 + T005 + T006 + T007 + T008 + T009 全部可并行(不同文件)
- Phase 2: 多个 [P] 任务可并行(不同模块)
- **每个 US 内部,所有测试任务([P])可并行**
- **每个 US 内部,所有工具实现([P])可并行**
- **跨 US**:不同 US 可由不同开发者并行(若已通过 Phase 2)

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests in parallel (after Phase 2):
Task: "T026 [US1] E2E test: conversational discovery"
Task: "T027 [US1] E2E test: LLM relax recall"
Task: "T028 [US1] E2E test: out-of-scope redirect"
Task: "T029 [US1] Contract test: ES 双路召回"
Task: "T030 [US1] Contract test: recommendation service"
Task: "T031 [US1] Smoke test: ES down → cache fallback"
Task: "T032 [US1] Smoke test: recommendation down → skip LLM"
Task: "T033 [US1] Unit test: slot extraction"
Task: "T034 [US1] Unit test: intent classifier"
# → All 9 tasks run in parallel;all FAIL initially.

# Then launch all US1 tool implementations in parallel (after tests fail):
Task: "T035 [US1] slot_extractor.py"
Task: "T036 [US1] search.py (ES 双路)"
Task: "T037 [US1] llm_relax.py"
Task: "T038 [US1] user_profile.py"
Task: "T039 [US1] user_behavior.py"
Task: "T040 [US1] rank.py"
Task: "T041 [US1] enrich.py"
# → All 7 tools developed in parallel;different files, no deps.

# Then sequential (depends on tools):
Task: "T042 [US1] es_fallback.py (degradation)"
Task: "T043 [US1] rank_fallback.py"
Task: "T044 [US1] LP orchestrator (uses T035~T043)"
Task: "T045 [US1] main-agent intent classifier"
Task: "T046 [US1] main-agent core loop (uses T044+T045)"
Task: "T047 [US1] SSE push"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Complete Phase 1: Setup (T001~T009, 9 tasks)
2. Complete Phase 2: Foundational (T010~T028, 19 tasks)
3. Complete Phase 3: US 1 (T026~T047, 22 tasks)
4. **STOP and VALIDATE**: 跑 `quickstart.md` 场景 1 + 3 + E-1 + E-2 + E-3
5. Deploy / demo if ready
6. **Total MVP: 47 个任务**

### Incremental Delivery

1. Setup + Foundational → Foundation ready (28 tasks)
2. + US 1 → Test → Deploy/Demo (**MVP**, +28 tasks = 56)
3. + US 2 → Test → Deploy/Demo (+15 tasks = 71)
4. + US 7 → Test → Deploy/Demo (+15 tasks = 86)
5. + US 3 → Test → Deploy/Demo (+6 tasks = 92)
6. + US 5 → Test → Deploy/Demo (+12 tasks = 104)
7. + US 8 → Test → Deploy/Demo (+11 tasks = 115)
8. + US 6 → Test → Deploy/Demo (+11 tasks = 126)
9. + US 4 stub → Test → Deploy/Demo (+4 tasks = 130)
10. + Phase 11 Polish (+10 tasks = **140 总任务**)

### Parallel Team Strategy

多开发者场景:
1. 团队**一起**完成 Phase 1 + Phase 2
2. Phase 2 完成后:
   - **Dev A**:US 1 (推荐)
   - **Dev B**:US 2 (下单,等 US 1 完成后启动也可)
   - **Dev C**:US 7 (券包)
   - **Dev D**:US 3 (重排)
3. US 5 / US 8 / US 6 可由后续开发者并行
4. US 4 stub 任何时候可由一人快速完成

---

## Summary

| 维度 | 数字 |
|------|------|
| **总任务数** | **140** |
| Phase 1 (Setup) | 9 |
| Phase 2 (Foundational) | 16 |
| US 1 (P1) MVP | 22(含 9 测试 + 13 实现) |
| US 2 (P2) | 15 |
| US 7 (P3) | 15 |
| US 3 (P4) | 6 |
| US 5 (P5) | 12 |
| US 8 (P6) | 11 |
| US 6 (P7) | 11 |
| US 4 (P8) stub | 4 |
| Phase 11 Polish | 10 |
| **测试任务** | **60** (43% — 符合 Constitution III) |
| **实现任务** | 80 |
| **MVP 范围** | Phase 1 + 2 + US 1 = **47 任务** |
| **首个交付增量** | MVP (US 1) |
| **故事间并行机会** | 8 个用户故事各自独立(US 2/3/5 依赖 US 1 的 list 概念,但各自工具有独立契约) |
| **故事内并行机会** | 每个 US 的 [P] 任务可并行 |

---

## Notes

- `[P]` tasks = different files, no dependencies
- `[Story]` label maps task to user story for traceability
- Each user story independently completable and testable
- **Constitution III 硬约束:每个 US 的测试任务必须先写并确认失败,再写实现**
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
- The "story goal" + "independent test" at the top of each phase serves as a **run gate** for the phase

进入 `/speckit-implement` 时,从 **T001** 开始顺序执行;每完成一个 Phase 做一次 checkpoint 验证(跑 `quickstart.md` 对应场景)。
