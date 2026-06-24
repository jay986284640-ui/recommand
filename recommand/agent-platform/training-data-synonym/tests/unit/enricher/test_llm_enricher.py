"""Unit tests for LLMEnricher (T035).

Note: production LLM is mocked via MockLLMClient.
"""

from __future__ import annotations

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
        def complete(self, prompt, temperature=0.7):
            raise LLMTimeoutError("simulated")

    enricher = LLMEnricher(FailClient(), DICT, PROMPT_TPL)
    out = enricher.enrich({"Cat_Nm": "咖啡"}, item_id="x")
    for dim in ENRICHABLE_DIMS:
        assert out[dim] is None