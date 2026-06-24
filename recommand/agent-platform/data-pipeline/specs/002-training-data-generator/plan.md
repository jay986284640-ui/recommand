# Implementation Plan: 训练数据生成

**Branch**: `002-training-data-generator` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

> 本 plan 在 001 增强管线(`agent-platform/data-pipeline/feature_extraction/ai_enhance/`)产出的
> `item_features_ai.jsonl` 基础上,设计"训练数据生成"独立子包。
> 现有代码**不动**,只追加 `feature_extraction/training_data/` 子包 + 1 个入口 `run_training_data.py`。

---

## Summary

| 能力 | 接入位置 | 触发方式 | 产出来源 |
|------|----------|----------|----------|
| 训练数据生成 | `feature_extraction/training_data/` 新增子模块 | 独立 `run_training_data.py` 脚本,手动 / 调度 | `item_features_ai.jsonl` → LLM → `training_data_v1.jsonl` |

---

## Technical Context

**Language/Version**: Python 3.11+(沿用)
**Spark**: 3.5.3(本子包不直接用,只是读 001 产物 jsonl)
**新增依赖**:
- LLM SDK(沿用 001 的客户端,直接复用)
- `pandas`(可选,用于读 `item_features_ai.jsonl` 做轻量预处理;不强制)

**Storage**:
- 训练样本主输出:`./training_data_v1.jsonl`
- 失败日志:`./training_data_failures.jsonl`
- 增量状态:`./training_data_state.parquet`

**Testing**:
- pytest + mock-llm 单元测试(沿用 001 的 mock-llm 服务)
- 集成测试:跑 50 个 item_features_ai fixture → 验证主输出 400 行 + 字典校验 100%

**Target Platform**: Linux 容器(沿用)
**Project Type**: 在 `data-pipeline/` 中追加 1 个子包 `feature_extraction/training_data/` + 1 个新 `run_training_data.py`

**Performance Goals**:
- 1 万 item × 8 条/商品 = 8 万样本 < 60 分钟(SC-001)
- 增量 1% 重跑 < 5 分钟(SC-006)
- LLM 调用并发 16(semaphore=16),50 req/min 限速下刚好跑满

**Constraints**:
- 不动 001 增强管线(`ai_enhance/`)
- 不动 LP Agent envelope 协议
- LLM 调用必须可降级(失败 → 写 failures,不阻塞主流程)
- 输出 jsonl 100% 可被 `jq -c .` 解析(SC-004)
- `params` 字段 100% 字典校验通过(SC-002)

**Scale/Scope**:
- item 总量:1w~10w SKU(沿用 001)
- 默认 8 条/商品(可配 5~10)
- 负样本占比 10%(可配 0~0.3)

---

## Constitution Check

### I. Library-First ✅
- `training_data/` 是新顶层子包,独立可测
- 与 001 增强管线**单向依赖**:只读 `item_features_ai.jsonl`,不反写

### II. CLI Interface ✅
- `run_training_data.py --mode=full|incremental --count=8 --config=...`
- 与 001 `run_ai_enhance.py` CLI 风格一致

### III. Test-First (NON-NEGOTIABLE) ✅
- 1 个 US(US1)+ 测试任务 9~10 个先于实现任务
- 关键测试:diversity(SC-005)、dict-validation(SC-002)、解析率(SC-003)

### IV. Integration Testing ✅
- 用 mock-llm 服务(沿用 001 的 `mock-llm-server`)
- 集成测试 1 个:50 个 item_features_ai fixture → 400 行输出 + 100% 字典校验

### V. Observability, Versioning, Simplicity ✅
- 监控指标:解析成功率 / 字典校验通过率 / 多样性命中率 / 负样本比例
- jsonl 格式版本化:每行加 `_format_version: "training_data_v1"`
- Simplicity:不引入新的中间件,沿用 LLM SDK + jsonl + parquet

