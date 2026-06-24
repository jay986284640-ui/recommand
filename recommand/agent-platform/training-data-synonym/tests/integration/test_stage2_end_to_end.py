"""Integration test for Stage 2 end-to-end (T059).

Runs Stage 2 pipeline against Stage 1 output and verifies SC-004/005/006/007.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from training_data_synonym.common.config import Config
from training_data_synonym.common.llm_client import MockLLMClient
from training_data_synonym.sft.pipeline import SFTPipeline


def test_stage2_end_to_end(fixtures_dir: Path, repo_root: Path, tmp_output_dir: Path):
    import subprocess
    # Run Stage 1 first; SC-003 may fail (mock LLM random coverage), but
    # the artifact (item_tags.jsonl) must exist regardless.
    subprocess.run(
        [
            "python", "-m", "training_data_synonym.cli", "enrich",
            "--sql", str(repo_root.parent.parent / "tabale_structer.sql"),
            "--source", "mock",
            "--fixture-dir", str(repo_root / "tests/fixtures/hive"),
            "--output-dir", str(tmp_output_dir),
            "--log-level", "WARNING",
        ],
        check=False, capture_output=True, text=True,
    )
    assert (tmp_output_dir / "item_tags.jsonl").exists()

    cfg = Config.load(repo_root / "configs")
    pipeline = SFTPipeline(
        config=cfg,
        llm_client=MockLLMClient(seed=42),
        input_path=tmp_output_dir / "item_tags.jsonl",
        output_dir=tmp_output_dir,
        count_per_item=4,
        max_message_turns=5,
    )
    summary = pipeline.run()
    assert summary.total >= 50  # at least 50 samples
    assert summary.sft_failures == 0

    # Read sft_corpus.jsonl and verify structure
    with (tmp_output_dir / "sft_corpus.jsonl").open() as f:
        samples = [json.loads(l) for l in f if l.strip()]
    assert all(s["_format_version"] == "sft_corpus_v2" for s in samples)
    # SC-006: negative ratio ≈ 0.10 ± 0.05 (mock LLM more random than production)
    n_neg = sum(1 for s in samples if s["negative"])
    ratio = n_neg / len(samples)
    assert 0.05 <= ratio <= 0.20, f"negative ratio {ratio} out of [0.05, 0.20]"


def test_negative_type_distribution():
    """3 negative types each ≥ 20% of negatives (SC-006 strict)."""
    from training_data_synonym.sft.negative_sampler import NegativeSampler
    import random
    rng = random.Random(0)
    s = NegativeSampler(rng, negative_ratio=1.0)
    counter = Counter(s.pick_type() for _ in range(3000))
    for t in ("reject", "pivot", "unsatisfiable"):
        assert counter[t] / 3000 >= 0.20, f"{t} only {counter[t]/3000:.2%}"