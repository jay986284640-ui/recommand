"""Unit tests for ``training_data_synonym.common.tables_config`` (Part A).

Covers the validation rules:
- missing file → TablesConfigError
- malformed YAML → TablesConfigError
- empty `tables:` → TablesConfigError
- duplicate (db, name) → TablesConfigError
- invalid role → TablesConfigError
- empty columns list → TablesConfigError
- column with empty name / type → TablesConfigError
- valid yaml → list[TableMeta] with correct Role + ColumnMeta fields
"""

from __future__ import annotations

import textwrap

import pytest

from training_data_synonym.common.tables_config import (
    TablesConfigError,
    derive_sensitive_blocklist,
    load_tables_config,
)
from training_data_synonym.data_model import Role


def test_valid_yaml_loads(tmp_path, repo_root):
    valid = tmp_path / "tables.yaml"
    valid.write_text(
        textwrap.dedent(
            """\
            tables:
              - db: db_a
                name: tbl_x
                role: meituan_shop
                columns:
                  - { name: id, type: BIGINT }
                  - { name: nm, type: VARCHAR, sensitive: true }
            """
        ),
        encoding="utf-8",
    )
    tables = load_tables_config(valid)
    assert len(tables) == 1
    t = tables[0]
    assert t.db == "db_a"
    assert t.table_name == "tbl_x"
    assert t.inferred_role == Role.MEITUAN_SHOP
    assert len(t.columns) == 2
    assert t.columns[0].name == "id"
    assert t.columns[0].type == "BIGINT"
    assert t.columns[1].name == "nm"
    assert t.columns[1].type == "VARCHAR"


def test_loads_real_tables_yaml(repo_root):
    """Smoke test: the production configs/tables.yaml parses and yields 8 tables."""
    tables = load_tables_config(repo_root / "configs" / "tables.yaml")
    assert len(tables) == 8
    roles = {t.inferred_role for t in tables}
    assert Role.MEITUAN_SHOP in roles
    assert Role.SELF_SHOP in roles
    assert Role.COUPON in roles
    # v2.5: business-abstraction — meituan_shop declares ~9 cols (was 36+).
    meituan = next(t for t in tables if t.table_name == "o2o_new_gut_shop_base_third")
    assert 5 <= len(meituan.columns) <= 12, (
        f"meituan_shop columns should be business-essential, got {len(meituan.columns)}"
    )


def test_real_tables_yaml_sensitive_top_level(repo_root):
    """v2.5: production tables.yaml uses top-level sensitive: lists."""
    import yaml
    raw = yaml.safe_load((repo_root / "configs" / "tables.yaml").read_text())
    bl = derive_sensitive_blocklist([], raw_yaml=raw)
    # Sensitive blocklist now preserves original case (PascalCase from DDL).
    # MockHiveReader does case-insensitive matching so both work.
    assert "Crt_Psn_Id" in bl       # meituan_shop
    assert "Updt_Psn_Id" in bl      # meituan_shop
    assert "Opr_Psn_Id" in bl        # self_shop
    assert "creator" in bl           # coupon (lowercase in DDL)
    assert "updatePerson" in bl     # coupon (camelCase in DDL)


# ──────────────────────── field_contract ────────────────────────


def test_field_contract_missing_required_raises(tmp_path):
    """v2.5: missing required role for the table's role → TablesConfigError."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        textwrap.dedent(
            """\
            _meta:
              field_contract:
                meituan_shop:
                  required: [id, name, brand, category, price, lng, lat]
            tables:
              - db: db_a
                name: tbl_x
                role: meituan_shop
                columns:
                  - { name: id, type: BIGINT, role: id }
                  - { name: name, type: VARCHAR, role: name }
                # missing brand / category / price / lng / lat
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(TablesConfigError, match="missing required columns"):
        load_tables_config(bad)


