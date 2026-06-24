"""validator — Stage 2 8-dim dict check + 5-turn cap (per FR-012).

Reuses param_ops.validate_params. Additional invariants:
  - messages[0].role == "user"
  - messages length ∈ [1, 5]
  - negative=true ⇔ negative_type ∈ {reject, pivot, unsatisfiable}
  - distance alignment (LLM-side; here we just structural check)
"""

from __future__ import annotations

from typing import Optional

from ..data_model import DIM_ORDER, MessageTurn, SFTSample
from ..param_ops import validate_params


class SFTValidationError(Exception):
    pass


def validate_sft_sample(
    sample: SFTSample,
    dictionary: dict,
    *,
    max_turns: int = 5,
) -> tuple[bool, list[str]]:
    errors: list[str] = []

    # 1. params dictionary check (8 dims, 4 ops)
    ok, errs = validate_params(sample.params, dictionary)
    errors.extend(errs)

    # 2. messages invariants
    if not sample.messages:
        errors.append("messages empty")
    if sample.messages:
        if sample.messages[0].role != "user":
            errors.append(f"messages[0].role != user (got {sample.messages[0].role})")
        if not (1 <= len(sample.messages) <= max_turns):
            errors.append(f"messages length {len(sample.messages)} ∉ [1, {max_turns}]")
        for i, m in enumerate(sample.messages):
            if not m.content or len(m.content.strip()) < 1:
                errors.append(f"messages[{i}].content empty or whitespace")
            if m.role not in {"user", "assistant", "system"}:
                errors.append(f"messages[{i}].role '{m.role}' invalid")
            if "\n\n\n" in m.content:
                errors.append(f"messages[{i}].content has ≥3 consecutive newlines")
            if "\t" in m.content:
                errors.append(f"messages[{i}].content has tab")

    # 3. negative <-> negative_type
    if sample.negative:
        if sample.negative_type not in {"reject", "pivot", "unsatisfiable"}:
            errors.append(
                f"negative=true but negative_type='{sample.negative_type}' invalid"
            )
    else:
        if sample.negative_type is not None:
            errors.append(
                f"negative=false but negative_type='{sample.negative_type}' not null"
            )

    # 4. order_by must be in 5-set or null
    if sample.order_by not in {None, "distance", "price", "rating", "time"}:
        errors.append(f"order_by '{sample.order_by}' not in allowed set")

    # 5. intent must be in 5-set
    if sample.intent not in {"search_item", "use_coupon", "pay", "view_order", "browse"}:
        errors.append(f"intent '{sample.intent}' not in allowed set")

    return (len(errors) == 0, errors)


__all__ = ["validate_sft_sample", "SFTValidationError"]