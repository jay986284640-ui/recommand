# Quickstart: 训练数据生成 (兴业 O2O 三品类 SFT 语料)

**Spec**: [./spec.md](./spec.md) (v2.5.2) | **Plan**: [./plan.md](./plan.md) | **Date**: 2026-06-27

> **v2.5.1 重要变更**:字段契约 `field_contract` 校验 + 禁隐式 JOIN + 商品名称 fallback 推断。
> 详细见项目根 `README.md` §v2.5.1。
> 
> **v2.5 重要变更**:表结构改用 `configs/tables.yaml` 声明,不再解析 `tabale_structer.sql`。
> `EnrichmentPipeline` / `extract-dictionary` 都接受 `--tables-config configs/tables.yaml`。
> `--sql <path>` 保留为 deprecated alias(走 `parse_sql` 兼容路径)。完整变更见项目根 `README.md`。

---

## 概述

本指南提供 5 个**可运行**的端到端验证场景,每个场景给出:前置条件 / 命令 / 期望产出 / SC 自检。
涵盖从 YAML 表配置加载到 80/10/10 划分全流程。

**前置条件**:
- Python 3.11+(`python3 --version`)
- 安装依赖:`pip install -r agent-platform/training-data-synonym/requirements.txt`(含 pyyaml / jsonschema / tenacity / pytest / hypothesis)
- 已 clone 工程到本地,`cd` 到 `/opt/recommand/recommand`

**注意**:本工程 CI 完全脱机(`--source=mock` + `MockLLMClient`);无需 Hive 集群 / LLM 凭据即可跑通 demo。

---

## 场景 1 — YAML 表配置加载 + 表角色识别(单步)

**目标**:验证 `configs/tables.yaml` 加载出 8 张表的列 / 分区 / 角色。

**命令**:

```bash
python -m training_data_synonym.cli tables-meta \
  --tables-config configs/tables.yaml \
  --output /tmp/quickstart/tables_meta.json
```

**期望产出**:

- `/tmp/quickstart/tables_meta.json` 存在;8 个 TableMeta 元素
  (meituan_shop / self_shop / coupon 三核心 + address / category / coupon_shop / discount 辅助)。
- 退出码 0。

**自检命令**:

```bash
jq '[.[] | select(.inferred_role | IN("meituan_shop","self_shop","coupon"))] | length' \
  /tmp/quickstart/tables_meta.json
# 期望: ≥ 3
```

**SC 绑定**:SC-001。

---

## 场景 2 — Stage 1 标签补全(mock Hive)

**目标**:从 mock Hive fixture 拉 100 行 × 3 类商品,产出 `item_tags.jsonl`(8 维标签 + tag_source)。

**前置**:

```bash
ls tests/fixtures/hive/ 2>/dev/null || \
  echo "fixtures missing — run: pytest tests/contract/test_hive_read_spec.py::test_setup_fixtures"
```

**命令**:

```bash
python -m training_data_synonym.cli enrich \
  --tables-config configs/tables.yaml \
  --source mock \
  --fixture-dir tests/fixtures/hive \
  --n-items-per-type 100 \
  --output-dir /tmp/quickstart/enrich
```

**期望产出**:

- `/tmp/quickstart/enrich/item_tags.jsonl`:≥ 200 行(2 类门店各 ~100 + 券 ~100)
- `/tmp/quickstart/enrich/tag_enrichment_failures.jsonl`:存在(可能为空,字典 reject 时有内容)
- `/tmp/quickstart/enrich/tag_enrichment_state.jsonl`:存在
- `/tmp/quickstart/enrich/tables_meta.json`:存在(同场景 1)
- `/tmp/quickstart/enrich/summary.json`:存在,含 `items_processed / llm_calls / dict_pass_rate / dict_rejected_count / coverage_avg / sc_pass`

**自检命令**:

