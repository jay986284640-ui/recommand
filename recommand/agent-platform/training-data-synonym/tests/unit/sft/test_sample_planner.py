"""Unit tests for sample_planner (T056)."""

from __future__ import annotations

import random

from training_data.data_model import DIM_ORDER, ItemTags, Role, TagOrigin, TagSource
from training_data.sft.sample_planner import SamplePlanner, get_non_null_dims


def _make_item(tags: dict) -> ItemTags:
    return ItemTags(
        item_id="i1",
        item_type=Role.MEITUAN_SHOP,
        raw_record={},
        tags={**{d: None for d in DIM_ORDER}, **tags},
        tag_source=TagSource(**{d: TagOrigin.MISSING for d in DIM_ORDER}),
        llm_model="mock",
    )


def test_get_non_null_dims_excludes_distance():
    item = _make_item({"category": "咖啡", "consumable_type": "drink", "distance": None})
    non_null = get_non_null_dims(item)
    assert "category" in non_null
    assert "consumable_type" in non_null
    assert "distance" not in non_null


def test_plan_turns_in_range():
    rng = random.Random(0)
    p = SamplePlanner(count_per_item=8, max_turns=5)
    turns = p.plan_turn_distribution(n_samples=8, rng=rng)
    assert all(1 <= t <= 5 for t in turns)


def test_plan_turn_distribution_close_to_expected():
    rng = random.Random(42)
    p = SamplePlanner(count_per_item=8, max_turns=5)
    from collections import Counter
    counts = Counter()
    for _ in range(100):
        for t in p.plan_turn_distribution(n_samples=8, rng=rng):
            counts[t] += 1
    total = sum(counts.values())
    for t, expected_pct in zip([1, 2, 3, 4, 5], [0.10, 0.20, 0.35, 0.25, 0.10]):
        actual = counts.get(t, 0) / total
        assert abs(actual - expected_pct) < 0.05, f"turn={t} actual={actual} expected={expected_pct}"


def test_plan_diverse_dims_covers_all():
    """Sample planner should ensure all non-null dims covered across N samples."""
    rng = random.Random(0)
    p = SamplePlanner(count_per_item=8, max_turns=5)
    item = _make_item({"category": "咖啡", "consumable_type": "drink",
                       "brand": "星巴克", "avg_prc": "30-50",
                       "age": "25-35", "occasion": "下午茶", "taste": ["甜"]})
    planned = p.plan_diverse_dims(item, n_samples=8, rng=rng)
    union = set()
    for per_sample in planned:
        union.update(per_sample)
    target = {"category", "consumable_type", "brand", "avg_prc", "age", "occasion", "taste"}
    assert target.issubset(union), f"missing: {target - union}"


def test_plan_diverse_dims_empty_for_cold_start():
    rng = random.Random(0)
    p = SamplePlanner(count_per_item=4)
    item = _make_item({})  # all null
    planned = p.plan_diverse_dims(item, n_samples=4, rng=rng)
    assert all(p == [] for p in planned)