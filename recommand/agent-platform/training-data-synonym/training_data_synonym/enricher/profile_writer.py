"""item_profile writer — flat JSONL merging Hive raw columns + AI tags.

Produces ``item_profile.jsonl`` (Stage 2 output) where each line is a flat dict
with Hive columns (str_id, str_nm, type, city_nm, cnty_nm, lng, lat, cat_nm)
and 8 AI-inferred dims inline.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..data_model import DIM_ORDER, ItemTags, Role

# Hive column → profile key mapping, per item_type
_PROFILE_MAP = {
    Role.MEITUAN_SHOP: {
        "str_id":   "Str_Id",
        "str_nm":   "Str_Nm",
        "cat_nm":   "Cat_Nm",
    },
    Role.SELF_SHOP: {
        "str_id":   "shopid",
        "str_nm":   "shopName",
        "cat_nm":   "Brnd_Nm",   # self_shop has no Cat_Nm; use Brnd_Nm as name fallback
    },
    Role.COUPON: {
        "str_id":   "couponId",
        "str_nm":   "couponName",
        "cat_nm":   None,        # coupon template has no category column
    },
}

# Type abbreviations for the profile
_TYPE_LABEL = {
    Role.MEITUAN_SHOP: "mt_shop",
    Role.SELF_SHOP:    "self_shop",
    Role.COUPON:       "coupon",
}

# Geo fields come from raw_record, not tags
_GEO_FIELDS = ["Lng", "Lat"]
_CITY_FIELDS = ["City_Nm", "City_Nm", "Cnty_Nm"]


def _get(raw: dict, *keys: str) -> str | None:
    for k in keys:
        v = raw.get(k)
        if v is not None:
            return str(v)
    return None


def write_item_profile(items: list[ItemTags], path: str | Path) -> int:
    """Write ``item_profile.jsonl``. Returns number of rows written."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", encoding="utf-8") as f:
        for item in items:
            raw = item.raw_record
            role = item.item_type
            mapping = _PROFILE_MAP.get(role, {})
            type_label = _TYPE_LABEL.get(role, "unknown")

            profile: dict[str, object] = {
                "str_id":   _get(raw, *(k for k in [mapping.get("str_id", "")] if k)),
                "str_nm":   _get(raw, *(k for k in [mapping.get("str_nm", "")] if k)),
                "type":     type_label,
                "city_nm":  _get(raw, "City_Nm", "city_nm"),
                "cnty_nm":  _get(raw, "Cnty_Nm", "cnty_nm"),
                "lng":      _get(raw, "Lng", "lng"),
                "lat":      _get(raw, "Lat", "lat"),
                "cat_nm":   _get(raw, *(k for k in [mapping.get("cat_nm", "")] if k)),
            }
            # Merge 8-dim AI tags
            for dim in DIM_ORDER:
                profile[dim] = item.tags.get(dim)

            f.write(json.dumps(profile, ensure_ascii=False) + "\n")
            written += 1
    return written


__all__ = ["write_item_profile"]
