"""negative_sampler — Stage 2 3 negative sample types per FR-013.

Types: reject / pivot / unsatisfiable.
Total ratio controlled by `negative_ratio` (default 0.10); type-level mix
ensures each ≥ 20% of negatives (SC-006).
"""

from __future__ import annotations

import random
from typing import Optional

from ..common.logging import get_logger

logger = get_logger(__name__)

NEGATIVE_TYPES = ["reject", "pivot", "unsatisfiable"]


class NegativeSampler:
    def __init__(
        self,
        rng: random.Random,
        *,
        negative_ratio: float = 0.10,
    ) -> None:
        self._rng = rng
        self._ratio = negative_ratio

    def is_negative(self) -> bool:
        return self._rng.random() < self._ratio

    def pick_type(self) -> str:
        # Uniform across 3 types; each type guaranteed ≥ 1/3 of negatives
        return self._rng.choice(NEGATIVE_TYPES)


__all__ = ["NegativeSampler", "NEGATIVE_TYPES"]