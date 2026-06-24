"""consumable_mapper — Stage 1 category → consumable_type derivation.

Per FR-008c. Reads configs/consumable_type_map.yaml; default = none.
LLM fallback only when mapping fails AND category is non-null.
"""

from __future__ import annotations

from typing import Optional

from ..common.llm_client import LLMClient
from ..common.logging import get_logger
from ..data_model import TagOrigin

logger = get_logger(__name__)

VALID_VALUES = {"food", "drink", "mixed", "none"}


class ConsumableMapper:
    """Pure mapping first, LLM fallback second.

    Usage:
        mapper = ConsumableMapper(config.consumable_type_map, llm_client)
        value, origin = mapper.map(category="咖啡", item_id="mt-1", raw_record={...})
    """

    def __init__(self, mapping: dict, llm_client: Optional[LLMClient] = None) -> None:
        self._map = (mapping or {}).get("map", {}) or {}
        self._default = (mapping or {}).get("default", "none") or "none"
        self._coupon_text_hints = (mapping or {}).get("coupon_text_hints", {}) or {}
        self._llm = llm_client
        # Build reverse index: category → consumable_type
        self._category_to_type: dict[str, str] = {}
        for ct, cats in self._map.items():
            for c in cats:
                self._category_to_type[c] = ct

    def map(
        self,
        category: Optional[str],
        *,
        item_id: str,
        raw_record: dict,
        llm_hint: str = "",
    ) -> tuple[Optional[str], TagOrigin]:
        """Return (value, origin).

        Order of operations (per FR-008c):
          1. category lookup in map → derived
          2. coupon_text_hints on raw_record (couponName / productDesc) → derived
          3. LLM fallback if available → ai
          4. default ('none')
        """
        # 1. category lookup
        if category and category in self._category_to_type:
            ct = self._category_to_type[category]
            return (ct, TagOrigin.DERIVED)

        # 2. coupon text hints
        text = self._extract_text(raw_record)
        if text and self._llm is None:  # when no LLM available, use deterministic hints
            hit = self._match_text_hints(text)
            if hit:
                return (hit, TagOrigin.DERIVED)

        # 3. LLM fallback
        if self._llm is not None and (category or text):
            try:
                prompt = (
                    f"你是消费类型判定助手。基于商品描述,给出 food / drink / mixed / none 之一。\n"
                    f"category={category or 'null'}\n"
                    f"text={text[:120]}\n"
                    f"严格 JSON: {{\"consumable_type\": \"<one of food|drink|mixed|none>\"}}"
                )
                resp = self._llm.complete(prompt, temperature=0.1)
                val = resp.get("consumable_type") if isinstance(resp, dict) else None
                if val in VALID_VALUES:
                    return (val, TagOrigin.AI)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "consumable_mapper_llm_failed",
                    extra={"stage": "enrich", "item_id": item_id, "event": "llm_fallback_fail", "error": str(e)},
                )

        # 4. default
        return (self._default if self._default in VALID_VALUES else "none", TagOrigin.DERIVED)

    def _extract_text(self, raw: dict) -> str:
        return " ".join(
            str(raw.get(k) or "")
            for k in ("couponName", "productDesc", "ruleDescription", "Str_Nm", "shopName", "Brnd_Nm")
        )

    def _match_text_hints(self, text: str) -> Optional[str]:
        lower = text.lower()
        # Score each type by how many of its hint words appear
        best, best_score = None, 0
        for ct, hints in self._coupon_text_hints.items():
            score = sum(1 for h in hints if h in text or h in lower)
            if score > best_score:
                best, best_score = ct, score
        return best if best_score > 0 else None


__all__ = ["ConsumableMapper", "VALID_VALUES"]