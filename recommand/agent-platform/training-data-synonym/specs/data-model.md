# Data Model: 训练数据生成 (兴业 O2O 三品类 SFT 语料)

**Version**: `v2.5` | **Date**: 2026-06-23
**Spec**: [./spec.md](./spec.md) (v2.5)
**Companion**: [./contracts/item_tags_v2.md](./contracts/item_tags_v2.md) · [./contracts/sft_corpus_v2.md](./contracts/sft_corpus_v2.md) · [./contracts/param_op_types_v2.md](./contracts/param_op_types_v2.md) · [./contracts/hive_read_v1.md](./contracts/hive_read_v1.md)

---

## 概述

本工程(Stage 1 标签补全 + Stage 2 SFT 语料生成)涉及 **9 个核心实体**:

| # | 实体 | Python dataclass | JSON 形态 | 来源/去向 |
|---|------|----------------|-----------|----------|
| 1 | `TableMeta` | `TableMeta` | `tables_meta.json` 元素 | SQL 解析产物 |
| 2 | `HiveReadSpec` | `HiveReadSpec` | CLI args + config 节 | 运行时配置 |
| 3 | `RawRecord` | `RawRecord` | `item_tags.jsonl.raw_record` | Hive 行 → Stage 1 入口 |
| 4 | `ItemTags` | `ItemTags` | `item_tags.jsonl` 行 | **Stage 1 主输出** |
| 5 | `TagSource` | `TagSource` | `item_tags.jsonl.tag_source` | 8 维每维来源 |
| 6 | `ParamSpec` | `ParamSpec` | `ItemTags.params[k]` / `SFTSample.params[k]` | 内嵌 |
| 7 | `SFTSample` | `SFTSample` | `sft_corpus_v2.jsonl` 行 | **Stage 2 主输出** |
| 8 | `MessageTurn` | `MessageTurn` | `SFTSample.messages[]` | 内嵌 |
| 9 | `DistributionReport` | `DistributionReport` | `distribution_report.json` | 清洗后统计 |

下游消费:`ItemTags` → `SFTSample` → 训练管线(`train.jsonl / val.jsonl / test.jsonl`)。

> **v2.5.2 变更(2026-06-27)**: 3-Stage Pipeline。Stage 1 (extract-tags)→snapshot→Stage 2 (enrich)→item_tags→Stage 3 (sft)→sft_corpus。Snapshot YAML 作为 Stage 1→Stage 2→Stage 3 的字典约束桥梁。
>
> **v2.5.1 变更(2026-06-26)**:
> - **字段契约**(`_meta.field_contract`):每种 role 声明 `required` / `optional` 字段;
>   loader 在加载时校验缺失并抛 `TablesConfigError`。修复了"上游 SQL 缺字段代码静默失败"
>   的隐患。
> - **禁隐式 JOIN**:`hive_reader.base.extract_geo` 移除 `address_row` 参数,
>   自拓展门店的 `Lng`/`Lat` 必须由上游 SQL 把 `o2o_new_gut_shop_address` JOIN 进来
>   (或 fixture pre-join)。代码不主动做跨表查询。
> - **名称 fallback 推断**(`enricher/name_inference.py`):当原始字段(`Brnd_Nm` /
>   `Cat_Nm` / `productDesc`)为空或为券抢购规则文案(满50减10 / 代金券 / 限时抢购 /
>   核销 / 优惠券)时,从商品名称(`Str_Nm` / `shopName` / `couponName`)按字典值做
>   最长子串匹配,推断 brand / category / taste / occasion。
> - 规则文案识别命中即**整体抑制**该 item 推断(避免误判)。
> - `LLMEnricher` 把 hints 注入 prompt(LLM 看到)→ LLM 返回 None 时替换(双重保护);
>   `ConsumableMapper` 当 `category=None` 时用 name 推断 category 再查 mapping。
> - 新增可观测性:`LLMEnricher.inferred_used_count`、`ConsumableMapper.inferred_count`,
>   `logger.info("name_hint_used", ...)` / `name_inferred_category` 结构化日志。
> - 新增 fixture:`tests/fixtures/hive/empty_brand.jsonl`(空 Brnd_Nm,可触发 name fallback)
>   + `tests/fixtures/hive/rule_text_coupon.jsonl`(规则文案,验证抑制逻辑)。
> - end-to-end demo coverage_avg 从 3.75 提升到 4.24(brand/category 维度从空 → 推断补齐)。
>
> **v2.5 变更(2026-06-26)**:
> - 实体 1 的输入从 `tabale_structer.sql` DDL 解析改为 `configs/tables.yaml` 显式声明。
>   加载器:`training_data_synonym.common.tables_config.load_tables_config(path) → list[TableMeta]`。
>   SQL 解析路径(`sql_parser.parser.parse_sql`)保留为 deprecated,新代码不再调用。
> - `EnrichmentPipeline` / `extract-dictionary` 同时接受 `--tables-config`(新)和 `--sql`(legacy)两个 flag。
> - `dim_dictionary.yaml` 中 merchant 取值从 19 扩展到 82;occasion 13;taste 14(新增 凉/微辣/通勤)。
> - 新增可观测性字段:`EnrichmentSummary.dict_rejected_count`、`LLMEnricher.rejection_count`、
>   `ConsumableMapper.rejection_count`;字典 reject 时写 `EnrichmentFailure(error="dict_rejection")`。

