# Contract: Hive 读侧接口 (`hive_read_v1`)

**Version**: `v1` | **Date**: 2026-06-22
**Spec**: [../spec.md](../spec.md) (v2.4)
**Companion**: [item_tags_v2.md](./item_tags_v2.md) · [data-model.md §实体 2,3](../data-model.md)

---

## 概述

Stage 1 在启动时按 `etl_dt` 分区从 Hive 拉取原始行级数据。本契约定义 `HiveReader` 抽象 + `HiveReadSpec` 运行时规格,以及 mock 实现的可观察行为。

**单一职责**:`HiveReader` 只做"按表 + 按分区读 + 敏感列剔除 + item_id 合成 + raw_record 透传",不做 LLM 推断、不做字段级语义补全(交给 `enricher` 子模块)。

---

## 抽象接口

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Dict, List, Optional, Tuple, Any

from .data_model import TableMeta, RawRecord          # 详见 data-model.md §实体 1,3

@dataclass(frozen=True)
class HiveReadSpec:
    """运行时读侧规格(spec §FR-003 + Configuration Snapshot 'input.hive')"""
    source: str = "hive"                              # "hive" | "mock"
    catalog: Optional[str] = None
    databases: Dict[str, str] = field(default_factory=lambda: {
        "recommand_workspace": "recommand_workspace",
        "cdm": "cdm",
    })
    etl_dt_mode: str = "latest_n"                     # "single" | "range" | "latest_n"
    etl_dt_single: Optional[str] = None              # "YYYYMMDD"
    etl_dt_range: Optional[Tuple[str, str]] = None    # ("YYYYMMDD", "YYYYMMDD") 闭区间
    etl_dt_latest_n: int = 1
    sample_n_per_type: Optional[int] = 100            # demo;None = 全量
    sensitive_columns_blocklist: List[str] = field(default_factory=lambda: [
        "MASTERCARD_CUST_ID", "Crt_Psn_Id", "Updt_Psn_Id", "Opr_Psn_Id",
        "creator", "updatePerson",
    ])

class HiveReader(ABC):
    @abstractmethod
    def list_partitions(self, table_meta: TableMeta) -> List[str]:
        """列出可用 etl_dt 分区(`YYYYMMDD` 列表,降序);
        失败 → 抛 `ConnectionError / AccessDenied / EmptyPartitionSet`"""

    @abstractmethod
    def read(self, table_meta: TableMeta, spec: HiveReadSpec) -> Iterator[RawRecord]:
        """按 spec.etl_dt 选择分区,读出每行;
        必须做的强制步骤:
          1. 敏感列剔除(spec.sensitive_columns_blocklist)
          2. item_id 合成(命名空间隔离,见下)
          3. shop_lng / shop_lat 抽取(若可得)
        输出 RawRecord 列表(Yield);失败 → 抛对应异常
        """

    def read_all_three_core(
        self, tables_meta: List[TableMeta], spec: HiveReadSpec
    ) -> Dict[Role, List[RawRecord]]:
        """便捷:读美团门店 / 自拓展门店 / 优惠券 三张核心表;按 Role 聚合输出"""
        ...
