"""Unit tests for negative_sampler (T053)."""

from __future__ import annotations

import random
from collections import Counter

from training_data.sft.negative_sampler import NEGATIVE_TYPES, NegativeSampler


def test_is_negative_zero_ratio():
    rng = random.Random(0)
    s = NegativeSampler(rng, negative_ratio=0.0)
    assert s.is_negative() is False


def test_is_negative_full_ratio():
    rng = random.Random(0)
    s = NegativeSampler(rng, negative_ratio=1.0)
    assert s.is_negative() is True


def test_negative_ratio_close_to_config():
    rng = random.Random(0)
    s = NegativeSampler(rng, negative_ratio=0.10)
    n = sum(s.is_negative() for _ in range(10000))
    assert abs(n / 10000 - 0.10) < 0.02


def test_pick_type_returns_one_of_three():
    rng = random.Random(0)
    s = NegativeSampler(rng, negative_ratio=1.0)
    seen = set()
    for _ in range(200):
        t = s.pick_type()
        seen.add(t)
    assert seen == set(NEGATIVE_TYPES)


def test_negative_type_distribution_balanced():
    rng = random.Random(0)
    s = NegativeSampler(rng, negative_ratio=1.0)
    counter = Counter(s.pick_type() for _ in range(3000))
    # Each type should be roughly 1/3 (3000/3=1000, ±10%)
    for t in NEGATIVE_TYPES:
        assert abs(counter[t] - 1000) < 200, f"{t}={counter[t]}, expected ~1000"