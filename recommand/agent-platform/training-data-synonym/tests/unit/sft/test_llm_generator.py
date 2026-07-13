"""Unit tests for llm_generator (T058)."""

from __future__ import annotations

from training_data.common.llm_client import MockLLMClient
from training_data.sft.llm_generator import (
    LLMGenerator,
    build_sft_prompt,
    parse_sft_response,
)


PROMPT = "item: {item_tags}\ntarget: intent={target_intent} params={target_params} order_by={target_order_by} turns={target_turns} neg={negative_type} tmpl={sentence_template}"


def test_prompt_injection():
    p = build_sft_prompt(
        item_tags_dict={"item_id": "x", "tags": {"category": "咖啡"}},
        target_intent="search_item",
        target_params={"category": {"op": "in", "values": ["咖啡"]}},
        target_order_by="distance",
        target_turns=3,
        negative_type=None,
        sentence_template="query_first",
        prompt_template=PROMPT,
    )
    assert "咖啡" in p
    assert "search_item" in p
    assert "distance" in p


def test_parse_sft_response_basic():
    msgs, covered = parse_sft_response({
        "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}],
        "covered_dims": ["category"],
    })
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert covered == ["category"]


def test_parse_sft_response_no_covered():
    msgs, covered = parse_sft_response({
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert covered == []


def test_generate_with_mock():
    gen = LLMGenerator(MockLLMClient(seed=42), PROMPT)
    # Prompt must contain "目标:" + "intent:" patterns for MockLLMClient to recognize Stage 2
    msgs, covered = gen.generate(
        item_tags_dict={"item_id": "x"},
        target_intent="search_item",
        target_params={"distance": {"op": "in", "values": ["0-500"]}},
        target_order_by="distance",
        target_turns=3,
        negative_type=None,
        sentence_template="query_first",
    )
    assert len(msgs) >= 1
    assert msgs[0].role == "user"