```

---

## `item_id` 合成规则

| 源表 | 合成 item_id |
|------|-------------|
| `o2o_new_gut_shop_base_third`(美团门店) | `mt-<Str_Id>` |
| `o2o_new_gut_shop_base`(自拓展门店) | `self-<shopId>` |
| `o2o_new_gut_coupon_template`(优惠券) | `cpn-<couponId>` |

**冲突检测**:三命名空间天然隔离,但同一前缀内重复必须抛 `DuplicateItemIdError`(理论上不应发生,运行时 catch 即查 DDL 漂移)。

---

## `shop_lng / shop_lat` 抽取规则(FR-008b)

| 源表 / join 路径 | 列 |
|------------------|-----|
| `o2o_new_gut_shop_base_third` | `Lng` → `shop_lng`,`Lat` → `shop_lat`(直读) |
| `o2o_new_gut_shop_base` + `o2o_new_gut_shop_address` join by `shopId` | `address.longitude` → `shop_lng`,`address.latitude` → `shop_lat`(优先取第一条非空记录) |
| `o2o_new_gut_coupon_template` + `o2o_new_gut_coupon_shop` join → `coupon_shop.merchantId` → 关联门店 → 上述 1/2 规则 | 同上 |

**合法性检查**(失败 → `shop_lng / shop_lat = None`):

- 缺失 / NULL
- 字符串 `"null"` / `"NULL"` / `""`
- `|value| > 180` (lng) / `|value| > 90` (lat)
- `(0, 0)` 占位(无效坐标)
- `NaN` / `Inf`(极少但防御)

---

## 异常类型(必须定义)

| 异常 | 触发条件 | 处理 |
|------|---------|------|
| `ConnectionError` | Hive 集群不可达 / 网络层失败 | Stage 1 启动即退出非 0,打印诊断 |
| `AccessDenied` | Kerberos / LDAP / 表权限不足 | 同上,提示运维申请权限 |
| `EmptyPartitionSet` | 目标 `etl_dt` 模式命中 0 个分区 | Stage 1 启动即退出非 0,提示调整 `--etl-dt` |
| `SchemaDriftError` | Hive 实际列与 `TableMeta` 不匹配(新增 / 列改名) | 自动忽略未声明列,对缺失列填 null,**继续**(spec Edge Cases 边界) |
| `DuplicateItemIdError` | 同表内同一源 ID 出现多行 | 报警 + 取首行,继续 |

---

## 实现:`SparkHiveReader`(生产,默认)

```python
class SparkHiveReader(HiveReader):
    """基于 PySpark Hive Catalog 的生产实现"""

    def __init__(self, catalog: str = "spark_catalog"):
        self._spark = SparkSession.builder \
            .appName("training_data_synonym") \
            .enableHiveSupport() \
            .getOrCreate()
        self._catalog = catalog

    def list_partitions(self, table_meta: TableMeta) -> List[str]:
        full = f"{self._catalog}.{table_meta.db}.{table_meta.table_name}"
        df = self._spark.sql(f"SHOW PARTITIONS {full}")
        return sorted([r[0].split("=")[1] for r in df.collect()], reverse=True)

    def read(self, table_meta: TableMeta, spec: HiveReadSpec) -> Iterator[RawRecord]:
        full = f"{self._catalog}.{table_meta.db}.{table_meta.table_name}"

        # 1. 选分区
        partitions = self._select_partitions(table_meta, spec)
        if not partitions:
            raise EmptyPartitionSet(f"No partitions for {full} with spec={spec}")
        partition_filter = " OR ".join(
            f"etl_dt='{p}'" for p in partitions
        )

        # 2. 投影(剔除敏感列)
        columns = [c.name for c in table_meta.columns
                   if c.name not in spec.sensitive_columns_blocklist]
        projection = ", ".join(columns)

        # 3. 查询
        sql = f"SELECT {projection} FROM {full} WHERE {partition_filter}"
        df = self._spark.sql(sql)

        # 4. 行级处理(去敏 / item_id 合成 / lng/lat 抽取)
        for row in df.toLocalIterator():
            raw = row.asDict(recursive=True)
            item_id = self._synthesize_item_id(table_meta, raw)
            shop_lng, shop_lat = self._extract_geo(table_meta, raw)
            raw.pop("etl_dt", None)        # 不写到 raw_record(已在 RawRecord.etl_dt)
            yield RawRecord(
                item_id=item_id,
                item_type=role_from_tablename(table_meta.table_name),
                raw=raw,
                shop_lng=shop_lng,
                shop_lat=shop_lat,
                etl_dt=raw.get("etl_dt") or partitions[0],
            )