---

## 实体 1:`TableMeta`(YAML 表配置,v2.5)

`configs/tables.yaml` 显式声明 db / name / role / columns / type / sensitive flags,
加载器 `common/tables_config.load_tables_config(path) -> list[TableMeta]` 产出与旧 SQL 解析
完全相同的 `TableMeta` 数据类(下游零修改)。

| 字段 | Python 类型 | JSON 类型 | 说明 |
|------|------------|-----------|------|
| `db` | `str` | string | 数据库名(如 `recommand_workspace` / `cdm`) |
| `table_name` | `str` | string | 表名(全小写,与 DDL 一致) |
| `columns` | `List[ColumnMeta]` | array | 列元数据 |
| `columns[].name` | `str` | string | 列名(全小写) |
| `columns[].type` | `str` | string | SQL 类型(VARCHAR / BIGINT / TIMESTAMP ...) |
| `columns[].nullable` | `bool` | boolean | 是否可空(从 `NOT NULL` 推断;缺省 True) |
| `columns[].comment` | `Optional[str]` | string | DDL 注释(如 `'纬度'`) |
| `partition_keys` | `List[str]` | array<string> | 分区键(通常 `["etl_dt"]`) |
| `inferred_role` | `Role` | string | 推断的本工程角色(`meituan_shop / self_shop / coupon / address / category / coupon_shop / discount / customer / events / unknown`) |
| `_format_version` | `str` | string | 固定 `"table_meta_v1"` |

**dataclass 草图**:

```python
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum

class Role(str, Enum):
    MEITUAN_SHOP = "meituan_shop"
    SELF_SHOP = "self_shop"
    COUPON = "coupon"
    ADDRESS = "address"
    CATEGORY = "category"
    COUPON_SHOP = "coupon_shop"
    DISCOUNT = "discount"
    CUSTOMER = "customer"
    EVENTS = "events"
    UNKNOWN = "unknown"

@dataclass
class ColumnMeta:
    name: str
    type: str
    nullable: bool = True
    comment: Optional[str] = None

@dataclass
class TableMeta:
    db: str
    table_name: str
    columns: List[ColumnMeta]
    partition_keys: List[str] = field(default_factory=list)
    inferred_role: Role = Role.UNKNOWN
    _format_version: str = "table_meta_v1"
```

**role 推断规则**(`sql_parser/parser.py`):

