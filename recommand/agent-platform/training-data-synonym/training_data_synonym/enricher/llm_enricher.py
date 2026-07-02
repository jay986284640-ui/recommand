"""llm_enricher — LLM tag inference, config-driven.

Reads ``_meta.llm_inference`` from ``configs/tables.yaml`` to determine
which fields the LLM should infer. No hard-coded field list.
"""
from __future__ import annotations

import json
from typing import Any

from ..common.exceptions import ValidationError
from ..common.llm_client import LLMClient, LLMTimeoutError, validate_complete_response
from ..common.logging import get_logger
from .name_inference import compute_name_hints

logger = get_logger(__name__)


def build_enrichment_prompt(
    raw_record: dict,
    inference_config: list[dict],
    prompt_template: str,
    *,
    name_hints: dict | None = None,
    include_candidates: bool = True,
    dictionary: dict | None = None,
) -> str:
    """Build prompt from config: field names, descriptions, types.

    ``inference_config`` is the ``_meta.llm_inference`` list from tables.yaml.
    Each entry: ``{field, desc, multiple}``.
    """
    raw_json = json.dumps(raw_record, ensure_ascii=False, default=str)

    # Build JSON schema section for LLM
    json_lines = []
    for item in inference_config:
        fld = item["field"]
        desc = item.get("desc", "")
        multi = item.get("multiple", False)
        type_hint = f'["<{desc}>", ...]' if multi else f'"<{desc}>"'
        json_lines.append(f'  "{fld}": {type_hint},')

    struct_block = "{\n" + "\n".join(json_lines) + "\n}"

    # Dictionary candidates block (Stage 2 / constrained mode)
    dict_block = ""
    if include_candidates and dictionary:
        dim_lines = []
        for item in inference_config:
            f = item["field"]
            vals = (dictionary.get(f) or {}).get("values", []) or []
            dim_lines.append(f"- {f}: {vals}")
        dict_block = (
            "\n\n候选字典(请严格从中选取):\n"
            + "\n".join(dim_lines)
            + "\n要求:严格 JSON,不写字典外值;不知道的填 null。"
        )

    hint_block = ""
    if name_hints:
        non_null = {k: v for k, v in name_hints.items() if v}
        if non_null:
            hint_json = json.dumps(non_null, ensure_ascii=False)
            hint_block = "\n\n提示(从商品名称推断,仅作参考):\n" + hint_json

    return (
        prompt_template
        .replace("{raw_record}", raw_json)
        .replace("{fields_schema}", struct_block)
        + dict_block
        + hint_block
    )


def parse_enrichment_response(
    payload: dict, inference_config: list[dict]
) -> dict[str, Any]:
    """Extract configured fields from LLM JSON response."""
    if not isinstance(payload, dict):
        raise ValidationError("LLM response not a dict")
    out: dict[str, Any] = {}
    for item in inference_config:
        f = item["field"]
        v = payload.get(f)
        if v is None:
            continue
        if item.get("multiple"):
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                out[f] = v
            elif isinstance(v, str):
                out[f] = [v]
        else:
            if isinstance(v, str):
                out[f] = v
    return out


class LLMEnricher:
    """LLM enricher driven by ``_meta.llm_inference`` config."""

    def __init__(
        self,
        llm_client: LLMClient,
        inference_config: list[dict],
        dictionary: dict,
        prompt_template: str,
        brand_values: list[str] | None = None,
        *,
        constrain_to_dict: bool = True,
    ) -> None:
        self._llm = llm_client
        self._config = inference_config
        self._fields = [c["field"] for c in inference_config]
        self._dict = dictionary
        self._template = prompt_template
        self._constrain = constrain_to_dict
        self._brand_values = brand_values or (
            dictionary.get("merchant") or {}
        ).get("values", []) or []

        self.rejection_count: int = 0
        self.rejection_log: list[dict[str, Any]] = []
        self.inferred_used_count: int = 0
        self.inferred_log: list[dict[str, Any]] = []

    def enrich(self, raw_record: dict, *, item_id: str = "") -> dict[str, Any]:
        name_hints = compute_name_hints(raw_record, self._dict, self._brand_values)
        prompt = build_enrichment_prompt(
            raw_record, self._config, self._template,
            name_hints=name_hints,
            include_candidates=self._constrain,
            dictionary=self._dict,
        )
        try:
            resp = self._llm.complete(prompt, temperature=0.3, item_id=item_id)
            validate_complete_response(resp)
            parsed = parse_enrichment_response(resp, self._config)
            self._apply_name_fallback(parsed, name_hints, item_id)
            if self._constrain:
                return self._constrain_to_dict(parsed, item_id)
            return {f: parsed.get(f) for f in self._fields}
        except (LLMTimeoutError, json.JSONDecodeError, ValidationError) as e:
            logger.warning("enrich_llm_failed", extra={
                "stage": "enrich", "item_id": item_id, "event": "llm_fallback_fail", "error": str(e),
            })
            return {f: None for f in self._fields}

    def _apply_name_fallback(self, parsed: dict, hints: dict, item_id: str = "") -> None:
        for dim, hint in (hints or {}).items():
            if dim not in self._fields:
                continue
            if parsed.get(dim) is None and hint:
                parsed[dim] = hint
                self.inferred_used_count += 1
                self.inferred_log.append({"item_id": item_id, "dim": dim, "value": hint})
                logger.info("name_hint_used", extra={
                    "stage": "enrich", "item_id": item_id,
                    "event": "name_inference_fallback", "dim": dim, "value": hint,
                })
        if len(self.inferred_log) > 1000:
            self.inferred_log = self.inferred_log[-1000:]

    def _constrain_to_dict(self, parsed: dict, item_id: str = "") -> dict[str, Any]:
        out: dict[str, Any] = {}
        for item in self._config:
            f = item["field"]
            v = parsed.get(f)
            if v is None:
                out[f] = None
                continue
            allowed = (self._dict.get(f) or {}).get("values", []) or []
            if item.get("multiple"):
                kept = [x for x in v if x in allowed]
                dropped = [x for x in v if x not in allowed]
                if dropped:
                    self._record_rejection(item_id, f, dropped, allowed)
                out[f] = kept if kept else None
            else:
                if v in allowed:
                    out[f] = v
                else:
                    self._record_rejection(item_id, f, [v], allowed)
                    out[f] = None
        return out

    def _record_rejection(self, item_id: str, dim: str, rejected: list, allowed: list) -> None:
        self.rejection_count += 1
        self.rejection_log.append({
            "item_id": item_id, "dim": dim,
            "rejected_values": list(rejected), "allowed_count": len(allowed),
        })
        if len(self.rejection_log) > 1000:
            self.rejection_log = self.rejection_log[-1000:]
        logger.warning("dict_rejected", extra={
            "stage": "enrich", "item_id": item_id, "event": "dict_rejection",
            "dim": dim, "rejected_values": list(rejected), "allowed_count": len(allowed),
        })


__all__ = ["LLMEnricher", "build_enrichment_prompt", "parse_enrichment_response"]