```

**生产部署**:`--source=hive --catalog=spark_catalog`(具体 catalog 由部署方注入)。

---

## 实现:`PyHiveReader`(备选后端,无 Spark 环境)

```python
class PyHiveReader(HiveReader):
    """基于 PyHive HiveServer2 的轻量后端;无分区下推优化,大表不推荐"""

    def __init__(self, host: str, port: int = 10000, auth: str = "KERBEROS"):
        self._conn = hive.Connection(host=host, port=port, auth=auth)

    def list_partitions(self, table_meta: TableMeta) -> List[str]:
        with self._conn.cursor() as cur:
            cur.execute(f"SHOW PARTITIONS {table_meta.db}.{table_meta.table_name}")
            rows = cur.fetchall()
            return sorted([r[0].split("=")[1] for r in rows], reverse=True)

    def read(self, table_meta: TableMeta, spec: HiveReadSpec) -> Iterator[RawRecord]:
        # 同 SparkHiveReader 的 4 步;分区过滤用 WHERE etl_dt IN ('...');逐行 fetch
        ...
```

**使用场景**:运维无 Spark 但有 HiveServer2;Stage 1 退化为单线程读(可接受)。

---

## 实现:`MockHiveReader`(CI / 开发,默认在 CI 路径)

```python
class MockHiveReader(HiveReader):
    """读 tests/fixtures/hive/*.jsonl;不连任何外部系统"""

    def __init__(self, fixture_dir: Path):
        self._fixture_dir = fixture_dir

    def list_partitions(self, table_meta: TableMeta) -> List[str]:
        # fixture 文件名直接是表名,返回 ["20260620"] 单一虚拟分区
        return ["20260620"]

    def read(self, table_meta: TableMeta, spec: HiveReadSpec) -> Iterator[RawRecord]:
        fixture = self._fixture_dir / f"{table_meta.table_name}.jsonl"
        with fixture.open() as f:
            records = [json.loads(line) for line in f if line.strip()]

        # 模拟采样
        if spec.sample_n_per_type:
            records = records[: spec.sample_n_per_type]

        for rec in records:
            # 1. 敏感列剔除
            for col in spec.sensitive_columns_blocklist:
                rec.pop(col, None)

            # 2. item_id 合成
            item_id = self._synthesize_item_id(table_meta, rec)

            # 3. shop_lng / shop_lat 抽取(若表含)
            shop_lng, shop_lat = self._extract_geo(table_meta, rec)

            # 4. etl_dt 注入(若缺失)
            etl_dt = rec.get("etl_dt", "20260620")
            rec.pop("etl_dt", None)

            yield RawRecord(
                item_id=item_id,
                item_type=role_from_tablename(table_meta.table_name),
                raw=rec,
                shop_lng=shop_lng,
                shop_lat=shop_lat,
                etl_dt=etl_dt,
            )
```

**fixture 必含表**(见 `research.md` D-013):

```text
tests/fixtures/hive/
├── o2o_new_gut_shop_base_third.jsonl
├── o2o_new_gut_shop_base.jsonl
├── o2o_new_gut_shop_address.jsonl
├── o2o_new_gut_coupon_template.jsonl
├── o2o_new_gut_coupon_shop.jsonl
├── o2o_new_gut_shop_category_meituan.jsonl
└── o2o_new_gut_shop_category_mapping.jsonl
```

每张表 ≥ 100 行;美团门店行含 50 行有 `Lng/Lat` + 50 行无(测试 `geo / missing` 两分支);自拓展门店地址覆盖 80%(测 join 缺失分支);券-门店绑定覆盖 70%(测多门店 / 无门店两个分支)。

---

## 行为差异表(CI vs 生产)

| 行为 | MockHiveReader | SparkHiveReader | PyHiveReader |
|------|----------------|----------------|--------------|
| 读分区 | 单一虚拟 `"20260620"` | 实际 `SHOW PARTITIONS` | 实际 `SHOW PARTITIONS` |
| 采样 | `records[:n]` | 无 native 采样 → SQL `LIMIT` | SQL `LIMIT` |
| 性能 | 内存读取,几秒 | 真实 Spark,JVM 启动 10s + scan 时间 | 单线程,大表慢 |
| 触发异常场景 | 通过 fixture 构造 | 真异常 | 真异常 |
| 凭证 | 无 | Spark 客户端 + Kerberos | HiveServer2 + 认证 |

**契约不变性**:三种实现 MUST 在相同 `TableMeta + HiveReadSpec + fixture` 下产生**同构**的 `RawRecord` 列表(行级字段、子集、敏感列剔除结果一致)。

---

## 与 SQL 解析的接口

`HiveReader` 接受 `TableMeta`(由 `sql_parser` 产出)而非表名字符串:

```python
def read_all_three_core(
    self, tables_meta: List[TableMeta], spec: HiveReadSpec
) -> Dict[Role, List[RawRecord]]:
    by_role = {}
    for tm in tables_meta:
        role = role_from_tablename(tm.table_name)    # e.g. MEITUAN_SHOP
        if role not in {Role.MEITUAN_SHOP, Role.SELF_SHOP, Role.COUPON}:
            continue
        by_role[role] = list(self.read(tm, spec))
    return by_role
