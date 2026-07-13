"""intent_assigner — Stage 2 5-intent + item_type bias (per FR-015/016).

5 intents: search_item / use_coupon / pay / view_order / browse.
Each intent ≥ 3% of total (SC-006 lower bound).
Item-type bias from configs/intent_keywords.yaml.
"""

from __future__ import annotations

import random
from collections import Counter

from ..common.logging import get_logger
from ..data_model import Role

logger = get_logger(__name__)

INTENTS = ["search_item", "use_coupon", "pay", "view_order", "browse"]


class IntentAssigner:
    def __init__(
        self,
        rng: random.Random,
        intent_config: dict | None = None,
    ) -> None:
        self._rng = rng
        self._intents = INTENT_CONFIG if intent_config is None else intent_config
        # global counter for distribution analysis
        self._counter: Counter = Counter()

    def assign(self, item_type: Role, *, count_per_item: int) -> list[str]:
        """Assign `count_per_item` intents to one item, biased by item_type."""
        bias = self._intents.get("item_type_bias", {}).get(item_type.value, ["search_item"])
        weights = self._intents.get("intents", {})
        # Build per-item intent distribution
        per_item: list[str] = []
        for _ in range(count_per_item):
            # 70% from biased set, 30% from any
            if self._rng.random() < 0.70 and bias:
                intent = self._rng.choice(bias)
            else:
                intent = self._weighted_intent(weights)
            per_item.append(intent)
            self._counter[intent] += 1
        return per_item

    def _weighted_intent(self, weights: dict) -> str:
        if not weights:
            return self._rng.choice(INTENTS)
        names = list(weights.keys())
        ws = [weights[n].get("weight", 1.0 / len(names)) for n in names]
        total = sum(ws)
        ws = [w / total for w in ws]
        r = self._rng.random()
        cum = 0.0
        for n, w in zip(names, ws):
            cum += w
            if r <= cum:
                return n
        return names[-1]

    @property
    def distribution(self) -> dict[str, int]:
        return dict(self._counter)


# Default intent config (matches configs/intent_keywords.yaml)
INTENT_CONFIG = {
    "item_type_bias": {
        "meituan_shop": ["search_item", "browse"],
        "self_shop":    ["search_item", "browse"],
        "coupon":       ["use_coupon", "pay", "search_item"],
    },
    "intents": {
        "search_item": {"weight": 0.50},
        "use_coupon":  {"weight": 0.20},
        "pay":         {"weight": 0.10},
        "view_order":  {"weight": 0.10},
        "browse":      {"weight": 0.10},
    },
}


__all__ = ["IntentAssigner", "INTENTS", "INTENT_CONFIG"]