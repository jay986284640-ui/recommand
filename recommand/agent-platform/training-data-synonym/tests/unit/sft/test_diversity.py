"""Unit tests for diversity sampler (T054)."""

from __future__ import annotations

import random

from training_data_synonym.sft.diversity import DEFAULT_TEMPLATES, DiversitySampler


def test_pick_template_returns_valid():
    rng = random.Random(0)
    s = DiversitySampler(rng)
    t = s.pick_template("item1")
    assert t in DEFAULT_TEMPLATES


def test_diversity_distribution_within_limit():
    rng = random.Random(0)
    s = DiversitySampler(rng, template_repeat_limit=0.20)
    counts = {}
    n = 200
    for _ in range(n):
        t = s.pick_template("item1")
        counts[t] = counts.get(t, 0) + 1
    # Each template should be at most 20% of total
    for t, c in counts.items():
        assert c / n <= 0.20 + 0.05, f"{t}={c}/{n}={c/n:.2%} > 20%"


def test_per_item_reset_isolation():
    rng = random.Random(0)
    s = DiversitySampler(rng, template_repeat_limit=0.10)
    # Saturate item A
    for _ in range(50):
        s.pick_template("itemA")
    # item B should start fresh
    counts = {}
    for _ in range(20):
        t = s.pick_template("itemB")
        counts[t] = counts.get(t, 0) + 1
    # The most-frequent template in itemB should be below saturation
    max_freq = max(counts.values())
    assert max_freq / 20 <= 0.5  # generous bound for fresh start


def test_reset_specific_item():
    rng = random.Random(0)
    s = DiversitySampler(rng)
    for _ in range(10):
        s.pick_template("itemA")
    s.reset("itemA")
    assert "itemA" not in s._per_item_used