- `table_name` 含 `shop_base_third` → `MEITUAN_SHOP`
- `table_name` = `shop_base`(无 `_third` / `_meituan` / `_address` 后缀)→ `SELF_SHOP`
- `table_name` 含 `coupon_template` → `COUPON`
- `table_name` 含 `shop_address` → `ADDRESS`
- `table_name` 含 `shop_category` → `CATEGORY`
- `table_name` 含 `coupon_shop` → `COUPON_SHOP`
- `table_name` 含 `discounts_pay` → `DISCOUNT`
- `table_name` 含 `cust_info_stat` → `CUSTOMER`
- `table_name` 含 `events` → `EVENTS`
- 其他 → `UNKNOWN`

**校验**:

- `tables_meta.json` 至少覆盖 `MEITUAN_SHOP / SELF_SHOP / COUPON` 三核心表 + `ADDRESS / CATEGORY / COUPON_SHOP` 三关联表(SC-001)。
- 任一核心表缺失 → 启动直接错误退出(FR-001 边界)。

---

## 实体 2:`HiveReadSpec`(运行时读侧规格)

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | `"hive" \| "mock"` | 来自 CLI `--source` |
| `hive.catalog` | `Optional[str]` | Spark catalog / PyHive 标识 |
| `hive.databases` | `Dict[str, str]` | `{"recommand_workspace": "recommand_workspace", "cdm": "cdm"}` |
| `etl_dt.mode` | `"single" \| "range" \| "latest_n"` | |
| `etl_dt.single` | `Optional[str]` | `YYYYMMDD` 单分区 |
| `etl_dt.range` | `Optional[Tuple[str, str]]` | `[start, end]` 闭区间 |
| `etl_dt.latest_n` | `Optional[int]` | 最近 N 个分区,默认 1 |
| `sample_n_per_type` | `Optional[int]` | demo 采样条数 |
| `sensitive_columns_blocklist` | `List[str]` | 读入后立即 drop 的列名 |

**dataclass 草图**:

```python
@dataclass
class HiveReadSpec:
    source: str                              # "hive" | "mock"
    catalog: Optional[str] = None
    databases: Dict[str, str] = field(default_factory=dict)
    etl_dt_mode: str = "latest_n"
    etl_dt_single: Optional[str] = None
    etl_dt_range: Optional[Tuple[str, str]] = None
    etl_dt_latest_n: int = 1
    sample_n_per_type: Optional[int] = 100
    sensitive_columns_blocklist: List[str] = field(default_factory=lambda: [
        "MASTERCARD_CUST_ID", "Crt_Psn_Id", "Opr_Psn_Id", "creator", "updatePerson"
    ])
```

**HiveReader 抽象**(`hive_reader/base.py`):

```python
class HiveReader(ABC):
    @abstractmethod
    def read(self, table_meta: TableMeta, spec: HiveReadSpec) -> Iterator[RawRecord]:
        """读指定表 + 敏感列剔除 + etl_dt 过滤"""
        ...
```

实现:`SparkHiveReader`(生产)/ `PyHiveReader`(备选)/ `MockHiveReader`(CI)。

---

## 实体 3:`RawRecord`(去敏行级原始数据)

| 字段 | 类型 | 说明 |
|------|------|------|
| `item_id` | `str` | 命名空间隔离:`mt-<Str_Id>` / `self-<shopId>` / `cpn-<couponId>` |
| `item_type` | `Role` | `MEITUAN_SHOP / SELF_SHOP / COUPON` 之一 |
| `raw` | `Dict[str, Any]` | Hive 原始列子集(**已剔除敏感列**);键名 = 列名全小写 |
| `shop_lng` | `Optional[float]` | 仅美团门店/自拓展门店有;coupon 经 join 后透传 |
| `shop_lat` | `Optional[float]` | 同上 |
| `etl_dt` | `str` | 来源分区(`YYYYMMDD`) |

**dataclass 草图**:

```python
@dataclass
class RawRecord:
    item_id: str
    item_type: Role
    raw: Dict[str, Any]
    shop_lng: Optional[float] = None
    shop_lat: Optional[float] = None
    etl_dt: str = ""
```

