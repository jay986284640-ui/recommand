"""YAML table-config loader (replaces SQL DDL parsing).

Per spec v2.5: ``configs/tables.yaml`` declares db / name / role / columns / data type
/ sensitive flags + a **field contract** (``_meta.field_contract``) that says which
``role:`` annotations each role must provide. :func:`load_tables_config` validates
the YAML and returns a list of :class:`~training_data_synonym.data_model.TableMeta`
— the same dataclass that :mod:`training_data_synonym.sql_parser` previously
produced. Downstream code (MockHiveReader, EnrichmentPipeline) is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..data_model import TABLE_META_V, ColumnMeta, Role, TableMeta


class TablesConfigError(ValueError):
    """Raised when ``configs/tables.yaml`` is missing or invalid."""


_VALID_TYPES = {
    # Hive primitive types we actually encounter in 兴业 O2O schema
    "TINYINT", "SMALLINT", "INT", "BIGINT",
    "FLOAT", "DOUBLE", "DECIMAL",
    "STRING", "VARCHAR", "CHAR", "BOOLEAN",
    "DATE", "TIMESTAMP",
}


def load_tables_config(path: str | Path) -> list[TableMeta]:
    """Load and validate the table-config YAML; return ``list[TableMeta]``.

    Validation:
      - file exists & parses as YAML
      - top-level ``tables:`` is a non-empty list
      - each table has unique ``(db, name)``
      - ``role`` ∈ :class:`Role` enum
      - ``columns`` is a non-empty list of ``{name, type}`` with both fields set
      - ``_meta.field_contract`` (if present): every table's columns must cover
        the contract's ``required`` roles for that table's role.

    Raises:
        TablesConfigError: on any validation failure.
    """
    p = Path(path)
    if not p.exists():
        raise TablesConfigError(f"tables config not found: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise TablesConfigError(f"invalid YAML in {p}: {e}") from e

    raw_tables = data.get("tables") or []
    if not isinstance(raw_tables, list) or not raw_tables:
        raise TablesConfigError(
            f"tables config must contain non-empty 'tables' list: {p}"
        )

    contract = (
        (data.get("_meta") or {}).get("field_contract") or {}
    )

    valid_roles = {r.value for r in Role}
    seen: set[tuple[str, str]] = set()
    out: list[TableMeta] = []

    for i, t in enumerate(raw_tables):
        if not isinstance(t, dict):
            raise TablesConfigError(
                f"table entry #{i} must be a mapping, got {type(t).__name__}"
            )
        db = str(t.get("db") or "").strip().lower()
        name = str(t.get("name") or "").strip().lower()
        if not db or not name:
            raise TablesConfigError(
                f"table entry #{i} missing db or name: db={db!r} name={name!r}"
            )
        if (db, name) in seen:
            raise TablesConfigError(
                f"duplicate table at index {i}: {db}.{name}"
            )
        seen.add((db, name))

        role_str = str(t.get("role") or "unknown").strip().lower()
        if role_str not in valid_roles:
            raise TablesConfigError(
                f"invalid role {role_str!r} for {db}.{name}; "
                f"must be one of {sorted(valid_roles)}"
            )

        cols_raw = t.get("columns") or []
        if not isinstance(cols_raw, list) or not cols_raw:
            raise TablesConfigError(
                f"table {db}.{name} has empty 'columns' list"
            )

        columns: list[ColumnMeta] = []
        column_roles: list[str] = []  # parallel list of `role:` annotations
        for j, c in enumerate(cols_raw):
            if not isinstance(c, dict):
                raise TablesConfigError(
                    f"table {db}.{name} column #{j} must be a mapping"
                )
            col_name = str(c.get("name") or "").strip()
            col_type = str(c.get("type") or "").strip().upper()
            if not col_name:
                raise TablesConfigError(
                    f"table {db}.{name} column #{j} has empty name"
                )
            # Keep original case — Hive columns are PascalCase (Str_Id, Brnd_Nm).
            # MockHiveReader does case-insensitive key matching so both work.
            if not col_type:
                raise TablesConfigError(
                    f"table {db}.{name} column #{j} ({col_name}) has empty type"
                )
            if col_type not in _VALID_TYPES:
                # Don't fail on unknown types — Hive has many. Warn via doc only.
                pass
            columns.append(
                ColumnMeta(
                    name=col_name,
                    type=col_type,
                    comment=c.get("comment"),
                )
            )
            col_role = c.get("role")
            if col_role is not None:
                column_roles.append(str(col_role).strip())

        partition_keys = [
            str(k).strip().lower()
            for k in (t.get("partition_keys") or [])
            if str(k).strip()
        ]

        # Field contract check (v2.5): every table's column_roles must include
        # the contract's required roles for that table's role.
        if contract:
            required = (
                (contract.get(role_str) or {}).get("required") or []
            )
            missing = [
                r for r in required if r not in column_roles
            ]
            if missing:
                raise TablesConfigError(
                    f"table {db}.{name} (role={role_str}) is missing "
                    f"required columns for field_contract: {missing}. "
                    f"Got column roles: {column_roles}; "
                    f"add the missing columns (with `role: <r>` annotation) "
                    f"or update the fixture / upstream SQL view to provide them."
                )

        out.append(
            TableMeta(
                db=db,
                table_name=name,
                columns=columns,
                partition_keys=partition_keys,
                inferred_role=Role(role_str),
                _format_version=TABLE_META_V,
            )
        )

    return out


def derive_sensitive_blocklist(
    tables: list[TableMeta], raw_yaml: dict[str, Any] | None = None
) -> list[str]:
    """Pull sensitive column names from the YAML.

    Two accepted sources (top-level wins, per-column kept for back-compat):
      1. Per-table top-level ``sensitive: [col_a, col_b]`` — preferred.
      2. Per-column ``sensitive: true`` flag — legacy, still honoured.

    Returns a sorted, deduplicated list — the contract that
    :class:`~training_data_synonym.data_model.HiveReadSpec.sensitive_columns_blocklist`
    expects. We re-read the YAML rather than threading ``sensitive`` through
    :class:`ColumnMeta` to keep the dataclass shape stable for any consumers
    that already serialize it (item_tags.jsonl, sft_corpus.jsonl).
    """
    sens: set[str] = set()
    if raw_yaml is None:
        return []
    for t in raw_yaml.get("tables", []) or []:
        # Source 1: top-level `sensitive: [list]` — keep original case
        for c in t.get("sensitive", []) or []:
            sens.add(str(c))
        # Source 2: per-column `sensitive: true` (legacy)
        for c in t.get("columns", []) or []:
            if bool(c.get("sensitive", False)):
                sens.add(str(c.get("name") or ""))
    return sorted(sens)


__all__ = ["TablesConfigError", "load_tables_config", "derive_sensitive_blocklist"]
