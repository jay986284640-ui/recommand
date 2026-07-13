"""Unit tests for distance_geo (T031)."""

from __future__ import annotations

from training_data.data_model import Role, TagOrigin
from training_data.enricher.distance_geo import extract_distance_tag


def test_geo_source_when_lng_lat_present():
    d_val, d_src = extract_distance_tag(Role.MEITUAN_SHOP, 121.45, 31.23)
    assert d_val is None  # always None at Stage 1
    assert d_src == TagOrigin.GEO


def test_missing_source_when_lng_lat_null():
    d_val, d_src = extract_distance_tag(Role.MEITUAN_SHOP, None, None)
    assert d_val is None
    assert d_src == TagOrigin.MISSING


def test_missing_when_out_of_range():
    # longitude > 180
    d_val, d_src = extract_distance_tag(Role.MEITUAN_SHOP, 200.0, 31.0)
    assert d_src == TagOrigin.MISSING


def test_missing_when_zero_zero():
    d_val, d_src = extract_distance_tag(Role.MEITUAN_SHOP, 0.0, 0.0)
    assert d_src == TagOrigin.MISSING


def test_never_ai():
    """distance tag_source must NEVER be ai (per contracts/item_tags_v2.md)."""
    for lng, lat in [(121.0, 31.0), (None, None), (-180, 90), (0.0, 0.0)]:
        _, d_src = extract_distance_tag(Role.MEITUAN_SHOP, lng, lat)
        assert d_src in (TagOrigin.GEO, TagOrigin.MISSING)


def test_geo_for_coupon_passthrough():
    """Coupon items with binding shop geo should also be geo."""
    d_val, d_src = extract_distance_tag(Role.COUPON, 121.0, 31.0)
    assert d_src == TagOrigin.GEO


def test_truncation_to_6_decimals_not_applied_in_distance_geo():
    """extract_distance_tag is a pure presence check; truncation is in extract_geo."""
    d_val, d_src = extract_distance_tag(Role.MEITUAN_SHOP, 121.4567890123, 31.2345678901)
    assert d_src == TagOrigin.GEO