**约束**(HiveReader 出口必做):

- `sensitive_columns_blocklist` 内的列名 MUST NOT 出现在 `RawRecord.raw`。
- 单位测试 `test_hive_reader.py::test_sensitive_drop` 拦截任何泄露。
- `shop_lng / shop_lat` 取自 `Lng/Lat` 或 `longitude/latitude` 列(分别对应 `_third` 与 `address`);`shop_lng` 必须满足 |lng| ≤ 180 且非 0,否则视为缺失。

---

## 实体 4:`ItemTags`(Stage 1 主输出)

| 字段 | Python 类型 | JSON 类型 | 必填 | 说明 |
|------|------------|-----------|------|------|
| `item_id` | `str` | string | ✅ | 同 `RawRecord.item_id` |
| `item_type` | `Role` | string | ✅ | `meituan_shop / self_shop / coupon` |
| `raw_record` | `Dict[str, Any]` | object | ✅ | 原始列子集(含 `shop_lng / shop_lat` 若可得) |
| `tags` | `Dict[str, Optional[str \| List[str]]]` | object | ✅ | **8 维标签值**;`distance` 始终 `null`;其他 7 维可 null |
| `tag_source` | `TagSource` | object | ✅ | 8 维每维来源标记 |
| `enriched_at` | `datetime` | string(ISO8601) | ✅ | LLM 调用完成时间(UTC) |
| `llm_model` | `str` | string | ✅ | 用的 LLM 模型 ID |
| `_format_version` | `str` | string | ✅ | 固定 `"item_tags_v2"` |

**`tags` 字段顺序(固定)**:`category, consumable_type, merchant, avg_prc, distance, age, occasion, taste`(8 维)。

**dataclass 草图**:

```python
@dataclass
class ItemTags:
    item_id: str
    item_type: Role
    raw_record: Dict[str, Any]
    tags: Dict[str, Optional[Any]]           # 8 维,缺补 None
    tag_source: "TagSource"
    enriched_at: datetime = field(default_factory=lambda: datetime.utcnow())
    llm_model: str = ""
    _format_version: str = "item_tags_v2"
```

**完整示例**(美团门店):

```json
{
  "item_id": "mt-100234",
  "item_type": "meituan_shop",
  "raw_record": {
    "Str_Id": "100234",
    "Str_Nm": "星巴克(南京西路店)",
    "Cat_Id_NEW": 5,
    "Avg_Prc": "45",
    "Lng": "121.456789",
    "Lat": "31.234567",
    "etl_dt": "20260620"
  },
  "tags": {
    "category": "咖啡",
    "consumable_type": "drink",
    "merchant": "星巴克",
    "avg_prc": "30-50",
    "distance": null,
    "age": "25-35",
    "occasion": "下午茶",
    "taste": ["甜"]
  },
  "tag_source": {
    "category": "raw",
    "consumable_type": "derived",
    "merchant": "raw",
    "avg_prc": "raw",
    "distance": "geo",
    "age": "ai",
    "occasion": "raw",
    "taste": "ai"
  },
  "enriched_at": "2026-06-22T10:00:00Z",
  "llm_model": "claude-haiku-4-5",
  "_format_version": "item_tags_v2"
}
```

---

## 实体 5:`TagSource`(8 维来源标记)

**三族枚举语义**:

| 维 | 取值集 | 永不取 |
|----|--------|--------|
| `category` / `merchant` / `avg_prc` / `age` / `occasion` / `taste` | `raw / ai / missing` | — |
| `distance` | `geo / missing` | `ai` |
| `consumable_type` | `derived / ai / missing` | — |

**含义**:

- `raw`:从源表显式列直接抽取。
- `derived`:从其他维度确定性推导(仅 `consumable_type`)。
- `geo`:从源表 lng/lat 透传(仅 `distance`)。
- `ai`:LLM 推断并落字典。
- `missing`:源数据缺失或无法推断,该维 tag 值为 `null`。

**dataclass 草图**(强类型枚举):

