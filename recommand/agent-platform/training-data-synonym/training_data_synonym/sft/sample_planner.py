"""sample_planner — Stage 2 per-item coverage planning (per FR-011, SC-005).

Plans N samples per item such that their union covers all non-null dims of
the item. If naive random generation misses a dim, append a `forced_coverage`
sample targeting the missing dim.
"""

from __future__ import annotations

import random
from typing import Iterable

from ..common.logging import get_logger
from ..data_model import DIM_ORDER, ItemTags, Role

logger = get_logger(__name__)


def get_non_null_dims(item: ItemTags) -> list[str]:
    """Return the dims of item.tags that have a non-null value."""
    return [d for d in DIM_ORDER if d != "distance" and item.tags.get(d) is not None]


class SamplePlanner:
    def __init__(self, count_per_item: int = 8, max_turns: int = 5) -> None:
        self.count_per_item = count_per_item
        self.max_turns = max_turns

    def plan_turn_distribution(
        self, *, n_samples: int, rng: random.Random
    ) -> list[int]:
        """Pick `n_samples` turn counts sampled from the configured distribution."""
        # default: 1:10%, 2:20%, 3:35%, 4:25%, 5:10%
        dist = [0.10, 0.20, 0.35, 0.25, 0.10]
        turns_pool = list(range(1, 6))
        return [self._weighted_choice(turns_pool, dist, rng) for _ in range(n_samples)]

    def _weighted_choice(self, choices, weights, rng):
        cum = 0.0
        r = rng.random()
        for c, w in zip(choices, weights):
            cum += w
            if r <= cum:
                return c
        return choices[-1]

    def plan_diverse_dims(
        self,
        item: ItemTags,
        n_samples: int,
        rng: random.Random,
    ) -> list[list[str]]:
        """Plan `n_samples` per-sample dim subsets covering all non-null dims.

        Returns: list of per-sample `covered_dims` lists.
        """
        target_dims = get_non_null_dims(item)
        if not target_dims:
            return [[] for _ in range(n_samples)]

        # Greedy: distribute target dims across samples
        per_sample: list[list[str]] = [[] for _ in range(n_samples)]
        # First pass: each sample gets 1-2 dims, ensuring every dim is covered at least once
        # (this is a coarse planner; LLM will elaborate details)
        rng.shuffle(target_dims)
        for i, d in enumerate(target_dims):
            slot = i % n_samples
            per_sample[slot].append(d)
        # Second pass: if a sample has 0 dims (very rare), grab from a neighbor
        for i, slot in enumerate(per_sample):
            if not slot:
                donor = max(range(n_samples), key=lambda j: len(per_sample[j]) if j != i else 0)
                if per_sample[donor]:
                    moved = per_sample[donor].pop()
                    slot.append(moved)
        return per_sample


__all__ = ["SamplePlanner", "get_non_null_dims"]