"""Unit tests for LLMEnricher (T035).

Note: production LLM is mocked via MockLLMClient.
"""

from __future__ import annotations

import logging

from training_data_synonym.common.llm_client import MockLLMClient
from training_data_synonym.enricher.llm_enricher import (
    ENRICHABLE_DIMS,
    LLMEnricher,
    build_enrichment_prompt,
    parse_enrichment_response,
)


DICT = {
    "category": {"values": ["咖啡", "奶茶", "快餐"]},
    "merchant": {"values": ["星巴克", "瑞幸"]},
    "avg_prc": {"values": ["0-30", "30-50"]},
    "age": {"values": ["18-25", "25-35"]},
    "occasion": {"values": ["下午茶", "午餐"]},
    "taste": {"values": ["甜", "咸"]},
}

PROMPT_TPL = (
    "你是助手。\n\n"
    "候选字典:\n{dict_block}\n\n"
    "原始信息:\n{raw_record}"
)


def test_prompt_injection():
    prompt = build_enrichment_prompt({"Cat_Nm": "咖啡"}, DICT, PROMPT_TPL)
    assert "咖啡" in prompt
    assert "原始信息" in prompt
    assert "category" in prompt


def test_parse_filters_unknown_fields():
    out = parse_enrichment_response({"category": "咖啡", "bogus": "x", "merchant": None})
    assert "category" in out
    assert "bogus" not in out
    assert "merchant" not in out  # None is dropped


def test_parse_taste_array_to_list():
    out = parse_enrichment_response({"taste": ["甜", "咸"]})
    assert out["taste"] == ["甜", "咸"]


def test_parse_taste_string_to_list():
    out = parse_enrichment_response({"taste": "甜"})
    assert out["taste"] == ["甜"]


def test_enrich_filters_dict_violations():
    enricher = LLMEnricher(MockLLMClient(seed=42), DICT, PROMPT_TPL)
    out = enricher.enrich({"Cat_Nm": "咖啡", "Brnd_Nm": "星巴克"}, item_id="x")
    # Mock may return '咖啡' or 'category=null'; check filter
    for dim in ENRICHABLE_DIMS:
        if out.get(dim) is not None:
            assert out[dim] in DICT[dim]["values"] or (
                dim == "taste" and all(x in DICT["taste"]["values"] for x in out[dim])
            )


def test_enrich_all_null_on_llm_failure():
    """When LLM fails to respond, all 6 dims are None."""
    from training_data_synonym.common.llm_client import LLMTimeoutError

    class FailClient(MockLLMClient):
        def complete(self, prompt, *, temperature=0.7, item_id=""):
            raise LLMTimeoutError("simulated")

    enricher = LLMEnricher(FailClient(), DICT, PROMPT_TPL)
    out = enricher.enrich({"Cat_Nm": "咖啡"}, item_id="x")
    for dim in ENRICHABLE_DIMS:
        assert out[dim] is None


def test_enrich_logs_dict_rejection(caplog):
    """Part B: out-of-vocab LLM value → dim becomes None + log + counter."""
    import logging

    class BadLLM(MockLLMClient):
        def complete(self, prompt, *, temperature=0.7, item_id=""):
            return {
                "category": "外星品类",
                "merchant": "外星品牌",
                "avg_prc": "30-50",
                "age": "25-35",
                "occasion": "下午茶",
                "taste": ["甜", "外星味道"],
            }

    enricher = LLMEnricher(BadLLM(seed=1), DICT, PROMPT_TPL)
    caplog.set_level(logging.WARNING, logger="training_data_synonym.enricher.llm_enricher")

    out = enricher.enrich({"Cat_Nm": "咖啡"}, item_id="test-item")

    # Dim is silently rejected → None
    assert out["category"] is None
    assert out["merchant"] is None
    # taste is filtered to in-vocab values only
    assert out["taste"] == ["甜"]
    # 3 rejections: category, merchant, taste["外星味道"]
    assert enricher.rejection_count == 3
    assert len(enricher.rejection_log) == 3
    # Structured warning emitted
    dict_rejected = [r for r in caplog.records if r.getMessage() == "dict_rejected"]
    assert len(dict_rejected) == 3
    for r in dict_rejected:
        assert getattr(r, "stage", None) == "enrich"
        assert getattr(r, "event", None) == "dict_rejection"
        assert getattr(r, "item_id", None) == "test-item"


