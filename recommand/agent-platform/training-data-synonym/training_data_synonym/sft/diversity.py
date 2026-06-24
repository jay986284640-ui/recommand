"""diversity — sentence template rotation (per FR-014, SC-007).

Picks one of N sentence templates per sample to ensure first-user-message
diversity. Detection: if a template exceeds `template_repeat_limit` ratio
within an item, lower temperature and retry.
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Optional


# 6 template skeletons (per configs/sentence_templates.yaml)
DEFAULT_TEMPLATES = [
    "query_first",     # {verb}{category}, {distance}, {occasion}
    "scenario_first",  # {occasion}想{category},{distance}
    "constraint_first",# {distance}, 推荐{category}
    "vague_first",     # 想吃点东西 / 想喝点东西
    "direct_first",    # {merchant}的{category}
    "pivot_start",     # 算了不看{category}了,看{another_category}
]


class DiversitySampler:
    def __init__(
        self,
        rng: random.Random,
        templates: Optional[list[str]] = None,
        template_repeat_limit: float = 0.20,
    ) -> None:
        self._rng = rng
        self._templates = templates or DEFAULT_TEMPLATES
        self._limit = template_repeat_limit
        self._per_item_used: dict[str, Counter] = {}  # item_id → Counter

    def pick_template(self, item_id: str) -> str:
        used = self._per_item_used.setdefault(item_id, Counter())
        # Pick least-used template within limit; fall back to random if all saturated
        candidates = [t for t in self._templates if used[t] / max(1, sum(used.values())) < self._limit]
        if not candidates:
            # All saturated — still pick (will accept high-frequency)
            return self._rng.choice(self._templates)
        choice = self._rng.choice(candidates)
        used[choice] += 1
        return choice

    def reset(self, item_id: Optional[str] = None) -> None:
        if item_id is None:
            self._per_item_used.clear()
        else:
            self._per_item_used.pop(item_id, None)


__all__ = ["DiversitySampler", "DEFAULT_TEMPLATES"]