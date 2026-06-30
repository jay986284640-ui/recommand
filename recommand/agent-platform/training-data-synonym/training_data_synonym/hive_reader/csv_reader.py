"""CsvReader — reads CSV files instead of Hive.

Matches ``{table_name}.csv`` under ``csv_dir``. Behaves identically to
``MockHiveReader`` (same RawRecord yield contract), but sources from CSV
instead of JSONL. Useful for data exported from Hive via Spark or beeline.

Usage:
    reader = CsvReader(csv_dir="/data/exports")
    for rec in reader.read(table_meta, spec):
        ...
"""
from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from ..common.exceptions import SensitiveLeakError
from ..common.logging import get_logger
from ..data_model import HiveReadSpec, RawRecord, TableMeta
from .base import HiveReader, extract_geo, synthesize_item_id

logger = get_logger(__name__)


class CsvReader(HiveReader):
    """Read CSV files exported from Hive / Spark.

    Expects files named ``{table_name}.csv``. First row is header (column
    names). Rows are yielded as ``RawRecord`` with the same contract as
    ``MockHiveReader`` / ``SparkHiveReader``.
    """

    def __init__(self, csv_dir: str | Path, delimiter: str = ",") -> None:
        self._csv_dir = Path(csv_dir)
        self._delimiter = delimiter
        if not self._csv_dir.exists():
            raise FileNotFoundError(f"csv dir not found: {self._csv_dir}")

    def list_partitions(self, table_meta: TableMeta) -> list[str]:
        return ["20260620"]  # synthetic — CSV has no partitions

    def read(
        self, table_meta: TableMeta, spec: HiveReadSpec
    ) -> Iterator[RawRecord]:
        csv_path = self._csv_dir / f"{table_meta.table_name}.csv"
        if not csv_path.exists():
            logger.warning(
                "csv_missing",
                extra={
                    "stage": "csv_reader",
                    "event": "fixture_missing",
                    "table": table_meta.table_name,
                    "path": str(csv_path),
                },
            )
            return

        sensitive_lower = {c.lower() for c in spec.sensitive_columns_blocklist}

        with csv_path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=self._delimiter)
            if reader.fieldnames is None:
                return

            rows = list(reader)

        # sample (deterministic slice like MockHiveReader)
        if spec.sample_n_per_type is not None:
            rows = rows[: spec.sample_n_per_type]

        for raw in rows:
            # Normalize keys (CSV headers may vary in case)
            raw = {k.strip().lower(): v for k, v in raw.items()}

            # sensitive column drop
            for key in list(raw.keys()):
                if key.lower() in sensitive_lower:
                    raw.pop(key, None)

            # item_id synthesis
            item_id = synthesize_item_id(table_meta, raw)
            if not item_id or item_id.startswith(("mt-", "self-", "cpn-")) and len(item_id) < 6:
                continue

            # shop_lng / shop_lat
            shop_lng, shop_lat = extract_geo(table_meta, raw)
            etl_dt = raw.pop("etl_dt", "20260620") or "20260620"

            for key in raw:
                if key.lower() in sensitive_lower:
                    raise SensitiveLeakError(
                        f"sensitive column '{key}' survived CsvReader.read()"
                    )

            yield RawRecord(
                item_id=item_id,
                item_type=table_meta.inferred_role,
                raw=raw,
                shop_lng=shop_lng,
                shop_lat=shop_lat,
                etl_dt=etl_dt,
            )


__all__ = ["CsvReader"]
