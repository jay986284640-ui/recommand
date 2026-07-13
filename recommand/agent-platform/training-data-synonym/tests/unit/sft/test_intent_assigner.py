"""Unit tests for intent_assigner (T055)."""

from __future__ import annotations

import random

from training_data.data_model import Role
from training_data.sft.intent_assigner import INTENTS, IntentAssigner


def test_assign_returns_count_per_item_intents():
    rng = random.Random(0)
    a = IntentAssigner(rng)
    intents = a.assign(Role.MEITUAN_SHOP, count_per_item=8)
    assert len(intents) == 8
    for i in intents:
        assert i in INTENTS


def test_coupon_bias_toward_use_coupon_pay():
    rng = random.Random(0)
    a = IntentAssigner(rng)
    counter = {}
    n = 1000
    for _ in range(n):
        for i in a.assign(Role.COUPON, count_per_item=1):
            counter[i] = counter.get(i, 0) + 1
    # use_coupon + pay should be substantial for coupons
    coupon_total = counter.get("use_coupon", 0) + counter.get("pay", 0)
    assert coupon_total / n >= 0.40, f"coupon bias weak: use_coupon+pay={coupon_total}/{n}"


def test_meituan_bias_toward_search_item():
    rng = random.Random(0)
    a = IntentAssigner(rng)
    counter = {}
    n = 1000
    for _ in range(n):
        for i in a.assign(Role.MEITUAN_SHOP, count_per_item=1):
            counter[i] = counter.get(i, 0) + 1
    assert counter.get("search_item", 0) / n >= 0.40


def test_distribution_cumulative_property():
    rng = random.Random(0)
    a = IntentAssigner(rng)
    for _ in range(100):
        a.assign(Role.MEITUAN_SHOP, count_per_item=1)
    dist = a.distribution
    total = sum(dist.values())
    assert total == 100
    assert all(i in INTENTS for i in dist)