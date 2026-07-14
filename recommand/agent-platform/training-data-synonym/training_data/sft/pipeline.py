"""SFTPipeline — Stage 3: item-driven SFT corpus generation.

For each item, sends item data + scenario_type to LLM, which generates
conversation + params + guide_text.  Outputs train.jsonl (80%) + test.jsonl (20%).
"""

from __future__ import annotations

import hashlib
import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..common.config import Config
from ..common.llm_client import LLMClient
from ..common.logging import get_logger
from ..data_model import ItemTags, Role, SFTSample
from .failures import SFTFailure, SFTFailureWriter
from .llm_generator import LLMGenerator
from .prompt import load_template
from .scenario_sampler import ScenarioSampler, SCENARIO_MAP
from .validator import validate_sft_sample
from .writer import SFTSampleWriter

logger = get_logger(__name__)


@dataclass
class SFTSummary:
    total: int = 0
    sft_failures: int = 0
    train_count: int = 0
    test_count: int = 0
    intent_distribution: dict = field(default_factory=dict)
    scenario_distribution: dict = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    finished_at: Optional[str] = None


class SFTPipeline:
    def __init__(
        self,
        config: Config,
        llm_client: LLMClient,
        input_path: str | Path,
        output_dir: str | Path,
        *,
        prompt_template_path: str | Path | None = None,
        count_per_item: int = 8,
        max_message_turns: int = 9,
        train_ratio: float = 0.80,
        max_items: int | None = None,
    ) -> None:
        self.config = config
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.count_per_item = count_per_item
        self.max_message_turns = max_message_turns
        self.train_ratio = train_ratio
        self.max_items = max_items
        self.summary = SFTSummary()

        self.prompt_template = load_template(prompt_template_path)
        sft_cfg = (config.pipeline.get("training_data") or {}).get("sft", {})
        self.tag_keys = set(sft_cfg.get("tag_keys", [])) or self._FALLBACK_TAG_KEYS
        self.concurrency = int(sft_cfg.get("concurrency", 4))
        self.llm_generator = LLMGenerator(llm_client, self.prompt_template, self.tag_keys)

        self._rng = random.Random(42)
        self.scenario_sampler = ScenarioSampler(self._rng)

        self.failures = SFTFailureWriter(self.output_dir / "sft_failures.jsonl")

    # ---- main ----------------------------------------------------------

    def run(self) -> SFTSummary:
        items = self._load_items()

        all_samples: list[SFTSample] = []
        total = len(items)
        done = 0
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = {pool.submit(self._process_item, it): it for it in items}
            for fut in as_completed(futures):
                done += 1
                logger.info("sft_progress", extra={
                    "stage": "sft", "progress": f"{done}/{total}",
                    "item_id": futures[fut].item_id,
                })
                try:
                    samples = fut.result()
                    all_samples.extend(samples)
                except Exception as e:
                    logger.warning("sft_item_failed", extra={
                        "stage": "sft", "item_id": futures[fut].item_id, "error": str(e),
                    })

        # Dedup by params: keep up to 3 per unique params key
        from collections import Counter

        key_counts: Counter = Counter()
        deduped: list[SFTSample] = []
        for s in all_samples:
            key = json.dumps(s.params, sort_keys=True, ensure_ascii=False)
            if key_counts[key] < 3:
                key_counts[key] += 1
                deduped.append(s)
        dup_count = len(all_samples) - len(deduped)
        if dup_count:
            print(f"  Deduped: {dup_count} duplicates removed ({len(deduped)} kept)")

        # --max-items: limit final output count (not input items)
        if self.max_items is not None and len(deduped) > self.max_items:
            deduped = deduped[: self.max_items]

        all_samples = deduped

        # Train/test split by item_id md5 (stable, no leakage)
        train, test = self._split_by_item(all_samples)
        self._write_split(train, "train.jsonl")
        self._write_split(test, "test.jsonl")

        self.summary.total = len(all_samples)
        self.summary.train_count = len(train)
        self.summary.test_count = len(test)
        self.summary.intent_distribution = self._count_intents(all_samples)
        self.summary.scenario_distribution = self.scenario_sampler.distribution
        self.summary.finished_at = datetime.utcnow().isoformat() + "Z"

        self._write_summary()
        self._print_distribution(train, "train", self.summary.train_count)
        self._print_distribution(test, "test", self.summary.test_count)
        return self.summary

    # ---- item loading --------------------------------------------------

    _FALLBACK_TAG_KEYS = {
        "brand", "category", "taste", "occasion", "consumable_type", "avg_prc", "distance",
    }

    def _load_items(self) -> list[ItemTags]:
        if not self.input_path.exists():
            raise FileNotFoundError(f"input not found: {self.input_path}")
        items: list[ItemTags] = []
        with self.input_path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)

                # Auto-detect format: nested "tags" dict → item_tags_v2; flat → generic
                tags = rec.get("tags")
                if isinstance(tags, dict):
                    # item_tags_v2 format
                    raw_record = rec.get("raw_record", {})
                    item_id = rec.get("item_id", "")
                    item_type = rec.get("item_type", "mt_shop")
                else:
                    # Generic flat format — auto-extract tag keys from config
                    tags = {k: rec[k] for k in self.tag_keys if k in rec and rec[k] is not None}
                    raw_record = {k: v for k, v in rec.items() if k not in self.tag_keys}
                    item_id = rec.get("str_id", rec.get("item_id", ""))
                    item_type = rec.get("item_type", "meituan_shop")

                items.append(
                    ItemTags(
                        item_id=str(item_id),
                        item_type=Role(item_type),
                        raw_record=raw_record,
                        tags=tags,
                        tag_source=None,
                        enriched_at=datetime.utcnow(),
                        llm_model=rec.get("llm_model", ""),
                    )
                )
        return items

    # ---- per-item processing -------------------------------------------

    def _process_item(self, item: ItemTags) -> list[SFTSample]:
        item_view = dict(item.tags)
        item_view["str_nm"] = item.raw_record.get("str_nm", "")

        samples: list[SFTSample] = []
        for _ in range(self.count_per_item):
            scenario_type = self.scenario_sampler.pick()
            # Turn distribution: 1-9 (5 user + 4 assistant max), bias 2-5
            target_turns = self._rng.choices(
                [1, 2, 3, 4, 5, 6, 7, 8, 9],
                weights=[3, 25, 25, 20, 15, 6, 3, 2, 1],
            )[0]
            try:
                result = self.llm_generator.generate(
                    item=item_view,
                    scenario_type=SCENARIO_MAP.get(scenario_type, scenario_type),
                    target_turns=target_turns,
                    item_id=item.item_id,
                )
                sample = self._build_sample(item, result, scenario_type)
                if sample is not None:
                    samples.append(sample)
            except Exception as e:
                self.summary.sft_failures += 1
                self.failures.append(
                    SFTFailure(
                        item_id=item.item_id,
                        raw_response=None,
                        error="GenError",
                        error_detail=str(e),
                        target_params={},
                    )
                )

        return samples

    def _build_sample(
        self, item: ItemTags, result: dict, assigned_type: str
    ) -> Optional[SFTSample]:
        messages = result["messages"]
        if len(messages) > self.max_message_turns:
            messages = messages[: self.max_message_turns]

        sample = SFTSample(
            item_id=item.item_id,
            item_type=item.item_type,
            intent=result.get("intent", "search_product"),
            messages=messages,
            params=result["params"],
            guide_text=result["guide_text"],
            order_by=None,
            scenario_type=assigned_type,
            llm_model=self.llm_generator.model_name,
        )

        ok, errs = validate_sft_sample(
            sample, self.config.dim_dictionary, max_turns=self.max_message_turns,
        )
        if not ok:
            self.summary.sft_failures += 1
            self.failures.append(
                SFTFailure(
                    item_id=item.item_id,
                    raw_response=None,
                    error="Validation",
                    error_detail="; ".join(errs),
                    target_params=result["params"],
                )
            )
            return None
        return sample

    # ---- split / write -------------------------------------------------

    def _split_by_item(self, samples: list[SFTSample]) -> tuple[list, list]:
        """MD5-based split by item_id — stable, no leakage."""
        train, test = [], []
        for s in samples:
            h = int(hashlib.md5(s.item_id.encode()).hexdigest(), 16) % 100
            if h < int(self.train_ratio * 100):
                train.append(s)
            else:
                test.append(s)
        return train, test

    def _write_split(self, samples: list[SFTSample], filename: str) -> None:
        # Use a temporary writer to flush this split
        writer = SFTSampleWriter(self.output_dir / filename)
        writer.write(samples)

    def _count_intents(self, samples: list[SFTSample]) -> dict:
        d: dict = {}
        for s in samples:
            d[s.intent] = d.get(s.intent, 0) + 1
        return d

    def _print_distribution(self, samples: list[SFTSample], label: str, total: int) -> None:
        from collections import Counter

        c = Counter(s.scenario_type for s in samples)
        print(f"\n--- {label} ({total} samples) ---")
        for t in sorted(c):
            pct = c[t] / total * 100 if total else 0
            print(f"  {t:30s} {c[t]:>5} ({pct:5.1f}%)")

    def _write_summary(self) -> None:
        summary_path = self.output_dir / "summary.json"
        existing = {}
        if summary_path.exists():
            try:
                existing = json.loads(summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        existing.update({"sft": self.summary.__dict__})
        summary_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


__all__ = ["SFTPipeline", "SFTSummary"]
