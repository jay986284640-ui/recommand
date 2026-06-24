"""Unit tests for consumable_mapper (T032)."""

from __future__ import annotations

from training_data_synonym.data_model import TagOrigin
from training_data_synonym.enricher.consumable_mapper import ConsumableMapper


def _mapping():
    return {
        "_meta": {"version": "1.0"},
        "map": {
            "drink": ["咖啡", "奶茶"],
            "food": ["快餐", "中餐"],
            "mixed": ["便利店"],
        },
        "default": "none",
        "coupon_text_hints": {
            "drink": ["咖啡", "拿铁"],
            "food": ["汉堡", "炸鸡"],
        },
    }


def test_drink_via_category():
    m = ConsumableMapper(_mapping(), llm_client=None)
    v, s = m.map(category="咖啡", item_id="x", raw_record={})
    assert v == "drink"
    assert s == TagOrigin.DERIVED


def test_food_via_category():
    m = ConsumableMapper(_mapping(), llm_client=None)
    v, s = m.map(category="快餐", item_id="x", raw_record={})
    assert v == "food"
    assert s == TagOrigin.DERIVED


def test_default_for_unknown_category():
    m = ConsumableMapper(_mapping(), llm_client=None)
    v, s = m.map(category="日料", item_id="x", raw_record={})
    assert v == "none"
    assert s == TagOrigin.DERIVED


def test_coupon_text_hint_fallback():
    """When category missing but couponName/productDesc has hint → derived."""
    m = ConsumableMapper(_mapping(), llm_client=None)
    v, s = m.map(category=None, item_id="x",
                 raw_record={"couponName": "汉堡套餐", "productDesc": ""})
    assert v == "food"
    assert s == TagOrigin.DERIVED


def test_null_category_no_hint_returns_default():
    m = ConsumableMapper(_mapping(), llm_client=None)
    v, s = m.map(category=None, item_id="x", raw_record={})
    assert v == "none"
    assert s == TagOrigin.DERIVED


def test_invalid_value_returns_default():
    """Category NOT in any mapping's values → falls back to default."""
    bad_map = {"_meta": {"version": "1.0"}, "map": {"food": ["快餐"]}, "default": "none"}
    m = ConsumableMapper(bad_map, llm_client=None)
    v, s = m.map(category="咖啡", item_id="x", raw_record={})
    # 咖啡 not in {快餐} → no match → default 'none'
    assert v == "none"
    assert s == TagOrigin.DERIVED


def test_value_not_in_VALID_VALUES_passes_through_mapping():
    """If a mapping entry's value isn't in VALID_VALUES, it's still mapped as-is
    (downstream tag_schema validator handles escape)."""
    bad_map = {"_meta": {"version": "1.0"}, "map": {"weird": ["咖啡"]}, "default": "none"}
    m = ConsumableMapper(bad_map, llm_client=None)
    v, s = m.map(category="咖啡", item_id="x", raw_record={})
    # 咖啡 → 'weird' (mapping doesn't validate values)
    assert v == "weird"
    assert s == TagOrigin.DERIVED