**Constitution Check 状态:通过**。Complexity Tracking 表空。

---

## Project Structure(增量)

```
agent-platform/data-pipeline/
├── feature_extraction/                       # 现有,扩展
│   ├── ai_enhance/                           # 001 已有,不动
│   │   └── ...
│   └── training_data/                        # 新增子模块
│       ├── __init__.py
│       ├── llm_client.py                     # 复用 001 LLMClient,本包只封装调用
│       ├── prompt.py                         # 对话生成 + 提参 prompt 模板
│       ├── param_schema.py                   # 7 维 ParamSpec + op 类型 + 字典校验
│       ├── diversity.py                      # 多样性控制(句式模板选择)
│       ├── negative_sampler.py               # 负样本生成
│       ├── state.py                          # 增量 md5 指纹状态
│       ├── pipeline.py                       # TrainingDataPipeline 编排
│       ├── cleaner.py                        # FR-007:7 类清洗规则
│       ├── distribution.py                   # FR-008:8 分布指标统计
│       ├── balancer.py                       # FR-008:自动过采样
│       ├── splitter.py                       # FR-009:按 item_id 划分 80/10/10
│       └── writer.py                         # jsonl 写出
├── configs/
│   ├── tag_dictionary.yaml                   # 001 已有,本 spec 沿用
│   └── prompts/
│       ├── ai_enhance_v1.txt                 # 001 已有
│       └── training_data_v1.txt              # 新增:对话生成 + 提参 prompt
├── tests/
│   └── feature_extraction/
│       ├── ai_enhance/                       # 001 已有
│       └── training_data/                    # 新增
│           ├── test_prompt.py
│           ├── test_param_schema.py
│           ├── test_diversity.py
│           ├── test_negative_sampler.py
│           ├── test_state.py
│           ├── test_pipeline.py
│           ├── test_writer.py
│           ├── test_cleaner.py
│           ├── test_distribution.py
│           ├── test_balancer.py
│           ├── test_splitter.py
│           └── test_integration.py
├── run_training_data.py                      # 新增入口
└── run_pipeline.py                           # 现有(可选加 --skip-training-data 开关,但默认关)
```

---

## Phase 0 — 关键技术决策(research.md 摘要)

| ID | 决策点 | 选项 | 推荐 |
|----|--------|------|------|
| D-001 | LLM 调用策略 | 1 段(同时产出对话 + 提参) / 2 段(先生成对话,再单独提参) | **1 段**:`structured output` 一次性产出 messages + intent + params,延迟减半,字段对齐精度更高 |
| D-002 | 对话轮次分布 | 固定 N 轮 / 1~4 轮随机 | **1~4 轮随机**(权重:1 轮 10%、2 轮 30%、3 轮 40%、4 轮 20%),3 轮为主贴近真实 |
| D-003 | 维度采样 | 全 7 维都覆盖 / 随机选 N 维(N≤4) | **随机选 2~4 维**;避免每条样本都 7 维全堆,贴近真实用户不会一次性表达所有条件 |
| D-004 | 字典版本化 | 硬编码字典 / 外部 yaml | **外部 yaml**(沿用 001 `configs/tag_dictionary.yaml`);本包只读不改 |
| D-005 | 负样本类型 | 仅"拒绝" / 仅"转移" / 拒绝 + 转移 + 不满足(3 类) | **3 类**:覆盖模型易错场景;实现为 prompt 里随机挑一类 |
| D-006 | op 类型集合 | 4 个基础 / 4+3 完整 | **4 个基础**(`eq` / `contains` / `in` / `not_in`);`gt/lt/between` 留接口不实现(SC-002 只校验 4 个) |
| D-007 | 多样性控制 | 句式模板随机 / 温度拉高 / 二者结合 | **二者结合**:prompt 注入 5~8 套句式骨架让 LLM 选;`temperature=0.7`;同时 SC-005 加 20% 高频模板上限 |
| D-008 | 数据清洗规则 | 仅去重 / 7 类全规则 | **7 类全规则**(FR-007):text_hash 去重 + 消息过短 + 模板降频 + params 全 null + 控制字符 + 字典外 + 轮次异常;always on 6 个 + 可配 1 个 |
| D-009 | 数据平衡策略 | 不平衡不处理 / 自动过采样 | **自动过采样**(FR-008):长尾类(<3%)原样本 + LLM 同义改写 1 次(2x);不平衡度 > 5x 报警不强制平衡(避免过拟合) |
| D-010 | 数据集划分 | 随机划分 / 按 item_id hash 划分 | **按 item_id hash % 100**(FR-009):80/10/10;避免同一 item 跨集合导致数据泄露;val/test 真实数据优先(SC-011) |