```python
class TagOrigin(str, Enum):
    RAW = "raw"
    AI = "ai"
    DERIVED = "derived"
    GEO = "geo"
    MISSING = "missing"

@dataclass
class TagSource:
    category: TagOrigin
    consumable_type: TagOrigin
    merchant: TagOrigin
    avg_prc: TagOrigin
    distance: TagOrigin          # 仅 GEO / MISSING
    age: TagOrigin
    occasion: TagOrigin
    taste: TagOrigin
```

**校验**(Stage 1 出口必做):

- `distance ∈ {geo, missing}`;**任何非 geo/missing 值 → enricher 自身 bug 报警**。
- `consumable_type ∈ {derived, ai, missing}`。
- 其余 6 维 ∈ `{raw, ai, missing}`。
- `tag == null` ⇔ `tag_source == missing`(双向不变式)。

---

## 实体 6:`ParamSpec`(`params` 内嵌)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `op` | `str` | ✅ | 候选:`eq / in / contains / not_in`(本批实现);`gt / lt / between`(预留,本批字典校验拒) |
| `values` | `str \| List[str]` | ✅ | 类型跟 `op` 对应,详见 `contracts/param_op_types_v2.md` |

**dataclass 草图**:

```python
@dataclass
class ParamSpec:
    op: str
    values: Any            # str 或 List[str]
```

**op ↔ 维度 ↔ values 类型**(本批实现):

| dim | 允许 op | values 类型 |
|-----|--------|------------|
| `category` | `in` | `array<string>` |
| `consumable_type` | `eq` | `string`(单值 ∈ {food, drink, mixed, none}) |
| `merchant` | `in` | `array<string>` |
| `avg_prc` | `in` | `array<string>`(桶 ID) |
| `distance` | `in` / `not_in` | `array<string>`(桶 ID) |
| `age` | `in` | `array<string>` |
| `occasion` | `in` | `array<string>` |
| `taste` | `contains` / `not_in` | `array<string>` |

**校验步骤**(7 步,任一失败 → DictValidation):

1. 字段名白名单(8 维);多出 → `unexpected field: <name>`。
2. 缺失字段 → null 补齐(非 error)。
3. op 白名单(`eq / in / contains / not_in`);`gt/lt/between` 拒。
4. op 适用维度:`consumable_type` 仅 `eq`,`taste` 仅 `contains/not_in`,等等。
5. values 类型跟 op 对应。
6. values 字典校验(每项必须在 `dim_dictionary.yaml` 候选集合内)。
7. `in / contains / not_in` values 非空数组。

---

## 实体 7:`SFTSample`(Stage 2 主输出)

| 字段 | Python 类型 | JSON 类型 | 必填 | 说明 |
|------|------------|-----------|------|------|
| `item_id` | `str` | string | ✅ | 同 ItemTags.item_id |
| `item_type` | `Role` | string | ✅ | |
| `intent` | `str` | string | ✅ | `search_item / use_coupon / pay / view_order / browse` |
| `messages` | `List[MessageTurn]` | array | ✅ | 长度 1~5,首条 `role=user`,末条不限 |
| `params` | `Dict[str, Optional[ParamSpec]]` | object | ✅ | **8 维**,缺失补 None,顺序固定 |
| `order_by` | `Optional[str]` | string\|null | ✅ | `distance / price / rating / time / null` |
| `negative` | `bool` | boolean | ✅ | `true` = 负样本 |
| `negative_type` | `Optional[str]` | string\|null | ✅ | `null` / `reject` / `pivot` / `unsatisfiable` |
| `covered_dims` | `List[str]` | array<string> | ✅ | 该样本 params 实际覆盖的维度列表(用于 SC-005 自检) |
| `forced_coverage` | `bool` | boolean | ✅ | `true` = FR-011 强制补样 |
| `generated_at` | `datetime` | string(ISO8601) | ✅ | LLM 调用完成时间(UTC) |
| `llm_model` | `str` | string | ✅ | |
| `_format_version` | `str` | string | ✅ | 固定 `"sft_corpus_v2"` |

