"""Unit tests for distance_sampler (T052)."""

from __future__ import annotations

import random

from training_data.sft.distance_sampler import DistanceSampler


def test_ratio_caps_null_ratio():
    rng = random.Random(0)
    s = DistanceSampler(rng, distance_param_ratio=0.0)
    out = s.sample_distance_param()
    assert out is None


def test_ratio_always_filled():
    rng = random.Random(0)
    s = DistanceSampler(rng, distance_param_ratio=1.0)
    for _ in range(20):
        out = s.sample_distance_param()
        assert out is not None
        assert out["op"] in {"in", "not contains"}
        assert "0-500" in out["values"] or "500-1000" in out["values"] or "1000-3000" in out["values"] or "3000+" in out["values"]


def test_negative_inverts_op():
    rng = random.Random(0)
    s = DistanceSampler(rng, distance_param_ratio=1.0)
    out = s.sample_distance_param(is_negative=True)
    assert out["op"] == "not contains"


def test_order_by_distance_present_couples_high():
    rng = random.Random(0)
    s = DistanceSampler(rng, order_by_distribution=[0.30, 0.20, 0.15, 0.10, 0.25])
    # When distance_param is set, P(order_by=distance) should be ≥ 0.60
    n_distance = 0
    trials = 1000
    for _ in range(trials):
        v = s.sample_order_by(distance_param={"op": "in", "values": ["0-500"]})
        if v == "distance":
            n_distance += 1
    ratio = n_distance / trials
    assert ratio >= 0.55, f"P(distance|param)={ratio} < 0.55"


def test_order_by_distance_null_couples_low():
    rng = random.Random(0)
    s = DistanceSampler(rng, order_by_distribution=[0.30, 0.20, 0.15, 0.10, 0.25])
    n_distance = 0
    trials = 1000
    for _ in range(trials):
        v = s.sample_order_by(distance_param=None)
        if v == "distance":
            n_distance += 1
    ratio = n_distance / trials
    assert ratio <= 0.15, f"P(distance|null)={ratio} > 0.15"


def test_order_by_returns_5set_or_null():
    rng = random.Random(0)
    s = DistanceSampler(rng)
    for _ in range(50):
        v = s.sample_order_by(distance_param=None)
        assert v in {"distance", "price", "rating", "time", None}