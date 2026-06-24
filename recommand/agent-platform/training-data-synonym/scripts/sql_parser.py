"""SQL 表结构解析器

解析 Hive 风格的 CREATE TABLE 语句,提取:
  - schema (数据库)
  - table_name
  - columns: [{name, type, comment}]
  - partitioned_by: [{name, type, comment}]
  - row_format (delimiter)
  - storage_format (TEXTFILE / ORC / PARQUET)

支持多张表(同一文件内),输出 dict 便于其他脚本消费。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ColumnMeta:
    name: str
    type: str
    comment: str = ""


@dataclass
class TableMeta:
    schema: str
    table_name: str
    columns: List[ColumnMeta] = field(default_factory=list)
    partitioned_by: List[ColumnMeta] = field(default_factory=list)
    row_format_delimiter: str = "\t"
    storage_format: str = "TEXTFILE"

    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.table_name}"

    def column_names(self) -> List[str]:
        return [c.name for c in self.columns]

    def column_comments(self) -> Dict[str, str]:
        return {c.name: c.comment for c in self.columns}


# ── 正则 ───────────────────────────────────────────────────────────
RE_CREATE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([\w.]+)\s*\((.*?)\)\s*"
    r"(PARTITIONED\s+BY\s*\((.*?)\))?\s*"
    r"ROW\s+FORMAT\s+DELIMITED\s+FIELDS\s+TERMINATED\s+BY\s+'(.*?)'\s+"
    r"STORED\s+AS\s+(\w+)",
    re.IGNORECASE | re.DOTALL,
)
RE_DATABASE = re.compile(
    r"CREATE\s+DATABASE\s+IF\s+NOT\s+EXISTS\s+([\w]+)\s*;", re.IGNORECASE
)
RE_COLUMN = re.compile(
    r"^\s*`?(\w+)`?\s+([\w()., ]+?)(?:\s+COMMENT\s+'([^']*)')?\s*,?\s*$"
)


def _split_columns(body: str) -> List[ColumnMeta]:
    """拆 columns body,支持 COMMENT 含特殊字符的行"""
    cols: List[ColumnMeta] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        m = RE_COLUMN.match(line)
        if not m:
            continue
        name, ctype, comment = m.group(1), m.group(2).strip(), m.group(3) or ""
        cols.append(ColumnMeta(name=name, type=ctype, comment=comment))
    return cols


def parse_sql(sql_text: str) -> Dict[str, TableMeta]:
    """解析整段 SQL,返回 {full_name: TableMeta}"""
    databases: Dict[str, str] = {}
    for m in RE_DATABASE.finditer(sql_text):
        databases[m.group(1)] = m.group(1)

    tables: Dict[str, TableMeta] = {}
    for m in RE_CREATE.finditer(sql_text):
        full_path = m.group(1)         # "recommand_workspace.o2o_new_gut_shop_base"
        body = m.group(2)
        part_body = m.group(3) or ""
        delimiter = m.group(4) or "\\t"
        storage = m.group(5) or "TEXTFILE"

        if "." in full_path:
            schema, table_name = full_path.split(".", 1)
        else:
            schema, table_name = databases.get("default", "default"), full_path

        meta = TableMeta(
            schema=schema,
            table_name=table_name,
            row_format_delimiter=delimiter.replace("\\t", "\t"),
            storage_format=storage.upper(),
        )
        meta.columns = _split_columns(body)
        if part_body:
            meta.partitioned_by = _split_columns(part_body)
        tables[meta.full_name] = meta

    return tables


def parse_sql_file(path: str | Path) -> Dict[str, TableMeta]:
    p = Path(path)
    return parse_sql(p.read_text(encoding="utf-8"))


# ── 工具函数:抽商品/客户/埋点相关表 ────────────────────────────────
def get_shop_tables(tables: Dict[str, TableMeta]) -> Dict[str, TableMeta]:
    """门店表族(shop_base* / shop_address* / shop_category*)"""
    return {
        k: v for k, v in tables.items()
        if "shop_base" in k or "shop_address" in k or "shop_category" in k
    }


def get_coupon_tables(tables: Dict[str, TableMeta]) -> Dict[str, TableMeta]:
    """券表族(coupon_template* / discounts_pay* / coupon_shop*)"""
    return {
        k: v for k, v in tables.items()
        if "coupon" in k or "discounts_pay" in k
    }


def get_customer_table(tables: Dict[str, TableMeta]) -> Optional[TableMeta]:
    """客户画像表(CDM_ADM_CUST_INFO_STAT_F)"""
    for v in tables.values():
        if "CDM_ADM_CUST_INFO_STAT_F" in v.table_name:
            return v
    return None


def get_event_table(tables: Dict[str, TableMeta]) -> Optional[TableMeta]:
    """埋点表(c10_ods_events_xysh)— 跨所有 schema 找"""
    for v in tables.values():
        if "events_xysh" in v.table_name or "ods_events" in v.table_name:
            return v
    return None


# ── CLI ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    import sys

    sql_path = sys.argv[1] if len(sys.argv) > 1 else "../../tabale_structer.sql"
    tables = parse_sql_file(sql_path)

    print(f"解析到 {len(tables)} 张表:")
    for name, t in tables.items():
        print(f"  {name:<60s} {len(t.columns):3d} 列, 分区 {len(t.partitioned_by)}")

    print("\n门店表族:")
    for name, t in get_shop_tables(tables).items():
        print(f"  {name}: {t.column_names()[:5]}...")

    print("\n客户表:")
    cust = get_customer_table(tables)
    print(f"  {cust.full_name if cust else 'None'}: "
          f"{len(cust.columns) if cust else 0} 列")

    print("\n埋点表:")
    evt = get_event_table(tables)
    print(f"  {evt.full_name if evt else 'None'}: "
          f"{len(evt.columns) if evt else 0} 列")
