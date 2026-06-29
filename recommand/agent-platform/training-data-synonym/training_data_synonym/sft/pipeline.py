"""SFTPipeline — Stage 2 orchestrator.

Reads item_tags.jsonl → for each item:
  1. Plan N samples (turns + covered_dims)
  2. Assign intent (item_type biased)
  3. Decide if negative (3 types)
  4. Sample distance + order_by (decoupled, FR-013b)
  5. Pick sentence template (diversity)
  6. Build target_params from item.tags (modulated by intent, negative, distance)
  7. LLM generate → validate → write
  8. Force-cover if any non-null dim is uncovered
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..common.config import Config
from ..common.exceptions import ValidationError
from ..common.llm_client import LLMClient
from ..common.logging import get_logger
from ..common.versioning import SFT_CORPUS_V
from ..data_model import DIM_ORDER, ItemTags, MessageTurn, Role, SFTSample
from .distance_sampler import DistanceSampler
from .diversity import DiversitySampler
from .failures import SFTFailure, SFTFailureWriter
from .intent_assigner import IntentAssigner
from .llm_generator import LLMGenerator
from .negative_sampler import NegativeSampler
from .sample_planner import SamplePlanner, get_non_null_dims
from .validator import validate_sft_sample
from .writer import SFTSampleWriter

logger = get_logger(__name__)


@dataclass
class SFTSummary:
    total: int = 0
    sft_failures: int = 0
    forced_coverage_count: int = 0
    intent_distribution: dict = field(default_factory=dict)
    coverage_pass: bool = False
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
        max_message_turns: int = 5,
        negative_ratio: float = 0.10,
    ) -> None:
        self.config = config
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.count_per_item = count_per_item
        self.max_message_turns = max_message_turns
        self.negative_ratio = negative_ratio
        self.summary = SFTSummary()

        if prompt_template_path is None:
            pt = Path(__file__).resolve().parent.parent.parent / "configs" / "prompts" / "sft_v1.txt"
        else:
            pt = Path(prompt_template_path)
        self.prompt_template = pt.read_text(encoding="utf-8") if pt.exists() else ""

        # RNG (deterministic seed for tests)
        self._rng = random.Random(42)

        # Sub-samplers
        self.distance_sampler = DistanceSampler(self._rng)
        self.negative_sampler = NegativeSampler(self._rng, negative_ratio=negative_ratio)
        self.diversity_sampler = DiversitySampler(self._rng)
        self.intent_assigner = IntentAssigner(self._rng)
        self.sample_planner = SamplePlanner(
            count_per_item=count_per_item, max_turns=max_message_turns
        )
        self.llm_generator = LLMGenerator(llm_client, self.prompt_template)

        # Writers
        self.writer = SFTSampleWriter(self.output_dir / "sft_corpus.jsonl")
        self.failures = SFTFailureWriter(self.output_dir / "sft_failures.jsonl")

    def run(self) -> SFTSummary:
        items = self._load_items()
        all_samples: list[SFTSample] = []
        for it in items:
            samples = self._process_item(it)
            all_samples.extend(samples)
        self.writer.write(all_samples)

        # Self-check
        self._self_check(items, all_samples)
        self.summary.total = len(all_samples)
        self.summary.intent_distribution = self.intent_assigner.distribution
        self.summary.finished_at = datetime.utcnow().isoformat() + "Z"

        # Append SFT fields to summary.json (preserve Stage 1 fields if present)
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
        return self.summary

    def _load_items(self) -> list[ItemTags]:
        if not self.input_path.exists():
            raise FileNotFoundError(f"item_tags.jsonl not found: {self.input_path}")
        items: list[ItemTags] = []
        with self.input_path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("_format_version") != "item_tags_v2":
                    raise ValidationError(
                        f"item_tags version mismatch: expected item_tags_v2, got {rec.get('_format_version')}"
                    )
                # Reconstruct minimal ItemTags (we need tags + item_type)
                items.append(
                    ItemTags(
                        item_id=rec["item_id"],
                        item_type=Role(rec["item_type"]),
                        raw_record=rec.get("raw_record", {}),
                        tags=rec["tags"],
                        tag_source=None,  # type: ignore — not used in Stage 2
                        enriched_at=datetime.utcnow(),
                        llm_model=rec.get("llm_model", ""),
                    )
                )
        return items

    def _process_item(self, item: ItemTags) -> list[SFTSample]:
        # Reset diversity sampler per item
        self.diversity_sampler.reset(item.item_id)

        # 1. Plan N samples
        turn_counts = self.sample_planner.plan_turn_distribution(
            n_samples=self.count_per_item, rng=self._rng
        )

        # 2. Assign intents
        intents = self.intent_assigner.assign(item.item_type, count_per_item=self.count_per_item)

        # 3. For each sample, generate
        item_samples: list[SFTSample] = []
        for i in range(self.count_per_item):
            negative = self.negative_sampler.is_negative()
            negative_type = self.negative_sampler.pick_type() if negative else None
            target_params = self._build_target_params(item, negative, negative_type)
            target_order_by = self.distance_sampler.sample_order_by(
                distance_param=target_params.get("distance")
            )
            template = self.diversity_sampler.pick_template(item.item_id)
            target_turns = turn_counts[i]

            try:
                sample = self._generate_one(
                    item=item,
                    target_intent=intents[i],
                    target_params=target_params,
                    target_order_by=target_order_by,
                    target_turns=target_turns,
                    negative=negative,
                    negative_type=negative_type,
                    template=template,
                    forced=False,
                )
                if sample is not None:
                    item_samples.append(sample)
            except Exception as e:  # noqa: BLE001
                self.summary.sft_failures += 1
                self.failures.append(
                    SFTFailure(
                        item_id=item.item_id,
                        raw_response=None,
                        target_params=target_params,
                        error="Other",
                        error_detail=str(e),
                    )
                )

        # 4. Force cover remaining non-null dims if any uncovered
        covered = set()
        for s in item_samples:
            covered.update(s.covered_dims)
        target_dims = set(get_non_null_dims(item))
        uncovered = target_dims - covered
        if uncovered:
            for missing_dim in list(uncovered):
                try:
                    # Force one sample targeting `missing_dim`
                    target_params = self._force_target_dim(item, missing_dim)
                    sample = self._generate_one(
                        item=item,
                        target_intent="search_item",
                        target_params=target_params,
                        target_order_by=self.distance_sampler.sample_order_by(
                            distance_param=target_params.get("distance")
                        ),
                        target_turns=2,
                        negative=False,
                        negative_type=None,
                        template="direct_first",
                        forced=True,
                        covered_dims_override=[missing_dim],
                    )
                    if sample is not None:
                        item_samples.append(sample)
                        self.summary.forced_coverage_count += 1
                except Exception as e:  # noqa: BLE001
                    self.summary.sft_failures += 1
                    self.failures.append(
                        SFTFailure(
                            item_id=item.item_id,
                            raw_response=None,
                            target_params=target_params,
                            error="CoverageFailure",
                            error_detail=str(e),
                        )
                    )

        return item_samples

    def _build_target_params(
        self, item: ItemTags, negative: bool, negative_type: Optional[str]
    ) -> dict:
        """Build target params from item's 8-dim tags.

        Non-distance dims: pulled directly from item.tags (modulated by intent).
        distance: sampled via DistanceSampler.
        consumable_type: derived if available, else None.
        """
        params: dict = {d: None for d in DIM_ORDER}

        # 6 non-distance dims (verbatim from item.tags)
        for d in ("category", "consumable_type", "merchant", "avg_prc", "age", "occasion", "taste"):
            v = item.tags.get(d)
            if v is not None:
                if d == "consumable_type":
                    params[d] = {"op": "eq", "values": v}
                elif d == "taste":
                    params[d] = {"op": "contains", "values": v}
                else:
                    params[d] = {"op": "in", "values": [v] if isinstance(v, str) else v}

        # distance sampled
        params["distance"] = self.distance_sampler.sample_distance_param(is_negative=negative)

        # Negative modulation: force a not_in for taste if reject
        if negative and negative_type == "reject" and params.get("taste"):
            # Append a not_in dimension
            taste_list = params["taste"].get("values", [])
            if taste_list:
                # Pick one taste to forbid
                forbidden = self._rng.choice(taste_list)
                params["taste"] = {"op": "not_in", "values": [forbidden]}

        return params

    def _force_target_dim(self, item: ItemTags, missing_dim: str) -> dict:
        params: dict = {d: None for d in DIM_ORDER}
        v = item.tags.get(missing_dim)
        if v is None:
            return params
        if missing_dim == "consumable_type":
            params[missing_dim] = {"op": "eq", "values": v}
        elif missing_dim == "taste":
            params[missing_dim] = {"op": "contains", "values": v}
        else:
            params[missing_dim] = {"op": "in", "values": [v] if isinstance(v, str) else v}
        return params

    def _generate_one(
        self,
        *,
        item: ItemTags,
        target_intent: str,
        target_params: dict,
        target_order_by: Optional[str],
        target_turns: int,
        negative: bool,
        negative_type: Optional[str],
        template: str,
        forced: bool,
        covered_dims_override: Optional[list[str]] = None,
    ) -> Optional[SFTSample]:
        item_tags_dict = {"item_id": item.item_id, "tags": item.tags, "item_type": item.item_type.value}
        messages, covered = self.llm_generator.generate(
            item_tags_dict=item_tags_dict,
            target_intent=target_intent,
            target_params=target_params,
            target_order_by=target_order_by,
            target_turns=target_turns,
            negative_type=negative_type,
            sentence_template=template,
            item_id=item.item_id,
        )
        if covered_dims_override:
            covered = list(set(covered) | set(covered_dims_override))
        sample = SFTSample(
            item_id=item.item_id,
            item_type=item.item_type,
            intent=target_intent,
            messages=messages,
            params=target_params,
            order_by=target_order_by,
            negative=negative,
            negative_type=negative_type,
            covered_dims=covered,
            forced_coverage=forced,
            generated_at=datetime.utcnow(),
            llm_model=self.llm_generator.model_name,
        )
        ok, errs = validate_sft_sample(sample, self.config.dim_dictionary, max_turns=self.max_message_turns)
        if not ok:
            self.summary.sft_failures += 1
            self.failures.append(
                SFTFailure(
                    item_id=item.item_id,
                    raw_response=None,
                    target_params=target_params,
                    error="DictValidation",
                    error_detail="; ".join(errs),
                )
            )
            return None
        # Defensive: trim messages to max_turns if LLM returned longer
        if len(sample.messages) > self.max_message_turns:
            sample.messages = sample.messages[: self.max_message_turns]
        return sample

    def _self_check(self, items: list[ItemTags], samples: list[SFTSample]) -> None:
        # SC-005: per-item union covers all non-null dims
        per_item: dict[str, set[str]] = {}
        for s in samples:
            per_item.setdefault(s.item_id, set()).update(s.covered_dims)
        all_pass = True
        for it in items:
            target = set(get_non_null_dims(it))
            covered = per_item.get(it.item_id, set())
            if not target.issubset(covered):
                all_pass = False
                logger.warning(
                    "coverage_failure",
                    extra={
                        "stage": "sft",
                        "item_id": it.item_id,
                        "missing": sorted(target - covered),
                    },
                )
        self.summary.coverage_pass = all_pass


__all__ = ["SFTPipeline", "SFTSummary"]