```bash
# SC-002 字典合法率(应 ≥ 1.0,mock 模式不 reject)
jq '.dict_pass_rate' /tmp/quickstart/enrich/summary.json

# SC-003 覆盖率(注意:mock LLM 仅 ≈3.75/7,真实 LLM 才能达到 ≥ 6.5)
jq '.coverage_avg' /tmp/quickstart/enrich/summary.json

# Part B(v2.5):字典 reject 可观测性 — 字典外值计数
jq '.dict_rejected_count' /tmp/quickstart/enrich/summary.json

# v2.5.1:名称 fallback 推断使用次数(LLM 返回 None 时从商品名称推断)
jq '.dict_rejected_count, .items_processed' /tmp/quickstart/enrich/summary.json
# mock 模式下 LLM 大概率返回非空值,数字会较小;真实 LLM + 空 Brnd_Nm 数据集会有较多触发

# v2.5.1:验证字段契约加载(表结构必需字段缺失 → TablesConfigError)
python -c "
from training_data_synonym.common.tables_config import load_tables_config
from pathlib import Path
tables = load_tables_config(Path('configs/tables.yaml'))
roles = sorted({t.inferred_role.value for t in tables})
print(f'Loaded {len(tables)} tables, roles: {roles}')
"

# tag_source.distance 仅 ∈ {geo, missing}
jq -r '.tag_source.distance' /tmp/quickstart/enrich/item_tags.jsonl | sort -u
# 期望: "geo"  "missing"  (不允许 "raw" / "ai")

# tag_source.consumable_type 仅 ∈ {derived, ai, missing}
jq -r '.tag_source.consumable_type' /tmp/quickstart/enrich/item_tags.jsonl | sort -u
# 期望: "ai"  "derived"  "missing"
```

**SC 绑定**:SC-002 / SC-003。

---

## 场景 3 — Stage 2 SFT 语料生成(mock LLM)

**目标**:从 Stage 1 输出生成多轮 SFT 语料 + 字典校验。

**前置**:场景 2 完成。

**命令**:

```bash
python -m training_data_synonym.cli sft \
  --input /tmp/quickstart/enrich/item_tags.jsonl \
  --output-dir /tmp/quickstart/sft \
  --count-per-item 8 \
  --max-message-turns 5
```

**期望产出**:

- `/tmp/quickstart/sft/sft_corpus.jsonl`:≥ 1600 行(200 items × 8)
- `/tmp/quickstart/sft/sft_failures.jsonl`:存在(占比 < 5%)
- `/tmp/quickstart/sft/summary.json`:存在(含 `sft.total / sft.sft_failures / sft.coverage_pass`)

**自检命令**:

```bash
# SC-004 JSONL 解析
jq -c . /tmp/quickstart/sft/sft_corpus.jsonl | head -1
# 期望: 单行 JSON,无 error

# SC-005 单 item 全维度覆盖率
jq -s 'group_by(.item_id) | map({
  item_id: .[0].item_id,
  covered: (map(.covered_dims[]) | unique | length),
  expected: 8
}) | map(select(.covered < .expected))' /tmp/quickstart/sft/sft_corpus.jsonl
# 期望: 空数组

# Part B(v2.5):每条 SFT 样本的 llm_model 字段记录真实模型名
jq -s '[.[] | .llm_model] | unique' /tmp/quickstart/sft/sft_corpus.jsonl
# 期望: ["mock-llm"]  (或 openai 模式下的实际模型名)
```

**SC 绑定**:SC-004 / SC-005。

---

## 场景 4 — 数据集 80/10/10 划分(SC-010 0 泄露)

**目标**:从 `sft_corpus.jsonl` 划 train/val/test 三文件,验证无数据泄露。
**(v2.5 新)** 由 `cmd_split` 直接实现:`hashlib.md5(item_id) % 100` 桶分。

**命令**:

```bash
python -m training_data_synonym.cli split \
  --input /tmp/quickstart/sft/sft_corpus.jsonl \
  --output-dir /tmp/quickstart/split
# ratios 从 configs/pipeline.yaml 读(train 0.8 / val 0.1 / test 0.1)
```

**期望产出**:

- `/tmp/quickstart/split/train.jsonl`、`val.jsonl`、`test.jsonl` 三文件。
- 行数比例 ≈ 80/10/10 ± 2%。
- 任一 `item_id` 不跨集合(`no_leak=True`)。

**自检命令**:

