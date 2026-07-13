"""distance_geo — Stage 1 transparent lng/lat extraction.

Per FR-008b. NEVER calls LLM. Sets tag_source.distance = geo | missing only.
"""

from __future__ import annotations

from typing import Optional

from ..common.logging import get_logger
from ..data_model import Role, TagOrigin

logger = get_logger(__name__)


def extract_distance_tag(
    item_type: Role,
    shop_lng: Optional[float],
    shop_lat: Optional[float],
) -> tuple[Optional[str], TagOrigin]:
    """Return (distance_value, tag_source).

    distance_value is always None at Stage 1 (no user known).
    tag_source is `geo` if shop_lng/lat usable, `missing` otherwise.

    This is the gatekeeper — `geo` ⇒ raw_record.shop_lng/lat is present
    and valid; runtime LP Agent can compute real distance downstream.
    """
    if shop_lng is None or shop_lat is None:
        return (None, TagOrigin.MISSING)
    if abs(shop_lng) > 180 or abs(shop_lat) > 90:
        return (None, TagOrigin.MISSING)
    if shop_lng == 0 and shop_lat == 0:
        return (None, TagOrigin.MISSING)

    return (None, TagOrigin.GEO)


__all__ = ["extract_distance_tag"]