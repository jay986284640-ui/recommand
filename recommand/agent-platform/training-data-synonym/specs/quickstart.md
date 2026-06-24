# Quickstart: 训练数据生成 (兴业 O2O 三品类 SFT 语料)

**Spec**: [./spec.md](./spec.md) (v2.4) | **Plan**: [./plan.md](./plan.md) | **Date**: 2026-06-22

---

## 概述

本指南提供 5 个**可运行**的端到端验证场景,每个场景给出:前置条件 / 命令 / 期望产出 / SC 自检。涵盖从 SQL 解析到 80/10/10 划分全流程。

**前置条件**:
- Python 3.11+(`python3 --version`)
- 安装依赖:`pip install -r agent-platform/training-data-synonym/requirements.txt`(含 pyyaml / jsonschema / tenacity / pytest / hypothesis)
- 已 clone 工程到本地,`cd` 到 `/opt/recommand/recommand`

**注意**:本工程 CI 完全脱机(`--source=mock` + `MockLLMClient`);无需 Hive 集群 / LLM 凭据即可跑通 demo。

---

## 场景 1 — SQL 解析 + 表角色识别(单步)

**目标**:验证 SQL 解析器从 `tabale_structer.sql` 抽出 8 张表的列 / 分区 / 角色。

**命令**:

```bash
python -m training_data_synonym.cli tables-meta \
  --sql /opt/recommand/recommand/tabale_structer.sql \
  --output /tmp/quickstart/tables_meta.json
```

**期望产出**:

- `/tmp/quickstart/tables_meta.json` 存在;8 个 TableMeta 元素(`o2o_new_gut_shop_base_third`, `o2o_new_gut_shop_base`, `o2o_new_gut_shop_address`, `o2o_new_gut_shop_category`, `o2o_new_gut_shop_category_meituan`, `o2o_new_gut_shop_category_mapping`, `o2o_new_gut_coupon_template`, `o2o_new_gut_coupon_shop`, `o2o_new_gut_discounts_pay`, `CDM_ADM_CUST_INFO_STAT_F`, `c10_ods_events_xysh`)。
- 至少包含 `meituan_shop / self_shop / coupon` 三核心表 + `address / category / coupon_shop` 三关联表的 `inferred_role`。
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
  --sql /opt/recommand/recommand/tabale_structer.sql \
  --source mock \
  --mock-fixture-dir agent-platform/training-data-synonym/tests/fixtures/hive/ \
  --n-items-per-type 100 \
  --output-dir /tmp/quickstart/enrich \
  --llm-source mock
```

**期望产出**:

- `/tmp/quickstart/enrich/item_tags.jsonl`:≥ 200 行(2 类门店各 ~100 + 券 ~100)
- `/tmp/quickstart/enrich/tag_enrichment_failures.jsonl`:存在(可能为空)
- `/tmp/quickstart/enrich/tag_enrichment_state.parquet`:存在
- `/tmp/quickstart/enrich/tables_meta.json`:存在(同场景 1)
- `/tmp/quickstart/enrich/summary.json`:存在,含 `stage=enrich / items_processed / llm_calls / dict_pass_rate / coverage / sc_pass`

**自检命令**:

```bash
# SC-002 字典合法率
jq -r '.tags | to_entries[] | select(.value != null and .key != "distance" and .key != "taste") | .value' \
  /tmp/quickstart/enrich/item_tags.jsonl \
  | sort -u | wc -l
# 期望: 与 dim_dictionary 中各 dim values 数之和相当

# SC-003 覆盖率
jq -s '[.[] | .tags | with_entries(select(.value != null)) | keys | length] | add / length' \
  /tmp/quickstart/enrich/item_tags.jsonl
# 期望: ≥ 7(8 维中至少 7 维非 null)

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

**目标**:从 Stage 1 输出生成多轮 SFT 语料 + 字典校验 + 清洗 + 分布统计。

**前置**:场景 2 完成。

**命令**:

```bash
python -m training_data_synonym.cli sft \
  --input /tmp/quickstart/enrich/item_tags.jsonl \
  --output-dir /tmp/quickstart/sft \
  --count-per-item 8 \
  --max-message-turns 5 \
  --llm-source mock
```

