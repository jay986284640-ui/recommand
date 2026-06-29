"""Unit tests for consumable_mapper (T032)."""

from __future__ import annotations

import logging

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


def test_consumable_type_rejected_logged(caplog):
    """Part B: LLM-returned consumable_type not in VALID_VALUES → silent reject + log + counter."""
    import logging

    from training_data_synonym.common.llm_client import MockLLMClient

    class BadCTLLM(MockLLMClient):
        def complete(self, prompt, *, temperature=0.7, item_id=""):
            return {"consumable_type": "snack"}  # not in {food,drink,mixed,none}

    m = ConsumableMapper(_mapping(), llm_client=BadCTLLM(seed=1))
    caplog.set_level(
        logging.WARNING, logger="training_data_synonym.enricher.consumable_mapper"
    )

    # Force the LLM path: category not in map (e.g. 日料), no text hints, but text present.
    raw = {"productDesc": "咖啡拿铁"}
    v, s = m.map(category="日料", item_id="ct-test", raw_record=raw)

    # Out-of-vocab → silent reject → falls through to default 'none'
    assert v == "none"
    assert m.rejection_count == 1
    rejects = [r for r in caplog.records if r.getMessage() == "consumable_type_rejected"]
    assert len(rejects) == 1
    assert getattr(rejects[0], "rejected_value", None) == "snack"
    assert getattr(rejects[0], "item_id", None) == "ct-test"
    assert getattr(rejects[0], "dim", None) == "consumable_type"


def test_consumable_type_valid_no_rejection():
    """In-vocab consumable_type → no rejection logged."""
    from training_data_synonym.common.llm_client import MockLLMClient

    class GoodCTLLM(MockLLMClient):
        def complete(self, prompt, *, temperature=0.7, item_id=""):
            return {"consumable_type": "drink"}

    m = ConsumableMapper(_mapping(), llm_client=GoodCTLLM(seed=1))
    raw = {"productDesc": "拿铁"}
    v, s = m.map(category="日料", item_id="ct-ok", raw_record=raw)
    assert v == "drink"
    assert s == TagOrigin.AI
    assert m.rejection_count == 0


# ──────────────────────── v2.5 name-inference category fallback ────────────────────────


def test_name_inferred_category_when_cat_nm_empty(caplog):
    """v2.5: empty Cat_Nm + product name contains category → inferred category → mapping."""
    m = ConsumableMapper(_mapping(), llm_client=None,
                          category_values=["咖啡", "奶茶", "快餐", "中餐", "西餐"])
    caplog.set_level(logging.INFO, logger="training_data_synonym.enricher.consumable_mapper")
    raw = {"Str_Nm": "星巴克 咖啡 馆"}  # no Cat_Nm, but name has "咖啡"
    v, s = m.map(category=None, item_id="inf-test", raw_record=raw)
    # 咖啡 is in mapping → drink
    assert v == "drink"
    assert s == TagOrigin.DERIVED
    assert m.inferred_count == 1
    assert any(r.getMessage() == "name_inferred_category" for r in caplog.records)


def test_name_inference_skipped_for_rule_text_name():
    """v2.5: rule-text names (满50减10, 代金券) → no inference → default 'none'."""
    m = ConsumableMapper(_mapping(), llm_client=None,
                          category_values=["咖啡", "奶茶"])
    raw = {"couponName": "[券] 咖啡 满50减10"}
    v, s = m.map(category=None, item_id="rule-test", raw_record=raw)
    assert v == "none"
    assert m.inferred_count == 0


def test_name_inference_no_match_returns_default():
    """v2.5: name has no category keyword → default fallback."""
    m = ConsumableMapper(_mapping(), llm_client=None,
                          category_values=["咖啡", "奶茶"])
    raw = {"Str_Nm": "外星料理馆"}
    v, s = m.map(category=None, item_id="no-match", raw_record=raw)
    assert v == "none"
    assert m.inferred_count == 0