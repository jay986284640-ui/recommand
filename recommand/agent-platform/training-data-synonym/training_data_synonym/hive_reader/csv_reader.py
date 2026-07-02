"""CsvReader — reads CSV files via PySpark."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ..common.logging import get_logger
from ..data_model import HiveReadSpec, RawRecord, TableMeta
from .base import HiveReader, extract_geo, synthesize_item_id

logger = get_logger(__name__)


class CsvReader(HiveReader):
    """Read CSV files via PySpark ``spark.read.csv()``."""

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
        self._spark = spark_session
        if not self._csv_dir.exists():
            raise FileNotFoundError(f"csv dir not found: {self._csv_dir}")

    def _get_spark(self):
        if self._spark is None:
            from pyspark.sql import SparkSession
            self._spark = SparkSession.builder.appName("csv-reader").getOrCreate()
        return self._spark

    def list_partitions(self, table_meta: TableMeta) -> list[str]:
        return ["20260620"]

    def read(
        self, table_meta: TableMeta, spec: HiveReadSpec
    ) -> Iterator[RawRecord]:
        csv_path = self._csv_dir / f"{table_meta.table_name}.csv"
        if not csv_path.exists():
            logger.warning("csv_missing", extra={
                "stage": "csv_reader", "table": table_meta.table_name, "path": str(csv_path),
            })
            return

        spark = self._get_spark()
        df = (
            spark.read
            .option("header", str(self._header).lower())
            .option("delimiter", self._delimiter)
            .option("inferSchema", "true")
            .csv(str(csv_path))
        )
        for col_name in df.columns:
            clean = col_name.replace("\x00", "").lower()
            df = df.withColumnRenamed(col_name, clean)

        limit = spec.sample_n_per_type
        rows = df.collect() if limit is None else df.limit(limit).collect()

        sensitive_lower = {c.lower() for c in spec.sensitive_columns_blocklist}
        for row in rows:
            raw = row.asDict(recursive=True)
            raw = {k: str(v or "").replace("\x00", "").rstrip("\r") for k, v in raw.items()}

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