---

## Phase 1 — 设计产物

### 1.1 新增数据模型(`data-model.md`,本 plan 简述)

| 实体 | 字段 | 来源 |
|------|------|------|
| `TrainingSample` | item_id, intent, messages, params, order_by, negative, generated_at, llm_model, _format_version | 主输出 |
| `ParamSpec` | op(str), values(str\|List[str]\|None) | params 内嵌 |
| `MessageTurn` | role(str:user/assistant/system), content(str) | messages 内嵌 |
| `NegativeSample` | type(str:reject/pivot/unsatisfiable), sample:TrainingSample | 负样本 |
| `TrainingDataState` | item_id, ai_tags_md5, sample_count, generated_at, llm_model | 增量状态 |
| `TrainingDataFailure` | item_id, raw_response, error, error_detail, occurred_at | 失败日志 |

### 1.2 新增 contracts

- `contracts/training_data_format_v1.md` — `training_data_v1.jsonl` 输出 schema 详细说明
- `contracts/param_op_types.md` — `op` 7 个类型的适用维度 + values 类型 + 示例

### 1.3 复用 001

- `feature_extraction/ai_enhance/llm_client.py` 的 `LLMClient` 类(直接 import 复用,不改)
- `feature_extraction/ai_enhance/tag_schema.py` 的 `load_dictionary()`(直接 import)
- `configs/tag_dictionary.yaml`(直接读)

---

## Phase 1 后的 Constitution Check(预期)

✅ I. Library-First — 1 个新子包独立  
✅ II. CLI Interface — 1 个新 `run_training_data.py`  
✅ III. Test-First — tasks.md 先测后实(预计 9~10 个测试任务)  
✅ IV. Integration Testing — mock-llm 集成  
✅ V. Observability — 解析率 / 字典校验率 / 多样性命中率 / 负样本比例

---

## 关键文件清单(增量)

