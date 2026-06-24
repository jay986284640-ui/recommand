"""Unit tests for incremental state (T034)."""

from __future__ import annotations

from training_data_synonym.enricher.state import (
    EnrichmentStateRow,
    EnrichmentStateStore,
    compute_raw_md5,
)


def test_raw_md5_deterministic():
    raw = {"a": 1, "b": [2, 3]}
    h1 = compute_raw_md5(raw)
    h2 = compute_raw_md5(raw)
    assert h1 == h2
    assert len(h1) == 32


def test_raw_md5_sensitive_to_change():
    h1 = compute_raw_md5({"a": 1})
    h2 = compute_raw_md5({"a": 2})
    assert h1 != h2


def test_state_needs_recompute_when_new():
    store = EnrichmentStateStore("/tmp/_state_test.jsonl")
    assert store.needs_recompute("i1", "m1", "d1", "p1") is True


def test_state_skips_when_unchanged(tmp_path):
    store = EnrichmentStateStore(tmp_path / "s.jsonl")
    store.upsert(EnrichmentStateRow("i1", "m1", "d1", "p1", "2026-06-22T00:00:00Z", "mock"))
    assert store.needs_recompute("i1", "m1", "d1", "p1") is False


def test_state_recomputes_on_raw_change(tmp_path):
    store = EnrichmentStateStore(tmp_path / "s.jsonl")
    store.upsert(EnrichmentStateRow("i1", "m1", "d1", "p1", "t", "mock"))
    assert store.needs_recompute("i1", "m2", "d1", "p1") is True


def test_state_recomputes_on_dict_version(tmp_path):
    store = EnrichmentStateStore(tmp_path / "s.jsonl")
    store.upsert(EnrichmentStateRow("i1", "m1", "d1", "p1", "t", "mock"))
    assert store.needs_recompute("i1", "m1", "d2", "p1") is True


def test_state_recomputes_on_partition(tmp_path):
    store = EnrichmentStateStore(tmp_path / "s.jsonl")
    store.upsert(EnrichmentStateRow("i1", "m1", "d1", "p1", "t", "mock"))
    assert store.needs_recompute("i1", "m1", "d1", "p2") is True


def test_state_flush_roundtrip(tmp_path):
    path = tmp_path / "s.jsonl"
    store = EnrichmentStateStore(path)
    store.upsert(EnrichmentStateRow("i1", "m1", "d1", "p1", "t", "mock"))
    store.upsert(EnrichmentStateRow("i2", "m2", "d1", "p1", "t", "mock"))
    store.flush()

    # Reload
    store2 = EnrichmentStateStore(path)
    assert store2.get("i1").raw_md5 == "m1"
    assert store2.get("i2").raw_md5 == "m2"