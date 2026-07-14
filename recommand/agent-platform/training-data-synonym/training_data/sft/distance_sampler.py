"""distance_sampler — dict sampling for ``params.distance``."""

from __future__ import annotations

import random
from typing import Optional

from ..common.logging import get_logger

logger = get_logger(__name__)

DEFAULT_DISTANCE_BUCKETS = ["0-500", "500-1000", "1000-3000", "3000+"]
NEGATIVE_OP = "not contains"


class DistanceSampler:
    def __init__(
        self,
        rng: random.Random,
        *,
        distance_param_ratio: float = 0.30,
        distance_bucket_weights: list[float] | None = None,
    ) -> None:
        self._rng = rng
        self._ratio = distance_param_ratio
        self._buckets = DEFAULT_DISTANCE_BUCKETS
        self._bucket_weights = distance_bucket_weights or [0.25] * 4

    def sample_distance_param(
        self, *, is_negative: bool = False
    ) -> Optional[dict]:
        """Return ``{op, values}`` dict or None."""
        if self._rng.random() > self._ratio:
            return None
        bucket = self._weighted_choice(self._buckets, self._bucket_weights)
        if is_negative:
            return {"op": NEGATIVE_OP, "values": [bucket]}
        return {"op": "in", "values": [bucket]}

    def _weighted_choice(self, choices: list, weights: list[float]):
        total = sum(weights)
        if total <= 0:
            return self._rng.choice(choices)
        w = [w_ / total for w_ in weights]
        cum = 0.0
        r = self._rng.random()
        for choice, weight in zip(choices, w):
            cum += weight
            if r <= cum:
                return choice
        return choices[-1]


__all__ = ["DistanceSampler", "DEFAULT_DISTANCE_BUCKETS"]
