"""llm_generator — Stage 3: dialogue generator.

Prompts the LLM with item data; parses the response into conversation,
params, intent, scenario_type, state_change, and guide_text.
"""

from __future__ import annotations

from ..common.exceptions import ValidationError
from ..common.llm_client import LLMClient
from ..common.logging import get_logger
from ..data_model import MessageTurn
from .prompt import build_sft_prompt

logger = get_logger(__name__)

# Fields in the params schema (fixed set per prompt)
_PARAMS_FIELDS = ["category", "brand", "distance", "price", "taste", "occasion", "consumable_type"]  # already correct


def parse_sft_response(payload: dict) -> dict:
    """Parse LLM JSON → dict with conversation, intent, params, guide_text etc."""
    if not isinstance(payload, dict):
        raise ValidationError("LLM response not a dict")

    # conversation
    raw_conv = payload.get("conversation", [])
    if not isinstance(raw_conv, list):
        raise ValidationError("conversation field is not a list")

    messages = []
    for m in raw_conv:
        if not isinstance(m, dict) or "role" not in m or "content" not in m:
            raise ValidationError(f"bad message entry: {m}")
        messages.append(MessageTurn(role=str(m["role"]), content=str(m["content"])))

    # params — validate and filter to known fields
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    params = {k: v for k, v in params.items() if k in _PARAMS_FIELDS}

    return {
        "messages": messages,
        "params": params,
        "guide_text": str(payload.get("guide_text", "") or ""),
        "intent": str(payload.get("intent", "search_product") or "search_product"),
        "scenario_type": str(payload.get("scenario_type", "") or ""),
        "state_change": payload.get("state_change") or {},
    }


class LLMGenerator:
    def __init__(self, llm_client: LLMClient, prompt_template: str) -> None:
        self._llm = llm_client
        self._template = prompt_template

    @property
    def model_name(self) -> str:
        return self._llm.model_name

    def generate(self, *, item: dict, scenario_type: str, target_turns: int,
                 item_id: str = "") -> dict:
        """Generate a dialogue + params from item data + scenario + turn count."""
        prompt = build_sft_prompt(
            item=item, scenario_type=scenario_type,
            target_turns=target_turns, template=self._template,
        )
        resp = self._llm.complete(prompt, temperature=0.7, item_id=item_id)
        if not isinstance(resp, dict):
            raise ValidationError(f"LLM response not a dict: {type(resp).__name__}")
        return parse_sft_response(resp)


__all__ = ["LLMGenerator", "parse_sft_response"]

