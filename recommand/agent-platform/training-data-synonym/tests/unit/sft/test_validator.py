"""Unit tests for SFT validator (T057)."""

from __future__ import annotations

from training_data.data_model import DIM_ORDER, MessageTurn, Role, SFTSample
from training_data.sft.validator import validate_sft_sample


DICT = {
    "category": {"values": ["咖啡", "奶茶"]},
    "consumable_type": {"values": ["food", "drink", "mixed", "none"]},
    "brand": {"values": ["星巴克", "瑞幸"]},
    "avg_prc": {"values": ["0-30", "30-50"]},
    "distance": {"values": ["0-500", "500-1000"]},
    "age": {"values": ["18-25", "25-35"]},
    "occasion": {"values": ["下午茶", "午餐"]},
    "taste": {"values": ["甜", "咸"]},
}


def _ok_sample() -> SFTSample:
    return SFTSample(
        item_id="i1",
        item_type=Role.MEITUAN_SHOP,
        intent="search_item",
        messages=[
            MessageTurn(role="user", content="想喝咖啡"),
            MessageTurn(role="assistant", content="好的"),
        ],
        params={
            "category": {"op": "in", "values": ["咖啡"]},
            "consumable_type": {"op": "eq", "values": "drink"},
            "brand": None,
            "avg_prc": None,
            "distance": None,
            "age": None,
            "occasion": None,
            "taste": None,
        },
        order_by=None,
    )


def test_valid_sample():
    ok, errs = validate_sft_sample(_ok_sample(), DICT)
    assert ok, errs


def test_invalid_messages_length_zero():
    s = _ok_sample()
    s.messages = []
    ok, errs = validate_sft_sample(s, DICT)
    assert not ok
    assert any("empty" in e for e in errs)


def test_invalid_messages_length_six():
    s = _ok_sample()
    s.messages = [MessageTurn(role="user", content=f"turn {i}") for i in range(6)]
    ok, errs = validate_sft_sample(s, DICT)
    assert not ok
    assert any("messages length" in e for e in errs)


def test_first_turn_must_be_user():
    s = _ok_sample()
    s.messages = [MessageTurn(role="assistant", content="hi"), MessageTurn(role="user", content="hi")]
    ok, errs = validate_sft_sample(s, DICT)
    assert not ok
    assert any("messages[0].role" in e for e in errs)


def test_negative_must_have_type():
    s = _ok_sample()
    s.negative = True
    s.negative_type = None
    ok, errs = validate_sft_sample(s, DICT)
    assert not ok
    assert any("negative_type" in e for e in errs)


def test_non_negative_must_have_null_type():
    s = _ok_sample()
    s.negative = False
    s.negative_type = "reject"
    ok, errs = validate_sft_sample(s, DICT)
    assert not ok


def test_invalid_intent():
    s = _ok_sample()
    s.intent = "unknown_intent"
    ok, errs = validate_sft_sample(s, DICT)
    assert not ok


def test_invalid_order_by():
    s = _ok_sample()
    s.order_by = "random_order"
    ok, errs = validate_sft_sample(s, DICT)
    assert not ok


def test_three_consecutive_newlines_rejected():
    s = _ok_sample()
    s.messages = [
        MessageTurn(role="user", content="hello\n\n\nworld"),
        MessageTurn(role="assistant", content="hi"),
    ]
    ok, errs = validate_sft_sample(s, DICT)
    assert not ok


def test_tab_in_content_rejected():
    s = _ok_sample()
    s.messages = [
        MessageTurn(role="user", content="a\tb"),
        MessageTurn(role="assistant", content="hi"),
    ]
    ok, errs = validate_sft_sample(s, DICT)
    assert not ok


def test_dict_validation_propagates():
    """Bad dict value triggers DictValidation error."""
    s = _ok_sample()
    s.params["category"] = {"op": "in", "values": ["unknown_category"]}
    ok, errs = validate_sft_sample(s, DICT)
    assert not ok
    assert any("dictionary" in e for e in errs)