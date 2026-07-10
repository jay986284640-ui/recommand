"""llm_generator — Stage 3: parameter-extraction dialogue generator.

Generates natural multi-turn user conversations whose semantics correspond
to given target params. The LLM returns {messages, guide_text}.
"""

from __future__ import annotations

import json
from typing import Optional

from ..common.exceptions import ValidationError
from ..common.llm_client import LLMClient
from ..common.logging import get_logger
from ..data_model import MessageTurn

logger = get_logger(__name__)


def build_field_definitions(dim_dictionary: dict, passthrough_fields: list[str]) -> str:
    """Build field definition text dynamically from dictionary + passthrough columns.

    Args:
        dim_dictionary: The ``dim_dictionary_snapshot.yaml`` content.
        passthrough_fields: Column names from ``tables.yaml`` to pass through
            (e.g. ``["distance", "avg_prc"]``).

    Returns:
        Multi-line numbered field definition string for the SFT prompt.
    """
    lines: list[str] = []
    idx = 1

    for dim_name, dim_info in dim_dictionary.items():
        if dim_name.startswith("_"):
            continue
        desc = dim_info.get("desc", dim_name) if isinstance(dim_info, dict) else dim_name
        vals = dim_info.get("values", []) if isinstance(dim_info, dict) else []
        examples = ", ".join(str(v) for v in vals[:8])
        lines.append(f"{idx}. **{dim_name}**: {desc}（如：{examples}）")
        idx += 1

    for col in passthrough_fields:
        if col == "distance":
            lines.append(f"{idx}. **distance**: 距离要求（单位km，如：0-500, 500-1000）")
        elif col == "avg_prc":
            lines.append(f"{idx}. **avg_prc**: 人均价格要求（单位元）")
        elif col == "store_name":
            lines.append(f"{idx}. **store_name**: 门店名称模糊搜索（兜底检索字段，用户可能只记得部分店名）")
        idx += 1

    return "\n".join(lines)


def build_sft_prompt(
    *,
    target_params: dict,
    target_turns: int,
    item_name: str = "",
    prompt_template: str,
    field_definitions: str,
) -> str:
    """Build the parameter-extraction dialogue generation prompt."""
    params_json = json.dumps(target_params, ensure_ascii=False, indent=2)

    return (
        prompt_template
        .replace("{target_params}", params_json)
        .replace("{target_turns}", str(target_turns))
        .replace("{field_definitions}", field_definitions)
    )


def parse_sft_response(payload: dict) -> tuple[list[MessageTurn], str]:
    """Parse LLM JSON → (messages, guide_text)."""
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

    guide_text = str(payload.get("guide_text", "") or "")

    return messages, guide_text


class LLMGenerator:
    def __init__(
        self,
        llm_client: LLMClient,
        prompt_template: str,
        field_definitions: str = "",
    ) -> None:
        self._llm = llm_client
        self._template = prompt_template
        self._field_definitions = field_definitions

    @property
    def model_name(self) -> str:
        return self._llm.model_name

    def generate(
        self,
        *,
        target_params: dict,
        target_turns: int,
        item_name: str = "",
        item_id: str = "",
    ) -> tuple[list[MessageTurn], str]:
        """Generate a dialogue + guide_text for the given target params."""
        prompt = build_sft_prompt(
            target_params=target_params,
            target_turns=target_turns,
            item_name=item_name,
            prompt_template=self._template,
            field_definitions=self._field_definitions,
        )
        resp = self._llm.complete(prompt, temperature=0.7, item_id=item_id)
        if not isinstance(resp, dict):
            raise ValidationError(f"LLM response not a dict: {type(resp).__name__}")
        return parse_sft_response(resp)


__all__ = [
    "LLMGenerator",
    "build_sft_prompt",
    "build_field_definitions",
    "parse_sft_response",
]
