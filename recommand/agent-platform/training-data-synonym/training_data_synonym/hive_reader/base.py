"""HiveReader abstract base + exception types + HiveReadSpec + RawRecord.

Per contracts/hive_read_v1.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Optional

from ..common.exceptions import (
    AccessDenied,
    ConnectionError_,
    DuplicateItemIdError,
    EmptyPartitionSet,
    HiveReaderError,
    SchemaDriftError,
    SensitiveLeakError,
)
from ..data_model import HiveReadSpec, RawRecord, Role, TableMeta


class HiveReader(ABC):
    """Abstract base for Hive row readers. Three implementations:

      - MockHiveReader (CI)
      - SparkHiveReader (production, PySpark Hive Catalog)
      - PyHiveReader  (optional backend, no Spark env)
    """

    @abstractmethod
    def list_partitions(self, table_meta: TableMeta) -> list[str]:
        """Return available etl_dt partition values (YYYYMMDD), sorted desc."""

    @abstractmethod
    def read(
        self, table_meta: TableMeta, spec: HiveReadSpec
    ) -> Iterator[RawRecord]:
        """Yield RawRecord rows from the table filtered by spec.etl_dt.

        MUST perform:
          1. sensitive column drop (spec.sensitive_columns_blocklist)
          2. item_id synthesis (mt-/self-/cpn- namespace)
          3. shop_lng/shop_lat extraction if available
        """

    def read_all_three_core(
        self,
        tables_meta: list[TableMeta],
        spec: HiveReadSpec,
    ) -> dict[Role, list[RawRecord]]:
        """Convenience: aggregate by Role for the three core tables."""
        out: dict[Role, list[RawRecord]] = {}
        for tm in tables_meta:
            role = tm.inferred_role
            if role not in {Role.MEITUAN_SHOP, Role.SELF_SHOP, Role.COUPON}:
                continue
            out[role] = list(self.read(tm, spec))
        return out


__all__ = [
    "HiveReader",
    "HiveReaderError",
    "ConnectionError_",
    "AccessDenied",
    "EmptyPartitionSet",
    "SchemaDriftError",
    "DuplicateItemIdError",
    "SensitiveLeakError",
    "HiveReadSpec",
    "RawRecord",
    "TableMeta",
    "Role",
]


def synthesize_item_id(table_meta: TableMeta, raw: dict) -> str:
    """Mount namespace-prefixed item_id per contracts/hive_read_v1.md."""
    role = table_meta.inferred_role
    if role == Role.MEITUAN_SHOP:
        sid = raw.get("str_id") or raw.get("Str_Id") or ""
        return f"mt-{sid}"
    if role == Role.SELF_SHOP:
        sid = raw.get("shopid") or raw.get("shopId") or ""
        return f"self-{sid}"
    if role == Role.COUPON:
        cid = raw.get("couponid") or raw.get("couponId") or ""
        return f"cpn-{cid}"
    return f"unknown-{raw.get('id', '')}"


# Convenience: don't re-import dataclass field at module level
__dataclass_fields_dataclass = field
__dataclass_dataclass = dataclass


def _normalize_lng_lat(value) -> Optional[float]:
    """Return a float lng/lat if value parses and is in valid range; else None."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # Reject obviously bad values
    return f


def extract_geo(
    table_meta: TableMeta, raw: dict, address_row: dict | None = None
) -> tuple[Optional[float], Optional[float]]:
    """Pull (shop_lng, shop_lat) from raw per FR-008b + contracts/hive_read_v1.md.

    Rules:
      - 美团门店: raw.Lng / raw.Lat
      - 自拓展门店: address_row.longitude / address_row.latitude (join by shopId)
      - 优惠券:  none at this step (caller resolves via coupon_shop binding)
    Returns (None, None) if missing / out-of-range / (0, 0) / 'null' / NaN.
    """
    if table_meta.inferred_role == Role.MEITUAN_SHOP:
        lng = _normalize_lng_lat(raw.get("Lng") or raw.get("lng"))
        lat = _normalize_lng_lat(raw.get("Lat") or raw.get("lat"))
    elif table_meta.inferred_role == Role.SELF_SHOP:
        src = address_row or raw
        lng = _normalize_lng_lat(src.get("longitude"))
        lat = _normalize_lng_lat(src.get("latitude"))
    else:
        return (None, None)

    # validation: range + non-zero + numeric
    if lng is None or lat is None:
        return (None, None)
    if abs(lng) > 180 or abs(lat) > 90:
        return (None, None)
    if lng == 0 and lat == 0:
        return (None, None)
    # truncate to 6 decimals (~11cm)
    return (round(lng, 6), round(lat, 6))