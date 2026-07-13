"""YAML table-config loader (v1.4 — simplified).

Per spec v2.5: ``configs/tables.yaml`` declares db / name / role / item_id /
columns (name + type) / sensitive flags.  :func:`load_tables_config` validates
the YAML and returns a list of :class:`~training_data.data_model.TableMeta`.
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

        item_id = str(t.get("item_id") or "").strip().lower()

        cols_raw = t.get("columns") or []
        if not isinstance(cols_raw, list) or not cols_raw:
            raise TablesConfigError(
                f"table {db}.{name} has empty 'columns' list"
            )

        columns: list[ColumnMeta] = []
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
            if not col_type:
                raise TablesConfigError(
                    f"table {db}.{name} column #{j} ({col_name}) has empty type"
                )
            if col_type not in _VALID_TYPES:
                # Don't fail on unknown types — Hive has many.
                pass
            columns.append(
                ColumnMeta(
                    name=col_name,
                    type=col_type,
                    comment=c.get("comment"),
                )
            )

        partition_keys = [
            str(k).strip().lower()
            for k in (t.get("partition_keys") or [])
            if str(k).strip()
        ]

        out.append(
            TableMeta(
                db=db,
                table_name=name,
                columns=columns,
                partition_keys=partition_keys,
                inferred_role=Role(role_str),
                item_id=item_id,
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

    Returns a sorted, deduplicated list.
    """
    sens: set[str] = set()
    if raw_yaml is None:
        return []
    for t in raw_yaml.get("tables", []) or []:
        # Source 1: top-level `sensitive: [list]`
        for c in t.get("sensitive", []) or []:
            sens.add(str(c))
        # Source 2: per-column `sensitive: true` (legacy)
        for c in t.get("columns", []) or []:
            if bool(c.get("sensitive", False)):
                sens.add(str(c.get("name") or ""))
    return sorted(sens)


__all__ = ["TablesConfigError", "load_tables_config", "derive_sensitive_blocklist"]
