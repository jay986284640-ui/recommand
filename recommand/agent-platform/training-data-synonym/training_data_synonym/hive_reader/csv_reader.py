"""CsvReader — reads CSV files via Python native csv module (fast, streaming)."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from itertools import islice
from pathlib import Path

from ..common.logging import get_logger
from ..data_model import HiveReadSpec, RawRecord, TableMeta
from .base import HiveReader, extract_geo, synthesize_item_id

logger = get_logger(__name__)


class CsvReader(HiveReader):
    """Read CSV files via Python stdlib :mod:`csv` — no PySpark overhead.

    Yields rows lazily; peak memory is O(1) regardless of file size.
    """

    def __init__(
        self,
        csv_dir: str | Path,
        delimiter: str = ",",
        header: bool = True,
        spark_session=None,
    ) -> None:
        self._csv_dir = Path(csv_dir)
        self._delimiter = delimiter
        self._header = header
        # spark_session kept for API compatibility; ignored in native mode.
        self._spark = spark_session
        if not self._csv_dir.exists():
            raise FileNotFoundError(f"csv dir not found: {self._csv_dir}")

    # noinspection PyUnusedLocal
    def list_partitions(self, table_meta: TableMeta) -> list[str]:
        return ["20260620"]

    def read(
        self, table_meta: TableMeta, spec: HiveReadSpec
    ) -> Iterator[RawRecord]:
        csv_path = self._csv_dir / f"{table_meta.table_name}.csv"
        if not csv_path.exists():
            logger.warning("csv_missing", extra={
                "stage": "csv_reader",
                "table": table_meta.table_name,
                "path": str(csv_path),
            })
            return

        with csv_path.open("r", encoding="utf-8", newline="") as f:
            # Peek first line to normalise column names
            if self._header:
                raw_header = f.readline().strip("\r\n")
                cols = [
                    c.strip().replace("\x00", "").lower()
                    for c in raw_header.split(self._delimiter)
                ]
                # Filter empty trailing column names (common in malformed CSVs)
                cols = [c for c in cols if c]
            else:
                # Without header, use column indices as names
                first_line = f.readline().strip("\r\n")
                n_cols = len(first_line.split(self._delimiter))
                cols = [f"col_{i}" for i in range(n_cols)]
                f.seek(0)

            reader = csv.DictReader(
                f,
                fieldnames=cols if not self._header else None,
                delimiter=self._delimiter,
            )
            # If we already consumed the header line, DictReader will use
            # fieldnames from the constructor.  If self._header is True we
            # passed fieldnames=None so DictReader reads the header from the
            # file — but we already consumed it above!  Handle both cases.

            if self._header:
                # We already consumed the header; use the pre-parsed cols as
                # fieldnames and DON'T let DictReader read another header.
                reader = csv.DictReader(
                    f, fieldnames=cols, delimiter=self._delimiter,
                    restkey="_extra",  # catch excess columns
                )

            limit = spec.sample_n_per_type
            row_iter: Iterator[dict] = reader
            if limit is not None:
                row_iter = islice(row_iter, int(limit))

            sensitive_lower = {c.lower() for c in spec.sensitive_columns_blocklist}

            for row in row_iter:
                if not row:
                    continue
                # Normalise: strip null bytes / \r, convert to string
                raw: dict[str, str] = {}
                for k, v in row.items():
                    if k is None:
                        continue
                    v_str = str(v or "").replace("\x00", "").rstrip("\r")
                    raw[k] = v_str

                # Drop sensitive columns
                for key in list(raw.keys()):
                    if key.lower() in sensitive_lower:
                        raw.pop(key, None)

                item_id = synthesize_item_id(table_meta, raw)
                if not item_id or len(item_id) < 6:
                    continue

                shop_lng, shop_lat = extract_geo(table_meta, raw)
                etl_dt = raw.pop("etl_dt", "20260620") or "20260620"

                yield RawRecord(
                    item_id=item_id,
                    item_type=table_meta.inferred_role,
                    raw=raw,
                    shop_lng=shop_lng,
                    shop_lat=shop_lat,
                    etl_dt=etl_dt,
                )


__all__ = ["CsvReader"]