```bash
# SC-009 比例
wc -l /tmp/quickstart/split/{train,val,test}.jsonl

# SC-010 0 泄露
diff <(jq -r '.item_id' /tmp/quickstart/split/train.jsonl | sort -u) \
     <(jq -r '.item_id' /tmp/quickstart/split/val.jsonl   | sort -u)
diff <(jq -r '.item_id' /tmp/quickstart/split/train.jsonl | sort -u) \
     <(jq -r '.item_id' /tmp/quickstart/split/test.jsonl  | sort -u)
# 期望: 全为空
```

**SC 绑定**:SC-009 / SC-010。

---

## 场景 5 — 端到端(`cli all`) + SC 自动自检

**目标**:一次跑完两阶段 + 划分,自动对照 11 个 SC 报告通过情况。
**(v2.5 新)** `cmd_all` 串联 enrich → sft → split → verify。

**命令**:

```bash
python -m training_data_synonym.cli all \
  --tables-config configs/tables.yaml \
  --source mock \
  --fixture-dir tests/fixtures/hive \
  --output-dir /tmp/quickstart/e2e \
  --n-items-per-type 50 \
  --count-per-item 4
# verify 由 cmd_all 内部触发;写 verify_report.json
```

**期望产出**:

- `/tmp/quickstart/e2e/` 包含完整产物集(item_tags / sft_corpus / train|val|test / summary / verify_report)。

**自检命令**:

```bash
cat /tmp/quickstart/e2e/verify_report.json | jq '.sc_pass'
# 期望: SC-001/002/004/005/010 全 PASS;SC-003 FAIL(mock LLM coverage 限制);
#       SC-008/009 skip(cleaning_report / distribution_report 不存在)
```

**SC 绑定**:SC-001 ~ SC-011(可运行子集)。

---

## 场景 6 — `extract-dictionary` 字典扩量离线(US4 / Stage 0)

**目标**:从 Hive 真实数据抽取品牌 + 分类候选,产出可审核 diff 报告(**离线工具,不污染主流水线**)。

**命令**:

```bash
python -m training_data_synonym.cli extract-dictionary \
  --tables-config configs/tables.yaml \
  --source mock \
  --fixture-dir tests/fixtures/hive \
  --output-dir /tmp/quickstart/dict_candidates \
  --frequency-min 1 \
  --log-level WARNING
```

**期望产出**(`/tmp/quickstart/dict_candidates/`):

```text
brands_raw.csv           70+ 行(name / frequency / sources)
brands_normalized.csv    ~55 行(canonical / frequency / n_variants / aliases,聚类合并后)
brands_diff.yaml         _meta + added + existing + removed 三段
categories_raw.csv      12 行
categories_normalized.csv
categories_diff.yaml
```

**自检命令**:

```bash
# 1. added 段至少 1 个候选(取决于 fixture 大小)
yq '.added | length' /tmp/quickstart/dict_candidates/brands_diff.yaml

# 2. _meta 字段完整
yq '._meta | keys' /tmp/quickstart/dict_candidates/brands_diff.yaml
# 期望: [candidate_count, existing_count, added_count, removed_count, frequency_min,
#        levenshtein_threshold, jaccard_threshold, raw_count, normalized_count, filtered_count]

# 3. 跨脚本不合并(CJK 星巴克 vs Latin Starbucks 各成独立 cluster)
yq '.normalized_brands' /tmp/dict_candidates/brands_diff.yaml  # 仅文案层验证

# 4. 高频 brand 优先排序
yq '.added | .[0]' /tmp/quickstart/dict_candidates/brands_diff.yaml
# 期望: frequency 最高的候选
```

**人工 promote 流程**:

```bash
# 1. Review brands_diff.yaml
cat /tmp/quickstart/dict_candidates/brands_diff.yaml

# 2. 编辑 configs/brand_dictionary.yaml,合并 added 段
# 3. bump _meta.version: 1.0 → 2.0
# 4. git commit + PR merge → dict_version 自动变 → Stage 1 自动增量重算
python -m training_data_synonym.cli enrich \
  --tables-config configs/tables.yaml \
  --source mock --fixture-dir tests/fixtures/hive \
  --output-dir /tmp/quickstart/enrich_v2
# 验证: enrichment_state 中所有 item 的 dict_version 都变 → Stage 1 重算触发
```

---

## 一键 demo(`scripts/demo.sh`)

