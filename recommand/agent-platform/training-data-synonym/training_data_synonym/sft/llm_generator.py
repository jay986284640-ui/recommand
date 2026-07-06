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

# Field definitions injected into the prompt so the LLM understands
# the parameter schema without hardcoding it in the template.
FIELD_DEFINITIONS = """1. **category**: 核心品类（如：咖啡、火锅、烧烤、奶茶）
2. **brand**: 品牌或店名（如：星巴克、麦当劳、肯德基、喜茶）
3. **distance**: 距离要求（单位km）
4. **avg_prc**: 人均价格要求（单位元）
5. **taste**: 口味偏好（如：甜、辣、清淡、酱香）
6. **cuisine**: 菜系类型（如：川菜、粤菜、日料、西餐）
7. **occasion**: 消费场景（如：环境好、聚餐、亲子、约会、生日、节日）
8. **meal_time**: 用餐时段（如：早餐、午餐、下午茶、晚餐、夜宵）
9. **consumable_type**: 食饮类型（food / drink / mixed）"""


def build_sft_prompt(
    *,
    target_params: dict,
    target_turns: int,
    item_name: str = "",
    prompt_template: str,
) -> str:
    """Build the parameter-extraction dialogue generation prompt."""
    params_json = json.dumps(target_params, ensure_ascii=False, indent=2)

    return (
        prompt_template
        .replace("{target_params}", params_json)
        .replace("{target_turns}", str(target_turns))
        .replace("{field_definitions}", FIELD_DEFINITIONS)
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
    ) -> None:
        self._llm = llm_client
        self._template = prompt_template

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
        )
        resp = self._llm.complete(prompt, temperature=0.7, item_id=item_id)
        if not isinstance(resp, dict):
            raise ValidationError(f"LLM response not a dict: {type(resp).__name__}")
        return parse_sft_response(resp)


__all__ = [
    "LLMGenerator",
    "build_sft_prompt",
    "parse_sft_response",
    "FIELD_DEFINITIONS",
]
