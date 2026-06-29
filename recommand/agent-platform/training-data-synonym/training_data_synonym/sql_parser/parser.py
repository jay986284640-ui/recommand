"""SQL DDL parser — extracts TableMeta list from `tabale_structer.sql`.

.. deprecated::
    This module is deprecated as of v2.5. Use
    :func:`training_data_synonym.common.tables_config.load_tables_config`
    with ``configs/tables.yaml`` instead. SQL DDL parsing is brittle and
    cannot capture intent (sensitive columns, role hints) that the new YAML
    schema expresses explicitly. New code MUST NOT import ``parse_sql``.

Per data-model.md §实体 1 + plan.md T014.
Handles Hive DDL:
  CREATE TABLE [IF NOT EXISTS] db.table (
      col_name TYPE [COMMENT '...'],
      ...
  ) PARTITIONED BY (...) ROW FORMAT ... STORED AS ...;

Robust parsing: walks the SQL char-by-char, balancing parentheses so that
nested types like VARCHAR(64) and DECIMAL(10, 2) are not mis-detected as the
column-list terminator.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

from ..data_model import ColumnMeta, Role, TableMeta

warnings.warn(
    "training_data_synonym.sql_parser is deprecated; "
    "use training_data_synonym.common.tables_config.load_tables_config "
    "with configs/tables.yaml.",
    DeprecationWarning,
    stacklevel=2,
)


# Header: locate the start of "CREATE TABLE [IF NOT EXISTS] db.table ("
_TABLE_HEADER_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<db>[a-zA-Z_][\w]*)\.(?P<table>[a-zA-Z_][\w]*)\s*\(",
    re.IGNORECASE,
)

# Inline COMMENT 'foo'
_COMMENT_RE = re.compile(r"COMMENT\s+'(?P<c>[^']*)'", re.IGNORECASE)

# Column: name TYPE [COMMENT '...'] (case-insensitive name match)
_COL_RE = re.compile(
    r"^\s*(?P<name>[a-zA-Z_][\w]*)\s+(?P<type>[A-Z]+(?:\s*\([^)]+\))?)(?P<rest>.*)$",
    re.IGNORECASE,
)

# PARTITIONED BY (col1 TYPE, col2 TYPE, ...)
_PARTITIONED_RE = re.compile(
    r"PARTITIONED\s+BY\s*\((?P<body>[^)]+)\)", re.IGNORECASE
)

# Database creation
_CREATE_DB_RE = re.compile(
    r"CREATE\s+DATABASE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<db>[a-zA-Z_][\w]*)",
    re.IGNORECASE,
)


def role_from_tablename(table_name: str) -> Role:
    """Heuristic mapping from table name → inferred role (per data-model.md)."""
    tn = table_name.lower()
    if "shop_base_third" in tn:
        return Role.MEITUAN_SHOP
    if tn == "shop_base" or tn.endswith("_shop_base"):
        return Role.SELF_SHOP
    if "coupon_template" in tn:
        return Role.COUPON
    if "shop_address" in tn:
        return Role.ADDRESS
    if "shop_category" in tn:
        return Role.CATEGORY
    if "coupon_shop" in tn:
        return Role.COUPON_SHOP
    if "discounts_pay" in tn:
        return Role.DISCOUNT
    if "cust_info_stat" in tn or "cust_info" in tn:
        return Role.CUSTOMER
    if "events" in tn:
        return Role.EVENTS
    return Role.UNKNOWN


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return sql


def _find_balanced_body(sql: str, start_idx: int) -> tuple[str, int]:
    """Given the index of the opening '(', return (body_inner, end_idx_after_close).

    Body_inner is the text between the matched parens. Balances nested
    parens so VARCHAR(64) and similar don't break the parse.
    """
    assert sql[start_idx] == "(", f"expected '(' at {start_idx}, got {sql[start_idx]!r}"
    depth = 0
    in_quote = False
    quote_char = ""
    body_start = start_idx + 1
    i = start_idx
    while i < len(sql):
        ch = sql[i]
        if in_quote:
            if ch == quote_char and (i == 0 or sql[i - 1] != "\\"):
                in_quote = False
        elif ch in ("'", '"'):
            in_quote = True
            quote_char = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return sql[body_start:i], i + 1
        i += 1
    raise ValueError("unbalanced parentheses in CREATE TABLE body")


def _split_columns(body: str) -> list[str]:
    """Split the column-list body on top-level commas, respecting quotes."""
    parts: list[str] = []
    current: list[str] = []
    in_quote = False
    quote_char = ""
    depth = 0
    for ch in body:
        if in_quote:
            current.append(ch)
            if ch == quote_char:
                in_quote = False
        elif ch in ("'", '"'):
            in_quote = True
            quote_char = ch
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current and "".join(current).strip():
        parts.append("".join(current).strip())
    return parts


def _parse_columns(body: str) -> list[ColumnMeta]:
    cols: list[ColumnMeta] = []
    for line in _split_columns(body):
        line = line.strip()
        if not line:
            continue
        if line.upper().startswith(("PRIMARY KEY", "FOREIGN KEY", "CONSTRAINT", "UNIQUE", "INDEX")):
            continue
        m = _COL_RE.match(line)
        if not m:
            continue
        name = m.group("name").strip()
        if name.upper() in ("PRIMARY", "FOREIGN", "CONSTRAINT", "UNIQUE"):
            continue
        ctype = m.group("type").strip().upper()
        comment = None
        c_match = _COMMENT_RE.search(m.group("rest") or "")
        if c_match:
            comment = c_match.group("c").strip()
        cols.append(ColumnMeta(name=name.lower(), type=ctype, comment=comment))
    return cols


def _parse_partitions(stmt_text: str) -> list[str]:
    m = _PARTITIONED_RE.search(stmt_text)
    if not m:
        return []
    body = m.group("body")
    return [
        c.strip().split()[0].strip("`").lower()
        for c in body.split(",")
        if c.strip()
    ]


def parse_sql(sql_path: str | Path) -> list[TableMeta]:
    """Parse all CREATE TABLE statements in the given SQL file."""
    sql_path = Path(sql_path)
    sql = _strip_comments(sql_path.read_text(encoding="utf-8"))

    tables: list[TableMeta] = []
    seen: set[tuple[str, str]] = set()
    for m in _TABLE_HEADER_RE.finditer(sql):
        db = m.group("db").lower()
        table = m.group("table").lower()
        if (db, table) in seen:
            continue
        # Locate the opening paren and walk forward, balanced.
        paren_idx = m.end() - 1  # m.end() is one past '('
        try:
            body, end_idx = _find_balanced_body(sql, paren_idx)
        except ValueError:
            continue
        seen.add((db, table))
        cols = _parse_columns(body)
        # Tail of the statement (up to next ';') for PARTITIONED BY extraction
        tail_end = sql.find(";", end_idx)
        if tail_end == -1:
            tail_end = len(sql)
        tail = sql[end_idx:tail_end]
        partitions = _parse_partitions(tail)
        tables.append(
            TableMeta(
                db=db,
                table_name=table,
                columns=cols,
                partition_keys=partitions,
                inferred_role=role_from_tablename(table),
            )
        )
    return tables


def list_databases(sql_path: str | Path) -> list[str]:
    sql = _strip_comments(Path(sql_path).read_text(encoding="utf-8"))
    return [m.group("db").lower() for m in _CREATE_DB_RE.finditer(sql)]