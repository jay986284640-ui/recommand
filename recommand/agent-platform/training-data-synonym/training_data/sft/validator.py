"""validator — Stage 3 param-extraction validation.

Validates the new SFT output format: {messages, params, guide_text}.
"""

from __future__ import annotations

from ..data_model import SFTSample


class SFTValidationError(Exception):
    pass


def validate_sft_sample(
    sample: SFTSample,
    dictionary: dict,
    *,
    max_turns: int = 5,
) -> tuple[bool, list[str]]:
    errors: list[str] = []

    # 1. messages invariants
    if not sample.messages:
        errors.append("messages empty")
    if sample.messages:
        if sample.messages[0].role != "user":
            errors.append(f"messages[0].role != user (got {sample.messages[0].role})")
        if not (1 <= len(sample.messages) <= max_turns):
            errors.append(f"messages length {len(sample.messages)} not in [1, {max_turns}]")
        for i, m in enumerate(sample.messages):
            if not m.content or len(m.content.strip()) < 1:
                errors.append(f"messages[{i}].content empty or whitespace")
            if m.role not in {"user", "assistant", "system"}:
                errors.append(f"messages[{i}].role '{m.role}' invalid")

    # 2. guide_text must be a non-empty string
    if not sample.guide_text or not isinstance(sample.guide_text, str):
        errors.append("guide_text missing or empty")

    # 3. params: each value must be null or array of {op, values} objects
    if not isinstance(sample.params, dict):
        errors.append("params is not a dict")
    else:
        valid_ops = {"contains", "not_contains", "in", "not_in",
                     "gt", "gte", "lt", "lte", "between"}
        for field, val in sample.params.items():
            if val is None:
                continue
            if not isinstance(val, list):
                errors.append(f"params.{field} must be null or array, got {type(val).__name__}")
                continue
            for i, item in enumerate(val):
                if not isinstance(item, dict):
                    errors.append(f"params.{field}[{i}] not a dict")
                    continue
                op = item.get("op", "")
                if op not in valid_ops:
                    errors.append(f"params.{field}[{i}].op '{op}' not in {valid_ops}")
                vals = item.get("values")
                if not isinstance(vals, list):
                    errors.append(f"params.{field}[{i}].values not a list")

    # 4. intent
    valid_intents = {"search_item", "search_product", "use_coupon", "pay", "view_order", "browse"}
    if sample.intent not in valid_intents:
        errors.append(f"intent '{sample.intent}' not in {valid_intents}")

    return (len(errors) == 0, errors)


__all__ = ["validate_sft_sample", "SFTValidationError"]
