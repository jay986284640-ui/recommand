"""SparkHiveReader — production Hive reader via PySpark Catalog.

Per contracts/hive_read_v1.md §SparkHiveReader. Requires pyspark installed
and a Spark session configured with Kerberos / LDAP access.

Not active in CI (mock source); production teams configure per deployment.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ..common.exceptions import (
    AccessDenied,
    ConnectionError_,
    EmptyPartitionSet,
    SchemaDriftError,
    SensitiveLeakError,
)
from ..common.logging import get_logger
from ..data_model import HiveReadSpec, RawRecord, TableMeta
from .base import HiveReader, extract_geo, synthesize_item_id

logger = get_logger(__name__)


class SparkHiveReader(HiveReader):
    """PySpark Hive Catalog reader. Lazy SparkSession — created on first .read() call."""

    def __init__(self, catalog: str = "spark_catalog", spark_session=None) -> None:
        self._catalog = catalog
        self._spark = spark_session  # allow injection for tests
        self._spark_initialized = spark_session is not None

    def _get_spark(self):
        if self._spark is None:
            try:
                from pyspark.sql import SparkSession  # type: ignore
            except ImportError as e:
                raise ConnectionError_(
                    "pyspark not installed; install with `pip install pyspark`"
                ) from e
            try:
                self._spark = (
                    SparkSession.builder.appName("training-data-synonym")
                    .enableHiveSupport()
                    .getOrCreate()
                )
            except Exception as e:  # noqa: BLE001
                raise ConnectionError_(f"SparkSession init failed: {e}") from e
            self._spark_initialized = True
        return self._spark

    def list_partitions(self, table_meta: TableMeta) -> list[str]:
        spark = self._get_spark()
        full = f"{self._catalog}.{table_meta.db}.{table_meta.table_name}"
        try:
            df = spark.sql(f"SHOW PARTITIONS {full}")
        except Exception as e:
            if "AccessControlException" in str(e) or "permission" in str(e).lower():
                raise AccessDenied(f"SHOW PARTITIONS denied for {full}") from e
            raise ConnectionError_(f"SHOW PARTITIONS failed for {full}: {e}") from e
        rows = df.collect()
        return sorted([r[0].split("=")[1] for r in rows], reverse=True)

    def read(
        self, table_meta: TableMeta, spec: HiveReadSpec
    ) -> Iterator[RawRecord]:
        spark = self._get_spark()
        full = f"{self._catalog}.{table_meta.db}.{table_meta.table_name}"
        partitions = self._select_partitions(table_meta, spec)
        if not partitions:
            raise EmptyPartitionSet(f"No partitions for {full}")

        # Project all declared columns minus sensitive blocklist
        columns = [c.name for c in table_meta.columns
                   if c.name not in spec.sensitive_columns_blocklist]
        projection = ", ".join(f"`{c}`" for c in columns)

        partition_filter = " OR ".join(f"etl_dt='{p}'" for p in partitions)
        sql = f"SELECT {projection} FROM {full} WHERE {partition_filter}"
        try:
            df = spark.sql(sql)
        except Exception as e:
            msg = str(e)
            if "cannot resolve" in msg.lower():
                raise SchemaDriftError(f"Hive schema drift for {full}: {msg}") from e
            raise

        for row in df.toLocalIterator():
            raw = row.asDict(recursive=True)
            # Validate sensitive columns NOT in result
            for col in spec.sensitive_columns_blocklist:
                if col in raw:
                    raise SensitiveLeakError(
                        f"sensitive '{col}' survived SparkHiveReader.read() for {full}"
                    )
            item_id = synthesize_item_id(table_meta, raw)
            shop_lng, shop_lat = extract_geo(table_meta, raw)
            etl_dt = raw.pop("etl_dt", partitions[0]) or partitions[0]
            yield RawRecord(
                item_id=item_id,
                item_type=table_meta.inferred_role,
                raw=raw,
                shop_lng=shop_lng,
                shop_lat=shop_lat,
                etl_dt=etl_dt,
            )

    def _select_partitions(
        self, table_meta: TableMeta, spec: HiveReadSpec
    ) -> list[str]:
        all_p = self.list_partitions(table_meta)
        if spec.etl_dt_mode == "single":
            if spec.etl_dt_single not in all_p:
                raise EmptyPartitionSet(
                    f"single etl_dt={spec.etl_dt_single} not in {all_p}"
                )
            return [spec.etl_dt_single]
        if spec.etl_dt_mode == "range":
            lo, hi = spec.etl_dt_range
            return [p for p in all_p if lo <= p <= hi]
        # latest_n
        return all_p[: max(1, spec.etl_dt_latest_n)]


__all__ = ["SparkHiveReader"]