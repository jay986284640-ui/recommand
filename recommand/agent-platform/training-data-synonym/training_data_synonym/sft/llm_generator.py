"""llm_generator — Stage 2 multi-turn dialogue generator with ground-truth injection.

Per research.md D-011. Builds prompt with target ground-truth, calls LLM,
parses structured JSON, validates messages.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..common.exceptions import ValidationError
from ..common.llm_client import LLMClient
from ..common.logging import get_logger
from ..data_model import DIM_ORDER, MessageTurn, Role, SFTSample

logger = get_logger(__name__)


def build_sft_prompt(
    item_tags_dict: dict,
    target_intent: str,
    target_params: dict,
    target_order_by: Optional[str],
    target_turns: int,
    negative_type: Optional[str],
    sentence_template: str,
    prompt_template: str,
) -> str:
    """Inject ground-truth into the Stage 2 prompt template."""
    intent_block = (
        f"- intent:    {target_intent}\n"
        f"- params:    {json.dumps(target_params, ensure_ascii=False)}\n"
        f"- order_by:  {target_order_by}\n"
        f"- 对话轮数:  {target_turns}\n"
        f"- 负样本类型: {negative_type or 'none'}\n"
        f"- 句式骨架:  {sentence_template}"
    )
    return (
        prompt_template
        .replace("{item_tags}", json.dumps(item_tags_dict, ensure_ascii=False, default=str))
        .replace("{target_intent}", target_intent)
        .replace("{target_params}", json.dumps(target_params, ensure_ascii=False, default=str))
        .replace("{target_order_by}", target_order_by or "null")
        .replace("{target_turns}", str(target_turns))
        .replace("{negative_type}", negative_type or "none")
        .replace("{sentence_template}", sentence_template)
    )


def parse_sft_response(payload: dict) -> tuple[list[MessageTurn], list[str]]:
    """Parse LLM JSON → (messages, covered_dims)."""
    if not isinstance(payload, dict):
        raise ValidationError("LLM response not a dict")
    raw_msgs = payload.get("messages", [])
    if not isinstance(raw_msgs, list):
        raise ValidationError("messages field is not a list")
    messages = []
    for m in raw_msgs:
        if not isinstance(m, dict) or "role" not in m or "content" not in m:
            raise ValidationError(f"bad message entry: {m}")
        messages.append(MessageTurn(role=str(m["role"]), content=str(m["content"])))
    covered_dims = list(payload.get("covered_dims", []) or [])
    return messages, covered_dims


class LLMGenerator:
    def __init__(
        self,
        llm_client: LLMClient,
        prompt_template: str,
    ) -> None:
        self._llm = llm_client
        self._template = prompt_template

    def generate(
        self,
        *,
        item_tags_dict: dict,
        target_intent: str,
        target_params: dict,
        target_order_by: Optional[str],
        target_turns: int,
        negative_type: Optional[str],
        sentence_template: str,
    ) -> tuple[list[MessageTurn], list[str]]:
        prompt = build_sft_prompt(
            item_tags_dict=item_tags_dict,
            target_intent=target_intent,
            target_params=target_params,
            target_order_by=target_order_by,
            target_turns=target_turns,
            negative_type=negative_type,
            sentence_template=sentence_template,
            prompt_template=self._template,
        )
        resp = self._llm.complete(prompt, temperature=0.7)
        if not isinstance(resp, dict):
            raise ValidationError(f"LLM response not a dict: {type(resp).__name__}")
        return parse_sft_response(resp)


__all__ = [
    "LLMGenerator",
    "build_sft_prompt",
    "parse_sft_response",
]