**dataclass 草图**:

```python
@dataclass
class SFTSample:
    item_id: str
    item_type: Role
    intent: str
    messages: List["MessageTurn"]
    params: Dict[str, Optional[ParamSpec]]
    order_by: Optional[str] = None
    negative: bool = False
    negative_type: Optional[str] = None
    covered_dims: List[str] = field(default_factory=list)
    forced_coverage: bool = False
    generated_at: datetime = field(default_factory=lambda: datetime.utcnow())
    llm_model: str = ""
    _format_version: str = "sft_corpus_v2"
```

**完整示例**:

```json
{
  "item_id": "mt-100234",
  "item_type": "meituan_shop",
  "intent": "search_item",
  "messages": [
    {"role": "user", "content": "想喝咖啡,500 米以内有没有"},
    {"role": "assistant", "content": "附近 200 米有星巴克,需要看菜单吗"},
    {"role": "user", "content": "好,下午想和同事一起,不要太甜的"}
  ],
  "params": {
    "category":         {"op": "in", "values": ["咖啡"]},
    "consumable_type":  {"op": "eq", "values": "drink"},
    "merchant":         null,
    "avg_prc":          null,
    "distance":         {"op": "in", "values": ["0-500"]},
    "age":              null,
    "occasion":         {"op": "in", "values": ["下午茶"]},
    "taste":            {"op": "not_in", "values": ["甜"]}
  },
  "order_by": "distance",
  "negative": false,
  "negative_type": null,
  "covered_dims": ["category", "consumable_type", "distance", "occasion", "taste"],
  "forced_coverage": false,
  "generated_at": "2026-06-22T10:05:00Z",
  "llm_model": "claude-haiku-4-5",
  "_format_version": "sft_corpus_v2"
}
```

---

## 实体 8:`MessageTurn`(`messages[]` 元素)

| 字段 | Python 类型 | JSON 类型 | 必填 | 说明 |
|------|------------|-----------|------|------|
| `role` | `str` | string | ✅ | `user / assistant / system` |
| `content` | `str` | string | ✅ | 自然语言 UTF-8,**不含 tab / 控制字符 / 连续 ≥3 换行** |

**dataclass 草图**:

```python
@dataclass
class MessageTurn:
    role: str              # "user" | "assistant" | "system"
    content: str
```

**约束**:

- `messages[0].role == "user"`(首条必为用户)
- `messages` 长度 ∈ [1, 5](由 `sft.max_message_turns=5` 控制)
- `content` 长度 ≥ 10 字(清洗规则 2 阈值)

---

## 实体 9:`DistributionReport`(清洗后统计)

| 字段 | Python 类型 | JSON 类型 | 说明 |
|------|------------|-----------|------|
| `total_samples` | `int` | int | 清洗后样本数 |
| `intent_distribution` | `Dict[str, int]` | object | 5 类 intent 计数 |
| `param_coverage` | `Dict[str, Dict[str, int]]` | object | 每维 `null / non_null` 计数 |
| `op_distribution` | `Dict[str, int]` | object | 4 op 计数 |
| `negative_distribution` | `Dict[str, int]` | object | `positive / reject / pivot / unsatisfiable` 计数 |
| `turn_distribution` | `Dict[int, int]` | object | 1/2/3/4/5 轮计数 |
| `avg_message_length` | `float` | number | 平均 content 字数 |
| `dict_coverage` | `Dict[str, int]` | object | 字典候选值在样本中的出现次数 |
| `param_combo_count` | `int` | int | 唯一 params 组合数 |
| `warnings` | `List[str]` | array<string> | 报警(不平衡 / 长尾等) |
| `_format_version` | `str` | string | 固定 `"distribution_report_v1"` |

**8 项分布指标**(对应 SC-009,详见 `contracts/...` 与 spec SC-009):