**期望产出**:

- `/tmp/quickstart/sft/sft_corpus.jsonl`:≥ 1600 行(200 items × 8)
- `/tmp/quickstart/sft/sft_failures.jsonl`:存在(占比 < 5%)
- `/tmp/quickstart/sft/cleaned_training_data.jsonl`:≥ 85% 留存
- `/tmp/quickstart/sft/cleaning_failures.jsonl`:存在
- `/tmp/quickstart/sft/distribution_report.json`:存在
- `/tmp/quickstart/sft/summary.json`:存在

**自检命令**:

```bash
# SC-004 JSONL 解析
jq -c . /tmp/quickstart/sft/sft_corpus.jsonl | head -1
# 期望: 单行 JSON,无 error

# SC-005 单 item 全维度覆盖率
jq -s 'group_by(.item_id) | map({
  item_id: .[0].item_id,
  total_dims: 8,
  covered: (map(.covered_dims[]) | unique | length),
  expected: 8
}) | map(select(.covered < .expected))' /tmp/quickstart/sft/sft_corpus.jsonl
# 期望: 空数组

# SC-006 负样本比例(默认 0.10 ± 0.02)
jq -s 'map(select(.negative == true)) | length / length' /tmp/quickstart/sft/sft_corpus.jsonl
# 期望: 0.08 ~ 0.12

# SC-007 首句高频模板 ≤ 20%
jq -r '.messages[0].content' /tmp/quickstart/sft/sft_corpus.jsonl \
  | sort | uniq -c | sort -rn | head -3 | awk '{print $1}'
# 期望: top1 计数 / 总样本数 ≤ 0.20

# SC-008 留存率
jq -s 'length' /tmp/quickstart/sft/cleaned_training_data.jsonl
jq -s 'length' /tmp/quickstart/sft/sft_corpus.jsonl
# 计算 cleaned / raw ≥ 0.85
```

**SC 绑定**:SC-004 / SC-005 / SC-006 / SC-007 / SC-008。

---

## 场景 4 — 数据集 80/10/10 划分(0 泄露)

**目标**:从 `cleaned_training_data.jsonl` 划 train/val/test 三文件,验证无数据泄露。

**命令**:

```bash
python -m training_data_synonym.cli split \
  --input /tmp/quickstart/sft/cleaned_training_data.jsonl \
  --output-dir /tmp/quickstart/split \
  --train-ratio 0.8 --val-ratio 0.1 --test-ratio 0.1
```

**期望产出**:

- `/tmp/quickstart/split/train.jsonl`、`val.jsonl`、`test.jsonl` 三文件。
- 行数比例 ≈ 80/10/10 ± 2%。
- 任一 `item_id` 不跨集合。

**自检命令**:

```bash
# SC-009 比例
wc -l /tmp/quickstart/split/{train,val,test}.jsonl

# SC-009 0 泄露
diff <(jq -r '.item_id' /tmp/quickstart/split/train.jsonl | sort -u) \
     <(jq -r '.item_id' /tmp/quickstart/split/val.jsonl   | sort -u)
diff <(jq -r '.item_id' /tmp/quickstart/split/train.jsonl | sort -u) \
     <(jq -r '.item_id' /tmp/quickstart/split/test.jsonl  | sort -u)
diff <(jq -r '.item_id' /tmp/quickstart/split/val.jsonl   | sort -u) \
     <(jq -r '.item_id' /tmp/quickstart/split/test.jsonl  | sort -u)
# 期望: 全为空
```

**SC 绑定**:SC-009。

---

## 场景 5 — 端到端(`--stage all`) + SC 自动自检

**目标**:一次跑完两阶段 + 划分,自动对照 11 个 SC 报告通过情况。

**命令**:

```bash
python -m training_data_synonym.cli all \
  --sql /opt/recommand/recommand/tabale_structer.sql \
  --source mock \
  --mock-fixture-dir agent-platform/training-data-synonym/tests/fixtures/hive/ \
  --output-dir /tmp/quickstart/e2e \
  --n-items-per-type 50 \
  --count-per-item 8 \
  --llm-source mock

python -m training_data_synonym.cli verify \
  --output-dir /tmp/quickstart/e2e \
  --format human
```

