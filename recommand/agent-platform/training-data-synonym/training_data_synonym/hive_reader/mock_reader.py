"""MockHiveReader — reads fixture jsonl files, no external system access.

Per contracts/hive_read_v1.md §MockHiveReader + research.md D-013.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from ..common.exceptions import EmptyPartitionSet, SensitiveLeakError
from ..common.logging import get_logger
from ..data_model import HiveReadSpec, RawRecord, Role, TableMeta
from .base import HiveReader, extract_geo, synthesize_item_id

logger = get_logger(__name__)


class MockHiveReader(HiveReader):
    def __init__(self, fixture_dir: str | Path) -> None:
        self._fixture_dir = Path(fixture_dir)
        if not self._fixture_dir.exists():
            raise FileNotFoundError(f"fixture dir not found: {self._fixture_dir}")

    def list_partitions(self, table_meta: TableMeta) -> list[str]:
        # Single synthetic partition for fixtures
        return ["20260620"]

    def read(
        self, table_meta: TableMeta, spec: HiveReadSpec
    ) -> Iterator[RawRecord]:
        # Selection: latest_n / range / single — fixtures only have one partition
        if spec.etl_dt_mode not in {"single", "range", "latest_n"}:
            raise ValueError(f"unknown etl_dt_mode: {spec.etl_dt_mode}")
        partitions = self.list_partitions(table_meta)
        if not partitions:
            raise EmptyPartitionSet(f"No partitions for {table_meta.table_name}")

        fixture_path = self._fixture_dir / f"{table_meta.table_name}.jsonl"
        if not fixture_path.exists():
            logger.warning(
                "fixture_missing",
                extra={
                    "stage": "mock_hive",
                    "event": "fixture_missing",
                    "table": table_meta.table_name,
                    "path": str(fixture_path),
                },
            )
            return

        with fixture_path.open(encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]

        # Sample (deterministic slice)
        if spec.sample_n_per_type is not None:
            records = records[: spec.sample_n_per_type]

        for raw in records:
            # 1. sensitive column drop
            for col in spec.sensitive_columns_blocklist:
                raw.pop(col, None)

            # 2. item_id synthesis
            item_id = synthesize_item_id(table_meta, raw)
            if not item_id or item_id == "mt-" or item_id == "self-" or item_id == "cpn-":
                continue

            # 3. shop_lng / shop_lat (caller may supply coupon_shop binding later)
            shop_lng, shop_lat = extract_geo(table_meta, raw)
            etl_dt = raw.pop("etl_dt", "20260620") or "20260620"

            # Sanity: sensitive column must not appear in raw
            for col in spec.sensitive_columns_blocklist:
                if col in raw:
                    raise SensitiveLeakError(
                        f"sensitive column '{col}' survived MockHiveReader.read()"
                    )

            yield RawRecord(
                item_id=item_id,
                item_type=table_meta.inferred_role,
                raw=raw,
                shop_lng=shop_lng,
                shop_lat=shop_lat,
                etl_dt=etl_dt,
            )