| 指标 | 目标 | 不达标动作 |
|------|------|------------|
| 5 类 intent 比例 | 每类 ≥ 3% | 报警 + 过采样 |
| 8 维 params 非 null 比例 | 每维 ≥ 5% | 报警 + 过采样 |
| 4 op 比例 | `not_in` ≥ 3% | 报警 + 过采样 |
| 负样本比例 | `negative_ratio` ±0.02 | 报警 |
| 对话轮次分布 | 1/2/3/4/5 = 10/20/35/25/10% ±5% | 报警 |
| 消息平均长度 | 20~80 字 | 报警 |
| 字典覆盖率 | 每候选值 ≥ 5 次 | 报警 |
| params 组合多样性 | 1000 样本 ≥ 200 唯一组合 | 报警 |

---

## 状态实体(增量指纹)

### `EnrichmentState`(Stage 1 增量)

| 字段 | 类型 | 说明 |
|------|------|------|
| `item_id` | `str` | |
| `raw_md5` | `str` | raw record 字段级 md5 |
| `dict_version` | `str` | `dim_dictionary.yaml._meta.version` × `consumable_type_map.yaml._meta.version` 联合 md5 |
| `source_partition` | `str` | `etl_dt` |
| `enriched_at` | `datetime` | |
| `llm_model` | `str` | |

持久化:Parquet 文件 `tag_enrichment_state.parquet`。

**重算条件**:4 元组任一字段变化即重算。

### `SFTState`(Stage 2 增量)

| 字段 | 类型 | 说明 |
|------|------|------|
| `item_id` | `str` | |
| `tags_md5` | `str` | 8 维 tags 字段级 md5 |
| `enrichment_format_version` | `str` | `item_tags_v2` 等 |
| `sft_format_version` | `str` | `sft_corpus_v2` |
| `generated_at` | `datetime` | |

---

## 失败实体

### `EnrichmentFailure`

```python
@dataclass
class EnrichmentFailure:
    item_id: str
    raw_response: Optional[str]      # LLM 原始输出
    error: str                        # JSONDecodeError | MissingField | DictValidation | Timeout | GeoMissing | Other
    error_detail: str
    occurred_at: datetime
```

### `SFTFailure`

```python
@dataclass
class SFTFailure:
    item_id: str
    raw_response: Optional[str]
    error: str                        # 同上 + DistanceAlignmentError | CoverageFailure
    error_detail: str
    target_params: Dict[str, Any]     # 期望 ground-truth,便于复盘
    occurred_at: datetime
```

---

## 数据流总览

```text
tabale_structer.sql ──┐
                      ├─→ sql_parser → tables_meta.json
                      │
Hive / Mock fixtures ─┴─→ HiveReader(spark | pyhive | mock)
                            │
                            ▼
                         RawRecord (去敏)
                            │
                            ▼
                 Enricher:
                   ├─ llm_enricher (6 维 LLM 兜底)
                   ├─ distance_geo (lng/lat 透传 → tag_source.distance)
                   ├─ consumable_mapper (category → food/drink/mixed/none)
                   └─ state (增量指纹)
                            │
                            ▼
                     item_tags_v2.jsonl
                            │
                            ▼
                 SFTPipeline:
                   ├─ sample_planner (8 维覆盖率规划 + 强制补样)
                   ├─ distance_sampler (distance / order_by 字典直采 + 耦合)
                   ├─ negative_sampler (3 类负样本)
                   ├─ intent_assigner (5 类 intent + 三品类倾向)
                   ├─ diversity (句式模板随机)
                   └─ llm_generator + validator (8 维 ground-truth 注入)
                            │
                            ▼
                     sft_corpus_v2.jsonl
                            │
                            ▼
                 Cleaner (7 类规则) → DistributionReport → Splitter (80/10/10)
                            │
                            ▼
              train.jsonl / val.jsonl / test.jsonl + summary.json
```

---

## 兼容性 / 版本