**期望产出**:

- `/tmp/quickstart/e2e/` 包含完整产物集(item_tags / sft_corpus / cleaned / train|val|test / summary)。

---

## 场景 6 — `extract-dictionary` 字典扩量离线(US4 / Stage 0)

**目标**:从 Hive 真实数据抽取品牌 + 分类候选,产出可审核 diff 报告(**离线工具,不污染主流水线**)。

**命令**:

```bash
python -m training_data_synonym.cli extract-dictionary \
  --sql /opt/recommand/recommand/tabale_structer.sql \
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
  --source mock --fixture-dir tests/fixtures/hive \
  --output-dir /tmp/quickstart/enrich_v2
# 验证: enrichment_state 中所有 item 的 dict_version 都变 → Stage 1 重算触发
```

**SC 绑定**:SC-012 / SC-013 / SC-014(US4 全套验证)。
- `verify` 输出 11 项 SC 状态,均 ✅。

**自检命令**:

```bash
cat /tmp/quickstart/e2e/verify_report.json | jq '.sc_results | to_entries | map({id: .key, pass: .value})'
```

**SC 绑定**:SC-001 ~ SC-011 全部。

---

## 单脚本(legacy demo)

为兼容早期 demo 脚本(已有用户),保留 `scripts/generate_training_data.py` 薄壳:

```bash
bash agent-platform/training-data-synonym/scripts/demo.sh
# 等价:场景 2 + 场景 3 + 场景 4 全跑,~1 分钟
```

---

## 生产部署场景(参考)

不在 CI 跑通路径中,留给部署运维执行:

```bash
# 生产:Hive + 真实 LLM
python -m training_data_synonym.cli all \
  --sql /opt/recommand/recommand/tabale_structer.sql \
  --source hive \
  --catalog spark_catalog \
  --etl-dt-mode latest_n --latest-n 7 \
  --output-dir /var/lib/training_data_synonym/prod/$(date +%Y%m%d) \
  --llm-source platform   # 见 research.md D-002 / data-pipeline LLMClient 抽象
```

---

## 故障定位

| 现象 | 排查方向 |
|------|---------|
| Stage 1 启动即退 0 | `--source mock` 试通;若仍失败 → fixture 缺表 |
| LLM 大量 `JSONDecodeError` | `--llm-source mock` 试通;确认 mock fixture 完整 |
| 字典合法率 < 100% | 检查 `configs/dim_dictionary.yaml` 是否最新 |
| 留存率 < 50% | 查 `cleaning_failures.jsonl` 看哪条规则触发多 |
| 划分报 item_id 冲突 | 输入有同 item 多分区重复;清洗先跑 |
| Hive 报 `AccessDenied` | 联系运维给本工程专用服务账号 + 表级 `SELECT` 权限 |

---

## 集成测试(自动化)

`tests/integration/test_pipeline_end_to_end.py` 覆盖场景 5;CI 100% 脱机可跑绿。

运行命令:

```bash
pytest agent-platform/training-data-synonym/tests/integration/ -v
```

---

## 相关文档

- [./spec.md](./spec.md) — v2.4 用户故事 / FR / SC
- [./plan.md](./plan.md) — 实现计划 / 项目结构
- [./data-model.md](./data-model.md) — 9 个实体 dataclass
- [./research.md](./research.md) — 14 个技术决策(D-001 ~ D-014)
- [./contracts/item_tags_v2.md](./contracts/item_tags_v2.md) — Stage 1 schema
- [./contracts/sft_corpus_v2.md](./contracts/sft_corpus_v2.md) — Stage 2 schema
- [./contracts/param_op_types_v2.md](./contracts/param_op_types_v2.md) — 8 维 × 4 op 映射
- [./contracts/hive_read_v1.md](./contracts/hive_read_v1.md) — Hive 读侧契约
- [../checklists/requirements.md](../checklists/requirements.md) — Spec quality checklist
- [../docs/ALIGNMENT_cib_o2o.md](../../docs/ALIGNMENT_cib_o2o.md) — 与 CIB O2O 业务对齐