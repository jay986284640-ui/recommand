"""ParamSpec dataclass + 7-step dictionary validator.

Per data-model.md §实体 6 + contracts/param_op_types_v2.md.

Validator rules:
  1. field name in 8 dim whitelist
  2. missing fields → null-pad (not error)
  3. op in implemented set (eq / in / contains / not_in)
  4. op applicable to dim
  5. values type matches op
  6. values are in dictionary candidate set
  7. in / contains / not_in values non-empty
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .data_model import DIM_ORDER

# op ↔ dim mapping per contracts/param_op_types_v2.md
OP_BY_DIM: dict[str, set[str]] = {
    "category": {"in"},
    "consumable_type": {"eq"},
    "brand": {"in"},
    "avg_prc": {"in"},
    "distance": {"in", "not contains"},
    "age": {"in"},
    "occasion": {"in"},
    "taste": {"contains", "not contains"},
}

IMPLEMENTED_OPS: set[str] = {"eq", "in", "contains", "not contains"}
RESERVED_OPS: set[str] = {"gt", "lt", "between"}  # rejected by validator


@dataclass
class ParamSpec:
    op: str
    values: Any  # str for eq; List[str] for in / contains / not_in

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, "values": self.values}


# --- T013: 7-step validator ----------------------------------------------


def validate_params(
    params: dict[str, Any], dictionary: dict[str, dict[str, Any]]
) -> tuple[bool, list[str]]:
    """Return (ok, errors). errors is a list of human-readable strings.

    dictionary shape: {dim: {"values": [candidates], "op": default_op}}
    """
    errors: list[str] = []

    # 1. field whitelist (8 dims)
    for k in list(params.keys()):
        if k not in DIM_ORDER:
            errors.append(f"unexpected field: {k}")
            params.pop(k, None)

    # 2. missing fields → null pad
    for k in DIM_ORDER:
        params.setdefault(k, None)

    # 3. op whitelist
    for dim, spec in params.items():
        if spec is None:
            continue
        op = spec.get("op") if isinstance(spec, dict) else getattr(spec, "op", None)
        if op is None or op not in IMPLEMENTED_OPS:
            errors.append(f"{dim}.op '{op}' not in implemented set")

    # 4. op ↔ dim
    for dim, spec in params.items():
        if spec is None:
            continue
        op = spec.get("op") if isinstance(spec, dict) else getattr(spec, "op", None)
        if op not in OP_BY_DIM.get(dim, set()):
            errors.append(f"{dim}.op '{op}' not allowed for this dim")

    # 5. values type ↔ op
    for dim, spec in params.items():
        if spec is None:
            continue
        if isinstance(spec, dict):
            op, v = spec.get("op"), spec.get("values")
        else:
            op, v = spec.op, spec.values
        if op == "eq":
            if not isinstance(v, str):
                errors.append(f"{dim}.values must be str for op=eq")
        elif op in {"in", "contains", "not contains"}:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                errors.append(f"{dim}.values must be array<string> for op={op}")
            elif len(v) == 0:
                errors.append(f"{dim}.values empty array")

    # 6. dictionary membership
    for dim, spec in params.items():
        if spec is None:
            continue
        if isinstance(spec, dict):
            op, v = spec.get("op"), spec.get("values")
        else:
            op, v = spec.op, spec.values
        if v is None or op not in IMPLEMENTED_OPS:
            continue
        allowed_values = set((dictionary.get(dim) or {}).get("values", []) or [])
        if not allowed_values:
            continue
        if op == "eq":
            if v not in allowed_values:
                errors.append(f"{dim}.values '{v}' not in dictionary")
        else:
            for item in v or []:
                if item not in allowed_values:
                    errors.append(f"{dim}.values[{item}] not in dictionary")

    return (len(errors) == 0, errors)