| 产物 | `_format_version` | v1 是否兼容 |
|------|-------------------|------------|
| `tables_meta.json` | `table_meta_v1` | 新 |
| `item_tags.jsonl` | `item_tags_v2` | **不兼容 v1**(`tag_source` 拆分 3 族,字段数 7→8) |
| `sft_corpus.jsonl` | `sft_corpus_v2` | **不兼容 v1**(`consumable_type` / `negative_type` / `covered_dims` / `forced_coverage` 新增) |
| `distribution_report.json` | `distribution_report_v1` | 新 |
| `train/val/test.jsonl` | `train_split_v1` | 行级同 `sft_corpus_v2`,仅拆分 |

读侧契约:`sft_corpus_v1` 客户端必须拒绝 `_format_version != "sft_corpus_v2"` 的样本(报 TypeError);`sft_corpus_v2` 客户端可降级读 `v1`(忽略新增字段),反向不兼容。

---

## v1 → v2 迁移说明

`v1 → v2` 是一次**主版本** 升级(spec.md §Changelog):

1. **7 维 → 8 维**:新增 `consumable_type`。
2. **`tag_source` 拆分 3 族枚举**:`distance` 从 `raw / ai / missing` 缩为 `geo / missing`;`consumable_type` 独占 `derived`。
3. **Stage 1 输入源变更**:`item_features_ai.jsonl` → Hive 直读。
4. **Stage 2 `distance` 路径变更**:LLM 推断 / 几何计算 → **字典直采**。
5. **Stage 2 SFT 训练目标明确化**:**提参准确性**(spec Clarifications Q3);不再关心几何数据。
6. **新增字段**:`negative_type` / `covered_dims` / `forced_coverage`。

迁移路径:旧 v1 训练数据通过 `tools/migrate_v1_to_v2.py`(计划期实现)统一转换为 v2 schema 后,才能进 v2 训练管道。

---

## 实体 10:`RawRow`(Stage 0 字典抽取的原始行)

| 字段 | Python 类型 | JSON 类型 | 说明 |
|------|------------|-----------|------|
| `name` | `str` | string | 原始 `Brnd_Nm` / `Cat_Nm` 字符串 |
| `frequency` | `int` | int | 出现频次 |
| `sources` | `set[str]` | array<string> | 来源表(`o2o_new_gut_shop_base_third` 等)|

**dataclass 草图**:

```python
@dataclass
class RawRow:
    name: str
    frequency: int = 0
    sources: set[str] = field(default_factory=set)
```

---

## 实体 11:`BrandCluster` / `CategoryCluster`(Stage 0 聚类输出)

| 字段 | 类型 | 说明 |
|------|------|------|
| `canonical` | `str` | 聚类 canonical 名(频次最高的变体)|
| `aliases` | `List[str]` | 合并的所有变体(去括号、去 `Co./Ltd.` 后)|
| `frequency` | `int` | 所有变体频次加和 |
| `n_variants` | `int` | 合并的变体数 |
| `sample_aliases` | `List[str]` | 前 5 个 alias 示例(brand 用)|

**dataclass 草图**:

```python
@dataclass
class BrandCluster:
    canonical: str
    aliases: list[str]
    frequency: int
    n_variants: int
    sample_aliases: list[str]

@dataclass
class CategoryCluster:
    canonical: str
    aliases: list[str]
    frequency: int
    n_variants: int
```

---

## 实体 12:`DictDiffReport`(Stage 0 diff 报告)

| 字段 | 类型 | 说明 |
|------|------|------|
| `_meta` | `Dict[str, Any]` | 抽取统计(raw_count / normalized_count / added_count / removed_count / frequency_min / levenshtein_threshold / jaccard_threshold)|
| `added` | `List[Dict]` | 候选新词项(`name` / `frequency` / `n_variants` / `sample_aliases`)|
| `existing` | `List[Dict]` | 已收录的(`name` / `frequency`)|
| `removed` | `List[Dict]` | yaml 有但 Hive 无的(`name`)|

**写入**:`dict_candidates/brands_diff.yaml` / `categories_diff.yaml`(人工 PR review 入口)。