| 文件 | 类型 | 说明 |
|------|------|------|
| `feature_extraction/training_data/__init__.py` | 新增 | 子包入口 |
| `feature_extraction/training_data/llm_client.py` | 新增 | 复用 001 `LLMClient`,加 `generate_training_sample()` 方法 |
| `feature_extraction/training_data/prompt.py` | 新增 | 对话生成 + 提参 prompt(7 维字典子集 + 5~8 套句式骨架 + 负样本注入位) |
| `feature_extraction/training_data/param_schema.py` | 新增 | `ParamSpec` dataclass + `OP_TYPES` 7 个常量 + `validate_params()` |
| `feature_extraction/training_data/diversity.py` | 新增 | `pick_template(seed)` 随机选 1 套句式 |
| `feature_extraction/training_data/negative_sampler.py` | 新增 | `sample_negative_type(seed)` 拒绝 / 转移 / 不满足 三选一 |
| `feature_extraction/training_data/state.py` | 新增 | `TrainingDataState` 增量 md5 指纹 |
| `feature_extraction/training_data/pipeline.py` | 新增 | `TrainingDataPipeline` 编排 **9 步**:加载 ai_features → 增量比对 → 批量 LLM → 字典校验 → **清洗(FR-007)→ 分布统计(FR-008)→ 自动平衡(FR-008)→ 划分(FR-009)→ 写 jsonl** |
| `feature_extraction/training_data/cleaner.py` | 新增 | `DataCleaner` 7 类清洗规则(FR-007)+ 留存率校验(SC-008) |
| `feature_extraction/training_data/distribution.py` | 新增 | `DistributionAnalyzer` 8 指标统计(FR-008)+ 写 `distribution_report.json` |
| `feature_extraction/training_data/balancer.py` | 新增 | `DataBalancer` 自动过采样(FR-008)+ 平衡动作日志 |
| `feature_extraction/training_data/splitter.py` | 新增 | `DataSplitter` 按 item_id hash 划分 80/10/10(FR-009)+ 泄露校验(SC-010) |
| `feature_extraction/training_data/writer.py` | 新增 | `write_training_data_jsonl()` 字段固定顺序 + `_format_version` |
| `configs/prompts/training_data_v1.txt` | 新增 | 对话生成 + 提参 prompt(含 7 维字典子集 + 句式骨架 + 负样本指令 + `op` 类型说明) |
| `tests/feature_extraction/training_data/test_prompt.py` | 新增 | prompt 加载 + 字段注入 + 字典子集约束 |
| `tests/feature_extraction/training_data/test_param_schema.py` | 新增 | 7 维 ParamSpec + op 类型 + 字典校验(SC-002) |
| `tests/feature_extraction/training_data/test_diversity.py` | 新增 | 句式模板选择 + 高频模板 ≤ 20%(SC-005) |
| `tests/feature_extraction/training_data/test_negative_sampler.py` | 新增 | 3 类负样本 + 比例 = `negative_ratio` ±0.02(SC-007) |
| `tests/feature_extraction/training_data/test_state.py` | 新增 | 增量 md5 指纹比对 |
| `tests/feature_extraction/training_data/test_pipeline.py` | 新增 | 单元测试:5 步编排 |
| `tests/feature_extraction/training_data/test_writer.py` | 新增 | jsonl 写出 + `_format_version` + 字段顺序 |
| `tests/feature_extraction/training_data/test_integration.py` | 新增 | 集成测试:50 items fixture → 400 行 + 100% 字典校验 + 100% jq 解析 + 留存率 ≥ 85% + 8 指标达标(SC-002, SC-004, SC-008, SC-009) |
| `tests/feature_extraction/training_data/test_cleaner.py` | 新增 | 7 类清洗规则单元测试(FR-007)+ 留存率校验(SC-008) |
| `tests/feature_extraction/training_data/test_distribution.py` | 新增 | 8 分布指标统计 + 警告(FR-008, SC-009) |
| `tests/feature_extraction/training_data/test_balancer.py` | 新增 | 自动过采样 + 平衡动作日志(FR-008) |
| `tests/feature_extraction/training_data/test_splitter.py` | 新增 | 按 item_id 划分 80/10/10 + 泄露校验(FR-009, SC-010) |
| `run_training_data.py` | 新增 | 入口 |
| `common/config_loader.py` | 改 | 加 `TrainingDataConfig` dataclass |
| `configs/datasets/*.yaml` | 改 | 增加 `training_data` 段 |

---

## Complexity Tracking

| 违反 | 为什么 | 更简单方案(被拒理由) |
|------|--------|---------------------|
| (空) | (空) | (空) |

---

## Next Steps

1. **Phase 0 research.md** 在 D-001~D-007 7 个点收敛;LLM 调用策略(1 段 vs 2 段)用 mock-llm 跑对照实验
2. **Phase 1 design** `data-model.md` 增量 + `contracts/{training_data_format_v1,param_op_types}.md`
3. **/speckit-tasks** 按 US1 拆任务,测试 9~10 个先于实现
4. **/speckit-implement** 按任务执行
