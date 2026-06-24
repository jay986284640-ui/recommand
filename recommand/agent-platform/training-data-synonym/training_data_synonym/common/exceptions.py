"""Common exception hierarchy.

Per Constitution V (Observability) + spec §FR-007/022 — failures are
logged structurally, never silently swallowed.
"""

from __future__ import annotations


class PipelineError(Exception):
    """Base error for the training-data-synonym pipeline."""


class StageError(PipelineError):
    """A specific stage failed (enrich / sft / split)."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"[{stage}] {message}")
        self.stage = stage
        self.message = message


class ValidationError(PipelineError):
    """A sample failed validation (JSON shape, dict membership, length)."""


class ContractError(PipelineError):
    """A product artifact has the wrong _format_version or missing fields."""


# --- Hive reader exceptions (per contracts/hive_read_v1.md §异常类型) ---


class HiveReaderError(PipelineError):
    """Base error for HiveReader implementations."""


class ConnectionError_(HiveReaderError):
    """Hive cluster unreachable (renamed to avoid stdlib clash)."""

    pass


class AccessDenied(HiveReaderError):
    """Kerberos / LDAP / table permission denied."""

    pass


class EmptyPartitionSet(HiveReaderError):
    """Selected etl_dt mode resolved to zero partitions."""

    pass


class SchemaDriftError(HiveReaderError):
    """Hive actual columns != TableMeta columns. Auto-continues by ignoring extras."""

    pass


class DuplicateItemIdError(HiveReaderError):
    """Same item_id appeared twice in one table — DDL drift indicator."""

    pass


class SensitiveLeakError(HiveReaderError):
    """Sensitive column survived HiveReader.read() — must not happen."""

    pass