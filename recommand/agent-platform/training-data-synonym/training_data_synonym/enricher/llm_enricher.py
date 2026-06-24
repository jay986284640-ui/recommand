"""llm_enricher — Stage 1 6-dim LLM fallback (per FR-005/007).

Reads configs/prompts/enrichment_v1.txt, injects dictionary subset + raw_record.
Retries 2x on JSONDecodeError / Timeout; failure → null + write to failures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..common.exceptions import ValidationError
from ..common.llm_client import LLMClient, LLMTimeoutError, validate_complete_response
from ..common.logging import get_logger
from ..data_model import TagOrigin

logger = get_logger(__name__)

ENRICHABLE_DIMS = ("category", "merchant", "avg_prc", "age", "occasion", "taste")


def build_enrichment_prompt(
    raw_record: dict, dictionary: dict, prompt_template: str
) -> str:
    """Inject dictionary subsets + raw_record into the prompt template."""
    dim_lines = []
    for dim in ENRICHABLE_DIMS:
        values = (dictionary.get(dim) or {}).get("values", []) or []
        dim_lines.append(f"- {dim}: {values}")
    dict_block = "\n".join(dim_lines)
    raw_json = json.dumps(raw_record, ensure_ascii=False, default=str)
    return (
        prompt_template
        .replace("{raw_record}", raw_json)
        + "\n\n" + "候选字典(注入 6 维各自值):\n" + dict_block
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
    ) -> None:
        self._llm = llm_client
        self._dict = dictionary
        self._template = prompt_template

    def enrich(self, raw_record: dict, *, item_id: str = "") -> dict[str, Any]:
        """Return {dim: value_or_None, ...}. None for failed dims."""
        prompt = build_enrichment_prompt(raw_record, self._dict, self._template)
        try:
            resp = self._llm.complete(prompt, temperature=0.3)
            validate_complete_response(resp)
            parsed = parse_enrichment_response(resp)
            # Filter by dictionary candidate set
            return self._constrain_to_dict(parsed)
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

    def _constrain_to_dict(self, parsed: dict) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for dim in ENRICHABLE_DIMS:
            v = parsed.get(dim, None)
            if v is None:
                out[dim] = None
                continue
            allowed = (self._dict.get(dim) or {}).get("values", []) or []
            if dim == "taste":
                ok = [x for x in v if x in allowed]
                out[dim] = ok if ok else None
            else:
                if v in allowed:
                    out[dim] = v
                else:
                    out[dim] = None
        return out


__all__ = [
    "LLMEnricher",
    "build_enrichment_prompt",
    "parse_enrichment_response",
    "ENRICHABLE_DIMS",
]