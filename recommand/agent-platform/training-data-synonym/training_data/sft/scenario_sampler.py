"""scenario_sampler — controls SFT data distribution per spec."""

from __future__ import annotations

import random
from collections import Counter

# Default distribution matching the spec table
DEFAULT_DISTRIBUTION = {
    "single_turn":         0.15,  # 单轮简单查询
    "single_multi_cond":   0.20,  # 单轮多条件查询
    "add_condition":       0.25,  # 多轮新增条件
    "modify_condition":    0.10,  # 多轮修改条件
    "remove_condition":    0.05,  # 多轮删除条件
    "negative_condition":  0.10,  # 否定/排除条件
    "reference_resolution": 0.05,  # 指代消解
    "intent_switch":       0.05,  # 意图切换
    "single_multi_complex": 0.05,  # 单轮复杂条件（与single_multi_cond合并为20%）
}


class ScenarioSampler:
    """Assign scenario_type per sample to match target distribution.

    Uses weighted random sampling; across many calls the output
    converges to the target distribution.
    """

    def __init__(
        self,
        rng: random.Random | None = None,
        distribution: dict[str, float] | None = None,
    ) -> None:
        self._rng = rng or random.Random(42)
        self._dist = distribution or DEFAULT_DISTRIBUTION
        self._counter: Counter = Counter()

    def pick(self) -> str:
        """Pick a scenario_type weighted by the target distribution."""
        types = list(self._dist.keys())
        weights = [self._dist[t] for t in types]
        # Weighted random choice
        total = sum(weights)
        r = self._rng.random() * total
        cum = 0.0
        for t, w in zip(types, weights):
            cum += w
            if r <= cum:
                self._counter[t] += 1
                return t
        return types[-1]

    @property
    def distribution(self) -> dict[str, int]:
        return dict(self._counter)


# Map scenario_types from sampler to prompt labels
SCENARIO_MAP = {
    "single_turn": "single_turn — 用户一次性说清需求（1-2个条件）",
    "single_multi_cond": "single_turn — 用户一次性表达多个条件组合（3个以上条件）",
    "single_multi_complex": "single_turn — 用户一次性表达多条件 + 数字约束（距离/价格）",
    "add_condition": "add_condition — 多轮新增条件",
    "modify_condition": "modify_condition — 多轮修改条件",
    "remove_condition": "remove_condition — 多轮删除条件",
    "negative_condition": "negative_condition — 否定/排除需求",
    "reference_resolution": "reference_resolution — 指代消解",
    "intent_switch": "intent_switch — 意图切换",
}


__all__ = ["ScenarioSampler", "DEFAULT_DISTRIBUTION", "SCENARIO_MAP"]
