"""distance_sampler — Stage 2 dict sampling for `params.distance` + `order_by`.

Per FR-013b. Decoupled from lng/lat. Coupled probabilities:
  - params.distance non-null → P(order_by=distance) ≥ 0.60
  - params.distance null     → P(order_by=distance) ≤ 0.05
"""

from __future__ import annotations

import random
from typing import Optional

from ..common.logging import get_logger
from ..param_ops import IMPLEMENTED_OPS

logger = get_logger(__name__)

# Defaults aligned with configs/pipeline.yaml `sft.distance_sampling`
DEFAULT_DISTANCE_BUCKETS = ["0-500", "500-1000", "1000-3000", "3000+"]
DEFAULT_ORDER_BY_VALUES = ["distance", "price", "rating", "time", None]  # null = no order
NEGATIVE_OP = "not_in"


class DistanceSampler:
    def __init__(
        self,
        rng: random.Random,
        *,
        distance_param_ratio: float = 0.30,
        distance_bucket_weights: list[float] | None = None,
        order_by_distribution: list[float] | None = None,
        order_by_distance_when_param_present: float = 0.60,
        order_by_distance_when_param_null: float = 0.05,
    ) -> None:
        self._rng = rng
        self._ratio = distance_param_ratio
        self._buckets = DEFAULT_DISTANCE_BUCKETS
        self._bucket_weights = distance_bucket_weights or [0.25] * 4
        self._order_by_dist = order_by_distribution or [0.30, 0.20, 0.15, 0.10, 0.25]
        self._order_by_distance_when_present = order_by_distance_when_param_present
        self._order_by_distance_when_null = order_by_distance_when_param_null

    def sample_distance_param(
        self, *, is_negative: bool = False
    ) -> Optional[dict]:
        """Return `{op, values}` dict or None if param is null this sample."""
        if self._rng.random() > self._ratio:
            return None
        bucket = self._weighted_choice(self._buckets, self._bucket_weights)
        if is_negative:
            # negative: distance NOT in this bucket (e.g. 'don't want too far')
            return {"op": NEGATIVE_OP, "values": [bucket]}
        return {"op": "in", "values": [bucket]}

    def sample_order_by(self, *, distance_param: Optional[dict]) -> Optional[str]:
        """Pick order_by with coupling to distance_param."""
        # _order_by_dist holds weights parallel to DEFAULT_ORDER_BY_VALUES:
        # ["distance", "price", "rating", "time", None]  (None = no order)
        weights = list(self._order_by_dist)
        distance_idx = DEFAULT_ORDER_BY_VALUES.index("distance")
        if distance_param is not None:
            # Force P(distance) ≥ threshold
            target = self._order_by_distance_when_present
            if weights[distance_idx] < target:
                # Reallocate from other buckets
                delta = target - weights[distance_idx]
                for i, w in enumerate(weights):
                    if i != distance_idx and w > 0:
                        take = min(w, delta)
                        weights[i] -= take
                        delta -= take
                        if delta <= 0:
                            break
                weights[distance_idx] = target
        else:
            # Cap P(distance) ≤ threshold
            target = self._order_by_distance_when_null
            if weights[distance_idx] > target:
                surplus = weights[distance_idx] - target
                weights[distance_idx] = target
                # Distribute surplus proportionally to other buckets
                other_indices = [i for i, w in enumerate(weights) if i != distance_idx and w > 0]
                other_total = sum(weights[i] for i in other_indices) or 1
                for i in other_indices:
                    weights[i] += surplus * (weights[i] / other_total)
        return self._weighted_choice(DEFAULT_ORDER_BY_VALUES, weights)

    def _weighted_choice(self, choices: list, weights: list[float]):
        total = sum(weights)
        if total <= 0:
            return self._rng.choice(choices)
        # renormalize
        w = [w_ / total for w_ in weights]
        cum = 0.0
        r = self._rng.random()
        for choice, weight in zip(choices, w):
            cum += weight
            if r <= cum:
                return choice
        return choices[-1]


__all__ = ["DistanceSampler", "DEFAULT_DISTANCE_BUCKETS", "DEFAULT_ORDER_BY_VALUES"]