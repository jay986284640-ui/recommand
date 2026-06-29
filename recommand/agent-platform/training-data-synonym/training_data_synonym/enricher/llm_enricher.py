"""llm_enricher — Stage 1 6-dim LLM fallback (per FR-005/007).

Reads configs/prompts/enrichment_v1.txt, injects dictionary subset + raw_record.
Retries 2x on JSONDecodeError / Timeout; failure → null + write to failures.

v2.5 fallback path: when raw brand/category/taste/occasion fields are empty
or contain rule prose, ``compute_name_hints`` extracts hints from the product
name (``Str_Nm`` / ``shopName`` / ``couponName``). Hints are passed to the LLM
prompt + used as fallback if the LLM returns None.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ..common.exceptions import ValidationError
from ..common.llm_client import LLMClient, LLMTimeoutError, validate_complete_response
from ..common.logging import get_logger
from ..data_model import TagOrigin
from .name_inference import compute_name_hints

logger = get_logger(__name__)

# avg_prc/distance 不走 LLM,仅从表字段桶化/几何计算
ENRICHABLE_DIMS = ("category", "merchant", "age", "occasion", "taste")


def build_enrichment_prompt(
    raw_record: dict,
    dictionary: dict,
    prompt_template: str,
    *,
    name_hints: Optional[dict] = None,
) -> str:
    """Inject dictionary subsets + raw_record + optional name hints.

    ``name_hints`` (v2.5) is the output of :func:`compute_name_hints` — keys
    are dim names from :data:`ENRICHABLE_DIMS`, values are inferred strings.
    They're rendered as a "提示:" block so the LLM sees the inferred values
    alongside the raw record (better context than raw alone).
    """
    dim_lines = []
    for dim in ENRICHABLE_DIMS:
        values = (dictionary.get(dim) or {}).get("values", []) or []
        dim_lines.append(f"- {dim}: {values}")
    dict_block = "\n".join(dim_lines)
    raw_json = json.dumps(raw_record, ensure_ascii=False, default=str)

    hint_block = ""
    if name_hints:
        non_null = {k: v for k, v in name_hints.items() if v}
        if non_null:
            hint_json = json.dumps(non_null, ensure_ascii=False)
            hint_block = (
                "\n\n提示(v2.5 名称推断,仅作参考;若与字段冲突以字段为准):\n"
                + hint_json
            )
    return (
        prompt_template
        .replace("{raw_record}", raw_json)
        + "\n\n" + "候选字典(注入 6 维各自值):\n" + dict_block
        + hint_block
    )


def parse_enrichment_response(payload: dict) -> dict[str, Any]:
    """Map LLM JSON → 6-dim dict; reject unknown fields, drop null fields."""
    if not isinstance(payload, dict):
        raise ValidationError("LLM response not a dict")
    out: dict[str, Any] = {}
    for k in ENRICHABLE_DIMS:
        v = payload.get(k, None)
        if v is None:
            continue
        if k == "taste":
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                out[k] = v
            elif isinstance(v, str):
                out[k] = [v]
            # else: drop
        else:
            if isinstance(v, str):
                out[k] = v
            # else: drop
    return out


class LLMEnricher:
    """6-dim LLM fallback; failures → dict with `null` for the failing dim."""

    def __init__(
        self,
        llm_client: LLMClient,
        dictionary: dict,
        prompt_template: str,
        brand_values: Optional[list[str]] = None,
    ) -> None:
        """``brand_values`` defaults to ``dictionary['merchant']['values']``;
        pass an explicit list when brand dictionary is separate (e.g. from
        ``configs/brand_dictionary.yaml``).
        """
        self._llm = llm_client
        self._dict = dictionary
        self._template = prompt_template
        self._brand_values = (
            brand_values
            if brand_values is not None
            else (dictionary.get("merchant") or {}).get("values", []) or []
        )
        # Part B: observability for silent dict rejections.
        self.rejection_count: int = 0
        self.rejection_log: list[dict[str, Any]] = []
        # Part C (v2.5): observability for name-inference fallback usage.
        self.inferred_used_count: int = 0
        self.inferred_log: list[dict[str, Any]] = []

    def enrich(self, raw_record: dict, *, item_id: str = "") -> dict[str, Any]:
        """Return {dim: value_or_None, ...}. None for failed dims.

        v2.5 fallback: if LLM returns None for a dim AND ``compute_name_hints``
        produced a non-empty value, use the inferred value. Tracked in
        ``inferred_used_count`` + ``inferred_log``.
        """
        name_hints = compute_name_hints(
            raw_record, self._dict, self._brand_values
        )
        prompt = build_enrichment_prompt(
            raw_record, self._dict, self._template, name_hints=name_hints
        )
        try:
            resp = self._llm.complete(prompt, temperature=0.3, item_id=item_id)
            validate_complete_response(resp)
            parsed = parse_enrichment_response(resp)
            # v2.5 fallback: apply name hints when LLM returned None
            self._apply_name_fallback(parsed, name_hints, item_id=item_id)
            # Filter by dictionary candidate set
            return self._constrain_to_dict(parsed, item_id=item_id)
        except (LLMTimeoutError, json.JSONDecodeError, ValidationError) as e:
            logger.warning(
                "enrich_llm_failed",
                extra={
                    "stage": "enrich",
                    "item_id": item_id,
                    "event": "llm_fallback_fail",
                    "error": str(e),
                },
            )
            return {dim: None for dim in ENRICHABLE_DIMS}

    def _apply_name_fallback(
        self,
        parsed: dict,
        hints: dict,
        *,
        item_id: str = "",
    ) -> None:
        """Substitute None values in parsed with non-empty hints.

        Records which dims used the fallback in ``self.inferred_log`` /
        ``self.inferred_used_count`` so the pipeline can surface this signal
        (similar to ``rejection_count``).
        """
        for dim, hint in (hints or {}).items():
            if dim not in ENRICHABLE_DIMS:
                continue
            if parsed.get(dim) is None and hint:
                parsed[dim] = hint
                self.inferred_used_count += 1
                self.inferred_log.append(
                    {
                        "item_id": item_id,
                        "dim": dim,
                        "value": hint,
                    }
                )
                logger.info(
                    "name_hint_used",
                    extra={
                        "stage": "enrich",
                        "item_id": item_id,
                        "event": "name_inference_fallback",
                        "dim": dim,
                        "value": hint,
                    },
                )
        # Cap the log
        if len(self.inferred_log) > 1000:
            self.inferred_log = self.inferred_log[-1000:]

    def _constrain_to_dict(
        self, parsed: dict, *, item_id: str = ""
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for dim in ENRICHABLE_DIMS:
            v = parsed.get(dim, None)
            if v is None:
                out[dim] = None
                continue
            allowed = (self._dict.get(dim) or {}).get("values", []) or []
            if dim == "taste":
                kept = [x for x in v if x in allowed]
                dropped = [x for x in v if x not in allowed]
                if dropped:
                    self._record_rejection(item_id, dim, dropped, allowed)
                out[dim] = kept if kept else None
            else:
                if v in allowed:
                    out[dim] = v
                else:
                    self._record_rejection(item_id, dim, [v], allowed)
                    out[dim] = None
        return out

    def _record_rejection(
        self,
        item_id: str,
        dim: str,
        rejected_values: list,
        allowed: list,
    ) -> None:
        """Record a silent dict rejection: increment counter, append to log,
        and emit a structured warning. The dim is still set to None by the
        caller — rejection is observable, not blocking."""
        self.rejection_count += 1
        entry = {
            "item_id": item_id,
            "dim": dim,
            "rejected_values": list(rejected_values),
            "allowed_count": len(allowed),
        }
        self.rejection_log.append(entry)
        # Cap the log so a long run doesn't grow unbounded.
        if len(self.rejection_log) > 1000:
            self.rejection_log = self.rejection_log[-1000:]
        logger.warning(
            "dict_rejected",
            extra={
                "stage": "enrich",
                "item_id": item_id,
                "event": "dict_rejection",
                "dim": dim,
                "rejected_values": list(rejected_values),
                "allowed_count": len(allowed),
            },
        )


__all__ = [
    "LLMEnricher",
    "build_enrichment_prompt",
    "parse_enrichment_response",
    "ENRICHABLE_DIMS",
]