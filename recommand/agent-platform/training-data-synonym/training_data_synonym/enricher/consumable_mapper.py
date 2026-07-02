"""consumable_mapper — Stage 1 category → consumable_type derivation.

Per FR-008c. Reads configs/consumable_type_map.yaml; default = none.
LLM fallback only when mapping fails AND category is non-null.

v2.5 fallback: when ``category`` is None/empty AND product name contains a
category keyword (``咖啡``, ``快餐`` …), :mod:`name_inference` infers the
category from the name and re-tries the mapping.
"""

from __future__ import annotations

from typing import Optional

from ..common.llm_client import LLMClient
from ..common.logging import get_logger
from ..data_model import TagOrigin
from .name_inference import (
    get_product_name,
    infer_category,
    is_rule_text,
)

logger = get_logger(__name__)

VALID_VALUES = {"food", "drink", "mixed", "none"}


class ConsumableMapper:
    """Pure mapping first, LLM fallback second.

    Usage:
        mapper = ConsumableMapper(config.consumable_type_map, llm_client)
        value, origin = mapper.map(category="咖啡", item_id="mt-1", raw_record={...})
    """

    def __init__(
        self,
        mapping: dict,
        llm_client: Optional[LLMClient] = None,
        category_values: Optional[list[str]] = None,
    ) -> None:
        self._map = (mapping or {}).get("map", {}) or {}
        self._default = (mapping or {}).get("default", "none") or "none"
        self._coupon_text_hints = (mapping or {}).get("coupon_text_hints", {}) or {}
        self._llm = llm_client
        # v2.5: for name-based category fallback when raw Cat_Nm is empty.
        # Inject ``category_values`` (from dim_dictionary.category.values).
        self._category_values = category_values or []
        # Build reverse index: category → consumable_type
        self._category_to_type: dict[str, str] = {}
        for ct, cats in self._map.items():
            for c in cats:
                self._category_to_type[c] = ct
        # Part B: observability for silent dict rejections.
        self.rejection_count: int = 0
        # v2.5: name-based category fallback observability.
        self.inferred_count: int = 0

    def map(
        self,
        category: Optional[str],
        *,
        item_id: str,
        raw_record: dict,
        llm_hint: str = "",
    ) -> tuple[Optional[str], TagOrigin]:
        """Return (value, origin).

        Order of operations (per FR-008c + v2.5):
          1. category lookup in map → derived
          2. **v2.5**: if category missing AND product name has a category
             keyword (and name is not rule prose), use inferred category
             → derived
          3. coupon_text_hints on raw_record (couponName / productDesc) → derived
          4. LLM fallback if available → ai
          5. default ('none')
        """
        # 1. category lookup
        if category and category in self._category_to_type:
            ct = self._category_to_type[category]
            return (ct, TagOrigin.DERIVED)

        # 2. v2.5: name-inference fallback for empty category.
        # Rule prose (满50减10, 代金券, 限时抢购) suppresses inference.
        name = get_product_name(raw_record)
        name_is_rule = is_rule_text(name)
        if (not category) and not name_is_rule and self._category_values and name:
            inferred_cat = infer_category(name, self._category_values)
            if inferred_cat and inferred_cat in self._category_to_type:
                self.inferred_count += 1
                logger.info(
                    "name_inferred_category",
                    extra={
                        "stage": "enrich",
                        "item_id": item_id,
                        "event": "name_inference_fallback",
                        "dim": "category",
                        "value": inferred_cat,
                        "source_name": name,
                    },
                )
                ct = self._category_to_type[inferred_cat]
                return (ct, TagOrigin.DERIVED)

        # 3. coupon text hints (also suppressed for rule-text names — rule prose
        # shouldn't trigger heuristic brand/category matches).
        text = self._extract_text(raw_record)
        if text and self._llm is None and not name_is_rule:
            hit = self._match_text_hints(text)
            if hit:
                return (hit, TagOrigin.DERIVED)

        # 4. LLM fallback
        if self._llm is not None and (category or text):
            try:
                prompt = (
                    f"你是消费类型判定助手。基于商品描述,给出 food / drink / mixed / none 之一。\n"
                    f"category={category or 'null'}\n"
                    f"text={text[:120]}\n"
                    f"严格 JSON: {{\"consumable_type\": \"<one of food|drink|mixed|none>\"}}"
                )
                resp = self._llm.complete(prompt, temperature=0.1, item_id=item_id)
                val = resp.get("consumable_type") if isinstance(resp, dict) else None
                if val in VALID_VALUES:
                    return (val, TagOrigin.AI)
                if val is not None:
                    # Part B: out-of-vocab consumable_type — silent reject + observe.
                    self.rejection_count += 1
                    logger.warning(
                        "consumable_type_rejected",
                        extra={
                            "stage": "enrich",
                            "item_id": item_id,
                            "event": "dict_rejection",
                            "dim": "consumable_type",
                            "rejected_value": val,
                            "allowed_values": sorted(VALID_VALUES),
                        },
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "consumable_mapper_llm_failed",
                    extra={"stage": "enrich", "item_id": item_id, "event": "llm_fallback_fail", "error": str(e)},
                )

        # 5. default
        return (self._default if self._default in VALID_VALUES else "none", TagOrigin.DERIVED)

    def _extract_text(self, raw: dict) -> str:
        return " ".join(
            str(raw.get(k) or "")
            for k in ("couponname", "productdesc", "ruledescription", "str_nm", "shopname", "brnd_nm")
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