def test_enrich_no_rejection_when_all_in_vocab():
    """In-vocab LLM values leave rejection_count == 0."""
    class GoodLLM(MockLLMClient):
        def complete(self, prompt, *, temperature=0.7, item_id=""):
            return {
                "category": "咖啡",
                "merchant": "星巴克",
                "avg_prc": "30-50",
                "age": "25-35",
                "occasion": "下午茶",
                "taste": ["甜"],
            }

    enricher = LLMEnricher(GoodLLM(seed=1), DICT, PROMPT_TPL)
    out = enricher.enrich({"Cat_Nm": "咖啡"}, item_id="x")
    assert enricher.rejection_count == 0
    assert enricher.rejection_log == []
    assert out["category"] == "咖啡"
    assert out["taste"] == ["甜"]


# ──────────────────────── v2.5 name-inference fallback ────────────────────────


def test_enrich_uses_name_hint_when_llm_returns_none(caplog):
    """v2.5: when raw Brnd_Nm is empty AND LLM returns None for merchant,
    fall back to inferred hint from Str_Nm."""

    class NullMerchantLLM(MockLLMClient):
        def complete(self, prompt, *, temperature=0.7, item_id=""):
            return {
                "category": "咖啡",
                "merchant": None,  # LLM declines to fill
                "avg_prc": "30-50",
                "age": "25-35",
                "occasion": "下午茶",
                "taste": ["甜"],
            }

    enricher = LLMEnricher(NullMerchantLLM(seed=1), DICT, PROMPT_TPL)
    caplog.set_level(logging.INFO, logger="training_data_synonym.enricher.llm_enricher")

    # raw record has empty Brnd_Nm, Str_Nm has brand keyword
    out = enricher.enrich(
        {"Brnd_Nm": "", "Str_Nm": "星巴克(测试店 0)"},
        item_id="hint-test",
    )

    # merchant filled by name hint, not None
    assert out["merchant"] == "星巴克"
    assert enricher.inferred_used_count == 1
    assert any(r["dim"] == "merchant" for r in enricher.inferred_log)
    # structured log emitted
    name_hint_logs = [r for r in caplog.records if r.getMessage() == "name_hint_used"]
    assert len(name_hint_logs) == 1


def test_enrich_no_name_fallback_for_rule_text_name():
    """v2.5: rule-text names (满50减10, 代金券) → no inference, no fallback."""

    class NullAllLLM(MockLLMClient):
        def complete(self, prompt, *, temperature=0.7, item_id=""):
            return {
                "category": None,
                "merchant": None,
                "avg_prc": None,
                "age": None,
                "occasion": None,
                "taste": None,
            }

    enricher = LLMEnricher(NullAllLLM(seed=1), DICT, PROMPT_TPL)
    out = enricher.enrich(
        {"couponName": "[券] 星巴克 30元代金券"},
        item_id="rule-test",
    )
    # No inference from rule text → all dims None (LLM returned None)
    assert enricher.inferred_used_count == 0
    for dim in ENRICHABLE_DIMS:
        assert out[dim] is None


def test_enrich_prompt_includes_name_hints_block():
    """v2.5: name hints are passed to LLM in prompt as 提示: block."""

    captured = {}

    class CapturingLLM(MockLLMClient):
        def complete(self, prompt, *, temperature=0.7, item_id=""):
            captured["prompt"] = prompt
            return {
                "category": "咖啡",
                "merchant": "星巴克",
                "avg_prc": None,
                "age": None,
                "occasion": None,
                "taste": None,
            }

    enricher = LLMEnricher(CapturingLLM(seed=1), DICT, PROMPT_TPL)
    enricher.enrich(
        {"Str_Nm": "星巴克 咖啡 下午茶 冰"}, item_id="x"
    )
    # Prompt should contain the hints block
    assert "提示" in captured["prompt"]
    assert "星巴克" in captured["prompt"]
    assert "咖啡" in captured["prompt"]


def test_enrich_rejection_log_capped_at_1000():
    """Bounded-buffer safety: rejection_log never exceeds 1000 entries."""
    class ManyBadLLM(MockLLMClient):
        def __init__(self):
            super().__init__(seed=1)

        def complete(self, prompt, *, temperature=0.7, item_id=""):
            return {
                "category": "外星品类",  # always rejected
                "merchant": "瑞幸",
                "avg_prc": "30-50",
                "age": "25-35",
                "occasion": "下午茶",
                "taste": ["甜"],
            }

    enricher = LLMEnricher(ManyBadLLM(), DICT, PROMPT_TPL)
    for i in range(1500):
        enricher.enrich({"Cat_Nm": "咖啡"}, item_id=f"x-{i}")
    assert enricher.rejection_count == 1500
    assert len(enricher.rejection_log) == 1000
    assert enricher.rejection_log[0]["item_id"] == "x-500"  # tail starts at i=500