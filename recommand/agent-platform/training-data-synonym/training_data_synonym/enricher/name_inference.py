"""Heuristic inference from product names (v2.5 fallback path).

When raw fields like ``Brnd_Nm`` / ``Cat_Nm`` are empty, OR the available
text is **rule prose** (``满50减10``, ``代金券``, ``限时抢购``) instead of a
product description, we fall back to substring matching the product's
**name** (``Str_Nm`` / ``shopName`` / ``couponName``) against the dict values.

Usage::

    hints = compute_name_hints(raw, dim_dict, brand_values)
    # hints = {"merchant": "星巴克", "category": "咖啡", "occasion": "下午茶", "taste": ["甜"]}

The heuristics are deliberately conservative: rule-text names produce empty
hints (no spurious brand inference from a discount description). When the
name contains a brand/category keyword AND rule text, ``is_rule_text`` wins
and we return nothing — better to leave the dim null than to inject a wrong
brand.
"""

from __future__ import annotations

import re
from typing import Optional


# Patterns that strongly suggest the name is rule prose, not a product
# description. If ANY matches, ALL inference is suppressed for that name.
_RULE_TEXT_PATTERNS = (
    re.compile(r"满\d+减\d+"),       # 满50减10
    re.compile(r"\d+折"),             # 8折
    re.compile(r"限时"),              # 限时
    re.compile(r"抢购"),
    re.compile(r"到店"),
    re.compile(r"核销"),
    re.compile(r"有效期"),
    re.compile(r"使用说明"),
    re.compile(r"不与其他"),
    re.compile(r"代金券"),
    re.compile(r"优惠券"),
    re.compile(r"兑换券"),
    re.compile(r"^\s*\[券\]"),
)


def is_rule_text(name: str | None) -> bool:
    """Return True if name looks like rule prose (suppresses inference)."""
    if not name:
        return False
    return any(p.search(name) for p in _RULE_TEXT_PATTERNS)


def get_product_name(raw: dict) -> str:
    """Return the most product-descriptive name from raw, in priority order.

    Meituan / self shop use ``Str_Nm`` / ``shopName``; coupons use
    ``couponName``. We strip leading "[券]" / "【券】" wrappers when the name
    is otherwise informative.
    """
    raw_name = (
        raw.get("Str_Nm")
        or raw.get("shopName")
        or raw.get("couponName")
        or ""
    )
    if not raw_name:
        return ""
    # Only strip "[券]" if the rest looks informative (length > 2).
    stripped = re.sub(r"^\s*[\[【]券[\]】]\s*", "", str(raw_name)).strip()
    return stripped or str(raw_name).strip()


def _longest_substring_match(name: str, candidates: list[str]) -> Optional[str]:
    """Return the longest candidate that appears as a substring of name."""
    if not name or not candidates:
        return None
    found = [c for c in candidates if c and c in name]
    if not found:
        return None
    return max(found, key=len)


def infer_brand(name: str, brand_values: list[str]) -> Optional[str]:
    """Infer merchant / brand from product name via longest substring match."""
    if is_rule_text(name):
        return None
    return _longest_substring_match(name, brand_values)


def infer_category(name: str, category_values: list[str]) -> Optional[str]:
    if is_rule_text(name):
        return None
    return _longest_substring_match(name, category_values)


def infer_taste(name: str, taste_values: list[str]) -> list[str]:
    """Return all taste keywords found as substrings (taste is array-typed)."""
    if is_rule_text(name):
        return []
    if not name or not taste_values:
        return []
    return [t for t in taste_values if t and t in name]


def infer_occasion(name: str, occasion_values: list[str]) -> Optional[str]:
    if is_rule_text(name):
        return None
    return _longest_substring_match(name, occasion_values)


def compute_name_hints(
    raw: dict, dim_dict: dict, brand_values: list[str]
) -> dict:
    """Compute inferred hints for one raw record.

    Returns a dict with keys from ``{"merchant", "category", "taste",
    "occasion"}`` and values either a string, list, or ``None`` (no hint
    inferred). Empty / rule-text names produce an empty dict.
    """
    name = get_product_name(raw)
    if not name or is_rule_text(name):
        return {}
    return {
        "merchant": infer_brand(name, brand_values),
        "category": infer_category(
            name, dim_dict.get("category", {}).get("values", [])
        ),
        "taste": infer_taste(
            name, dim_dict.get("taste", {}).get("values", [])
        ),
        "occasion": infer_occasion(
            name, dim_dict.get("occasion", {}).get("values", [])
        ),
    }


__all__ = [
    "compute_name_hints",
    "get_product_name",
    "infer_brand",
    "infer_category",
    "infer_occasion",
    "infer_taste",
    "is_rule_text",
]