def test_field_contract_self_shop_requires_brand(tmp_path):
    """v2.5: self_shop requires id/name/brand (raw DDL columns only)."""
    bad = tmp_path / "no_brand.yaml"
    bad.write_text(
        textwrap.dedent(
            """\
            _meta:
              field_contract:
                self_shop:
                  required: [id, name, brand]
            tables:
              - db: db_a
                name: tbl_x
                role: self_shop
                columns:
                  - { name: shopid, type: VARCHAR, role: id }
                  - { name: shopname, type: VARCHAR, role: name }
                # missing brand
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(TablesConfigError, match="missing required columns"):
        load_tables_config(bad)


def test_field_contract_no_contract_in_yaml_works(tmp_path):
    """v2.5: when no field_contract is declared, all checks are skipped
    (backward compat with ad-hoc yaml)."""
    no_contract = tmp_path / "no_contract.yaml"
    no_contract.write_text(
        textwrap.dedent(
            """\
            tables:
              - db: db_a
                name: tbl_x
                role: meituan_shop
                columns:
                  - { name: id, type: BIGINT, role: id }
            """
        ),
        encoding="utf-8",
    )
    tables = load_tables_config(no_contract)
    assert len(tables) == 1


def test_missing_file_raises(tmp_path):
    with pytest.raises(TablesConfigError, match="not found"):
        load_tables_config(tmp_path / "does_not_exist.yaml")


def test_malformed_yaml_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("tables: [unclosed", encoding="utf-8")
    with pytest.raises(TablesConfigError, match="invalid YAML"):
        load_tables_config(bad)


def test_empty_tables_raises(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("tables: []", encoding="utf-8")
    with pytest.raises(TablesConfigError, match="non-empty 'tables'"):
        load_tables_config(empty)


def test_duplicate_table_raises(tmp_path):
    dup = tmp_path / "dup.yaml"
    dup.write_text(
        textwrap.dedent(
            """\
            tables:
              - { db: a, name: t, role: meituan_shop, columns: [{ name: id, type: BIGINT }] }
              - { db: a, name: t, role: coupon, columns: [{ name: id, type: BIGINT }] }
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(TablesConfigError, match="duplicate"):
        load_tables_config(dup)


def test_invalid_role_raises(tmp_path):
    bad_role = tmp_path / "role.yaml"
    bad_role.write_text(
        textwrap.dedent(
            """\
            tables:
              - { db: a, name: t, role: not_a_real_role, columns: [{ name: id, type: BIGINT }] }
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(TablesConfigError, match="invalid role"):
        load_tables_config(bad_role)


def test_empty_columns_raises(tmp_path):
    no_cols = tmp_path / "nocols.yaml"
    no_cols.write_text(
        textwrap.dedent(
            """\
            tables:
              - { db: a, name: t, role: meituan_shop, columns: [] }
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(TablesConfigError, match="empty 'columns'"):
        load_tables_config(no_cols)


def test_column_with_empty_name_raises(tmp_path):
    no_name = tmp_path / "noname.yaml"
    no_name.write_text(
        textwrap.dedent(
            """\
            tables:
              - db: a
                name: t
                role: meituan_shop
                columns:
                  - { name: "", type: BIGINT }
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(TablesConfigError, match="empty name"):
        load_tables_config(no_name)


def test_column_with_empty_type_raises(tmp_path):
    no_type = tmp_path / "notype.yaml"
    no_type.write_text(
        textwrap.dedent(
            """\
            tables:
              - db: a
                name: t
                role: meituan_shop
                columns:
                  - { name: id, type: "" }
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(TablesConfigError, match="empty type"):
        load_tables_config(no_type)


def test_derive_sensitive_blocklist_basic():
    raw = {
        "tables": [
            {
                "db": "db",
                "name": "t",
                "columns": [
                    {"name": "id", "type": "BIGINT"},
                    {"name": "secret_col", "type": "VARCHAR", "sensitive": True},
                    {"name": "public_col", "type": "VARCHAR"},
                ],
            }
        ]
    }
    bl = derive_sensitive_blocklist([], raw_yaml=raw)
    assert bl == ["secret_col"]


def test_derive_sensitive_blocklist_top_level_list():
    """v2.5: top-level `sensitive: [col_a, col_b]` per table — preferred form."""
    raw = {
        "tables": [
            {
                "db": "db",
                "name": "t",
                "columns": [
                    {"name": "id", "type": "BIGINT"},
                    {"name": "secret_col", "type": "VARCHAR"},
                    {"name": "another_secret", "type": "VARCHAR"},
                ],
                "sensitive": ["secret_col", "another_secret"],
            }
        ]
    }
    bl = derive_sensitive_blocklist([], raw_yaml=raw)
    assert bl == ["another_secret", "secret_col"]


def test_derive_sensitive_blocklist_top_level_and_per_column_merge():
    """Both forms can coexist; union is taken."""
    raw = {
        "tables": [
            {
                "db": "db",
                "name": "t",
                "columns": [
                    {"name": "a", "type": "VARCHAR", "sensitive": True},
                    {"name": "b", "type": "VARCHAR"},
                ],
                "sensitive": ["b", "c"],
            }
        ]
    }
    bl = derive_sensitive_blocklist([], raw_yaml=raw)
    assert bl == ["a", "b", "c"]


def test_derive_sensitive_blocklist_no_sensitive():
    raw = {
        "tables": [
            {
                "db": "db",
                "name": "t",
                "columns": [{"name": "id", "type": "BIGINT"}],
            }
        ]
    }
    bl = derive_sensitive_blocklist([], raw_yaml=raw)
    assert bl == []