```

**为什么用 TableMeta**:① 验证 SQL 解析产物的列与 Hive 一致(契约测试 `test_hive_read_spec.py::test_tablemeta_vs_hive_schema`);② 敏感列剔除、白名单用同一份"声明";③ 加 join(`o2o_new_gut_coupon_shop` → `o2o_new_gut_shop_base`)时只需加 1 张 `TableMeta`。

---

## 校验与契约测试(`tests/contract/test_hive_read_spec.py`)

| 测试用例 | 断言 |
|---------|------|
| `test_three_core_partition_present` | `list_partitions()` 三核心表均非空;否则 `EmptyPartitionSet` |
| `test_sensitive_columns_dropped` | 任一 fixture / 真实 Hive 行,sensitive 列 MUST NOT 在 `RawRecord.raw` |
| `test_item_id_namespace` | 同一 `item_id` 跨三品类不重名(`mt-*` / `self-*` / `cpn-*`) |
| `test_geo_extraction_valid` | 有 lng/lat 的行 → `shop_lng / shop_lat` 非 None 且在合法范围 |
| `test_geo_missing_becomes_none` | 缺失 / (0,0) / 越界 → `shop_lng / shop_lat` 均为 None |
| `test_coupon_lnglat_via_binding` | `coupon` 行通过 `o2o_new_gut_coupon_shop` 链式 join 取关联门店 lng/lat |
| `test_mock_matches_production_schema` | MockHiveReader 与 SparkHiveReader 在相同 fixture 下产出同构 `RawRecord`(字段集合一致) |
| `test_etl_dt_filter` | `etl_dt_mode=single / range / latest_n` 三种模式均生效 |

---

## 配置:`pipeline.yaml.input.hive` 段

```yaml
training_data_synonym:
  input:
    source: hive                          # hive | mock
    hive:
      catalog: spark_catalog              # 由部署方注入
      databases:
        recommand_workspace: recommand_workspace
        cdm: cdm
      etl_dt:
        mode: latest_n
        latest_n: 1
        # range: ["20260601", "20260615"]
        # single: "20260620"
      sample_n_per_type: 100             # demo;全量留空
      sensitive_columns_blocklist:
        - MASTERCARD_CUST_ID
        - Crt_Psn_Id
        - Opr_Psn_Id
        - creator
        - updatePerson
    mock:
      fixture_dir: ./tests/fixtures/hive/
    item_types: [meituan_shop, self_shop, coupon]
```

---

## 安全性(A-008 + Constitution V)

- `HiveReader.read()` 出口前 MUST 做"敏感列剔除断言":对 `spec.sensitive_columns_blocklist` 每列,断言 `not in RawRecord.raw.keys()`。失败 → 抛 `SensitiveLeakError`(单测 `test_hive_reader.py::test_sensitive_drop` 拦截)。
- `shop_lng / shop_lat` 保留(非个人字段),但精度截到 6 位小数(约 11cm);不视为 PII。
- 所有日志输出 MUST NOT 打印 `RawRecord.raw` 完整内容,只打 `item_id` / `item_type` / `etl_dt` 元信息。