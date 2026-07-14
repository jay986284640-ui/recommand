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

def parse_sft_response(payload: dict, param_fields: set | None = None) -> dict:
    """Parse LLM JSON → dict with conversation, intent, params, guide_text etc.

    Args:
        payload: Raw LLM JSON response.
        param_fields: Allowed param field names (from config). None = no filtering.
    """
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

    # params — filter to known fields if specified
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    if param_fields:
        params = {k: v for k, v in params.items() if k in param_fields}

    return {
        "messages": messages,
        "params": params,
        "guide_text": str(payload.get("guide_text", "") or ""),
        "intent": str(payload.get("intent", "search_product") or "search_product"),
        "scenario_type": str(payload.get("scenario_type", "") or ""),
        "state_change": payload.get("state_change") or {},
    }


class LLMGenerator:
    def __init__(self, llm_client: LLMClient, prompt_template: str,
                 param_fields: set | None = None) -> None:
        self._llm = llm_client
        self._template = prompt_template
        self._param_fields = param_fields

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
        # DEBUG: full prompt content
        logger.debug("sft_prompt", extra={
            "stage": "sft", "item_id": item_id,
            "scenario_type": scenario_type, "target_turns": target_turns,
            "prompt": prompt,
        })
        resp = self._llm.complete(prompt, temperature=0.7, item_id=item_id)
        # DEBUG: raw LLM response
        logger.debug("sft_raw_response", extra={
            "stage": "sft", "item_id": item_id, "response": resp,
        })
        if not isinstance(resp, dict):
            raise ValidationError(f"LLM response not a dict: {type(resp).__name__}")

        result = parse_sft_response(resp, self._param_fields)
        logger.info("sft_result", extra={
            "stage": "sft", "item_id": item_id,
            "scenario_type": scenario_type,
            "has_guide_text": bool(result.get("guide_text")),
            "guide_text_len": len(result.get("guide_text", "")),
            "msg_count": len(result.get("messages", [])),
            "param_keys": list(result.get("params", {}).keys()),
        })
        return result


__all__ = ["LLMGenerator", "parse_sft_response"]

