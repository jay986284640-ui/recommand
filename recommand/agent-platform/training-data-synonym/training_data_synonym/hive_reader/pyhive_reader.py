"""PyHiveReader — fallback backend (no Spark required).

Per contracts/hive_read_v1.md §PyHiveReader. For non-Spark environments
that still have HiveServer2 access.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..common.exceptions import ConnectionError_, EmptyPartitionSet, SensitiveLeakError
from ..common.logging import get_logger
from ..data_model import HiveReadSpec, RawRecord, TableMeta
from .base import HiveReader, extract_geo, synthesize_item_id

logger = get_logger(__name__)


class PyHiveReader(HiveReader):
    """PyHive HiveServer2 backend. Single-threaded; not recommended for large tables."""

    def __init__(self, host: str, port: int = 10000, auth: str = "KERBEROS",
                 database: str | None = None) -> None:
        self._host = host
        self._port = port
        self._auth = auth
        self._database = database
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            try:
                from pyhive import hive  # type: ignore
            except ImportError as e:
                raise ConnectionError_(
                    "pyhive not installed; install with `pip install pyhive[hive]`"
                ) from e
            try:
                self._conn = hive.Connection(
                    host=self._host, port=self._port, auth=self._auth,
                    database=self._database,
                )
            except Exception as e:  # noqa: BLE001
                raise ConnectionError_(
                    f"PyHive connection failed ({self._host}:{self._port}): {e}"
                ) from e
        return self._conn

    def list_partitions(self, table_meta: TableMeta) -> list[str]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(f"SHOW PARTITIONS {table_meta.db}.{table_meta.table_name}")
            rows = cur.fetchall()
        return sorted([r[0].split("=")[1] for r in rows], reverse=True)

    def read(
        self, table_meta: TableMeta, spec: HiveReadSpec
    ) -> Iterator[RawRecord]:
        full = f"{table_meta.db}.{table_meta.table_name}"
        partitions = self._select_partitions(table_meta, spec)
        if not partitions:
            raise EmptyPartitionSet(f"No partitions for {full}")

        columns = [c.name for c in table_meta.columns
                   if c.name not in spec.sensitive_columns_blocklist]
        projection = ", ".join(f"`{c}`" for c in columns)
        partition_filter = " OR ".join(f"etl_dt='{p}'" for p in partitions)
        sql = f"SELECT {projection} FROM {full} WHERE {partition_filter}"

        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            col_names = [d[0].lower() for d in cur.description]
        for row in rows:
            raw = dict(zip(col_names, row))
            for col in spec.sensitive_columns_blocklist:
                if col in raw:
                    raise SensitiveLeakError(
                        f"sensitive '{col}' survived PyHiveReader.read() for {full}"
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
            return [spec.etl_dt_single] if spec.etl_dt_single in all_p else []
        if spec.etl_dt_mode == "range" and spec.etl_dt_range:
            lo, hi = spec.etl_dt_range
            return [p for p in all_p if lo <= p <= hi]
        return all_p[: max(1, spec.etl_dt_latest_n)]


__all__ = ["PyHiveReader"]