**(v2.5 新)** 走新 CLI 4 段串联,`set -uo pipefail`(no -e)— mock LLM 不达标也跑完整链路。

```bash
bash scripts/demo.sh
# 10 门店/类型 × 4 样本/商品,30s 内跑通 enrich → sft → split → verify
# 产物见 /tmp/training_data_demo/
```

---

## 生产部署场景(参考)

不在 CI 跑通路径中,留给部署运维执行:

```bash
# 生产:Hive + 真实 LLM(OpenAI 兼容 HTTP)
pip install -e .[llm]   # 装 httpx
export OPENAI_API_KEY=sk-...
python -m training_data_synonym.cli all \
  --tables-config configs/tables.yaml \
  --provider openai_compat --model claude-haiku-4-5 \
  --source hive \
  --catalog spark_catalog \
  --etl-dt-mode latest_n --latest-n 7 \
  --output-dir /var/lib/training_data_synonym/prod/$(date +%Y%m%d)
```

> v2.5 之前用 `--llm-source platform`(legacy 占位)已废弃;改用 `--provider openai_compat`。

---

## 故障定位

| 现象 | 排查方向 |
|------|---------|
| `TablesConfigError: tables config not found` | 检查 `--tables-config` 路径;默认是 `configs/tables.yaml` |
| `TablesConfigError: invalid role` | 检查 `configs/tables.yaml` 中 `role` 是否 ∈ Role 枚举 |
| `TablesConfigError: ... is missing required columns for field_contract` | **v2.5.1**:表声明的 `role:` 标注未覆盖 `_meta.field_contract.<role>.required`。给缺失字段加 `role: <r>` 标注,或更新上游 SQL / fixture 提供。 |
| 自拓展门店 `shop_lng`/`shop_lat` 缺失 → distance = null | **v2.5.1**:上游 SQL 视图未把 `o2o_new_gut_shop_address` JOIN 进来。代码不再做隐式 join;改上游视图或在 fixture pre-join。 |
| `Brnd_Nm` 空导致 merchant=null | **v2.5.1**:检查 `LLMEnricher.inferred_used_count`(应 ≥ 1);若 = 0,可能是 `Str_Nm` 也是空或匹配规则文案(`满50减10` 等)。 |
| Stage 1 启动即退 0 | `--source mock` 试通;若仍失败 → fixture 缺表 |
| LLM 大量 `JSONDecodeError` | 默认 `--provider mock` 试通;确认 mock fixture 完整 |
| 字典 reject 计数 > 0 | 查 `tag_enrichment_failures.jsonl` 中 `error="dict_rejection"`;可能需扩 `dim_dictionary.yaml` |
| 留存率 < 50% | 查 `cleaning_failures.jsonl` 看哪条规则触发多(legacy) |
| 划分报 item_id 冲突 | 输入有同 item 多分区重复;清洗先跑 |
| Hive 报 `AccessDenied` | 联系运维给本工程专用服务账号 + 表级 `SELECT` 权限 |

---

## 集成测试(自动化)

`tests/integration/` 覆盖 enrich / sft / 端到端。CI 100% 脱机可跑绿。

运行命令:

```bash
pytest agent-platform/training-data-synonym/tests/integration/ -v
```

---

## 相关文档

- [./spec.md](./spec.md) — v2.5 用户故事 / FR / SC
- [./plan.md](./plan.md) — 实现计划 / 项目结构
- [./data-model.md](./data-model.md) — 9 个实体 dataclass
- [./research.md](./research.md) — 14 个技术决策(D-001 ~ D-014)
- [./contracts/item_tags_v2.md](./contracts/item_tags_v2.md) — Stage 1 schema
- [./contracts/sft_corpus_v2.md](./contracts/sft_corpus_v2.md) — Stage 2 schema
- [./contracts/param_op_types_v2.md](./contracts/param_op_types_v2.md) — 8 维 × 4 op 映射
- [./contracts/hive_read_v1.md](./contracts/hive_read_v1.md) — Hive 读侧契约
- [../checklists/requirements.md](../checklists/requirements.md) — Spec quality checklist
- [../docs/ALIGNMENT_cib_o2o.md](../../docs/ALIGNMENT_cib_o2o.md) — 与 CIB O2O 业务对齐