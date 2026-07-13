"""SFTPipeline — Stage 3 orchestrator.

Reads item_tags.jsonl + dim_dictionary_snapshot.yaml → for each item:
  1. Plan N samples (turns + covered_dims)
  2. Assign intent (item_type biased)
  3. Decide if negative (3 types)
  4. Build target_params from item.tags + passthrough fields
  5. Coverage planner: ensure each dict value appears in 包含/not_in scenarios
  6. LLM generate → validate → write
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

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
from .llm_generator import LLMGenerator, build_field_definitions
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
    coverage_positive: int = 0
    coverage_negative: int = 0
    coverage_pass: bool = False
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    finished_at: Optional[str] = None


# Passthrough columns from tables.yaml that supplement AI-inferred dimensions
_PASSTHROUGH_FIELDS = ["distance", "avg_prc", "store_name"]


class SFTPipeline:
    def __init__(
        self,
        config: Config,
        llm_client: LLMClient,
        input_path: str | Path,
        output_dir: str | Path,
        *,
        prompt_template_path: str | Path | None = None,
        dict_snapshot_path: str | Path | None = None,
        tables_config_path: str | Path | None = None,
        count_per_item: int = 8,
        max_message_turns: int = 5,
        negative_ratio: float = 0.10,
        coverage_min_samples_per_value: int = 2,
        coverage_positive_ratio: float = 0.6,
    ) -> None:
        self.config = config
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.count_per_item = count_per_item
        self.max_message_turns = max_message_turns
        self.negative_ratio = negative_ratio
        self.coverage_min = coverage_min_samples_per_value
        self.coverage_pos_ratio = coverage_positive_ratio
        self.summary = SFTSummary()

        # Prompt template
        if prompt_template_path is None:
            pt = Path(__file__).resolve().parent.parent.parent / "configs" / "prompts" / "sft_v1.txt"
        else:
            pt = Path(prompt_template_path)
        self.prompt_template = pt.read_text(encoding="utf-8") if pt.exists() else ""

        # Load dim dictionary snapshot
        if dict_snapshot_path:
            self.dim_dict = yaml.safe_load(Path(dict_snapshot_path).read_text(encoding="utf-8")) or {}
        else:
            self.dim_dict = config.dim_dictionary

        # Discover llm-inferred dims from snapshot (non-_meta keys with "values" list)
        self._llm_dims = sorted(
            k for k in self.dim_dict
            if not k.startswith("_")
            and isinstance(self.dim_dict[k], dict)
            and "values" in self.dim_dict[k]
        )

        # Build dynamic field definitions
        self.field_definitions = build_field_definitions(self.dim_dict, _PASSTHROUGH_FIELDS)

        # Extract dict values per dimension
        self._dict_values: dict[str, list] = {}
        for d in self._llm_dims:
            self._dict_values[d] = list((self.dim_dict[d] or {}).get("values", []) or [])

        # RNG
        self._rng = random.Random(42)

        # Sub-samplers
        self.distance_sampler = DistanceSampler(self._rng)
        self.negative_sampler = NegativeSampler(self._rng, negative_ratio=negative_ratio)
        self.diversity_sampler = DiversitySampler(self._rng)
        self.intent_assigner = IntentAssigner(self._rng)
        self.sample_planner = SamplePlanner(
            count_per_item=count_per_item, max_turns=max_message_turns
        )
        self.llm_generator = LLMGenerator(
            llm_client, self.prompt_template, self.field_definitions
        )

        # Writers
        self.writer = SFTSampleWriter(self.output_dir / "sft_corpus.jsonl")
        self.failures = SFTFailureWriter(self.output_dir / "sft_failures.jsonl")

        # Coverage tracking
        self._cov_positive: dict[str, set] = defaultdict(set)  # dim -> {values covered}
        self._cov_negative: dict[str, set] = defaultdict(set)

    # ---- main ----------------------------------------------------------

    def run(self) -> SFTSummary:
        items = self._load_items()

        # Phase A: per-item generation (existing logic with order_by removed)
        all_samples: list[SFTSample] = []
        for it in items:
            samples = self._process_item(it)
            all_samples.extend(samples)

        # Phase B: coverage-driven samples (包含/不包含)
        cov_samples = self._generate_coverage_samples(items, all_samples)
        all_samples.extend(cov_samples)

        self.writer.write(all_samples)

        # Self-check
        self._self_check(items, all_samples)
        self.summary.total = len(all_samples)
        self.summary.intent_distribution = self.intent_assigner.distribution
        self.summary.coverage_positive = sum(len(v) for v in self._cov_positive.values())
        self.summary.coverage_negative = sum(len(v) for v in self._cov_negative.values())
        self.summary.finished_at = datetime.utcnow().isoformat() + "Z"

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

    # ---- coverage planner -----------------------------------------------

    def _generate_coverage_samples(
        self, items: list[ItemTags], existing: list[SFTSample]
    ) -> list[SFTSample]:
        """Ensure every dictionary value is covered in both 包含 / not_in scenarios."""
        # Track what's already covered
        for s in existing:
            for dim, constraints in s.params.items():
                if not constraints or dim not in self._dict_values:
                    continue
                for c in constraints:
                    op = c.get("op", "")
                    vals = c.get("values", [])
                    if op == "contains":
                        for v in vals:
                            self._cov_positive[dim].add(v)
                    elif op == "not_in":
                        for v in vals:
                            self._cov_negative[dim].add(v)

        samples: list[SFTSample] = []

        for dim in self._llm_dims:
            dict_vals = self._dict_values.get(dim, [])
            if not dict_vals:
                continue

            # Positive coverage: value IS constrained
            for val in dict_vals:
                if val in self._cov_positive[dim]:
                    continue
                item = self._find_item_with_dim(items, dim, val)
                if item is None:
                    continue
                sample = self._make_coverage_sample(item, dim, val, op="contains")
                if sample:
                    samples.append(sample)
                    self._cov_positive[dim].add(val)

            # Negative coverage: value is explicitly EXCLUDED (反选)
            for val in dict_vals:
                if val in self._cov_negative[dim]:
                    continue
                item = self._find_item_for_negative(items, dim, val)
                if item is None:
                    continue
                sample = self._make_coverage_sample(item, dim, val, op="not_in")
                if sample:
                    samples.append(sample)
                    self._cov_negative[dim].add(val)

        return samples

    def _find_item_with_dim(
        self, items: list[ItemTags], dim: str, val: str
    ) -> Optional[ItemTags]:
        """Find an item whose tag for *dim* equals *val* (for 包含)."""
        candidates = []
        for it in items:
            tag_val = it.tags.get(dim)
            if tag_val is None:
                continue
            if isinstance(tag_val, list):
                if val in tag_val:
                    candidates.append(it)
            elif str(tag_val) == val:
                candidates.append(it)
        return self._rng.choice(candidates) if candidates else None

    def _find_item_for_negative(
        self, items: list[ItemTags], dim: str, val: str
    ) -> Optional[ItemTags]:
        """Find an item that does NOT have *val* for *dim* (for 反选)."""
        candidates = []
        for it in items:
            tag_val = it.tags.get(dim)
            if tag_val is None:
                candidates.append(it)
                continue
            if isinstance(tag_val, list):
                if val not in tag_val:
                    candidates.append(it)
            elif str(tag_val) != val:
                candidates.append(it)
        return self._rng.choice(candidates) if candidates else None

    def _make_coverage_sample(
        self, item: ItemTags, dim: str, val: str, op: str
    ) -> Optional[SFTSample]:
        """Generate a single coverage sample for (dim, val, op)."""
        params: dict = {d: None for d in DIM_ORDER}
        params[dim] = [{"op": op, "values": [val]}]

        # Add distance for realism
        dist = self.distance_sampler.sample_distance_param(is_negative=(op == "not_in"))
        if dist is not None:
            params["distance"] = [dist]

        try:
            return self._generate_one(
                item=item,
                target_intent="search_item",
                target_params=params,
                target_turns=2,
                negative=(op == "not_in"),
                negative_type=None,
                template="direct_first",
                forced=True,
                covered_dims_override=[dim],
            )
        except Exception as e:
            self.summary.sft_failures += 1
            self.failures.append(
                SFTFailure(
                    item_id=item.item_id,
                    raw_response=None,
                    target_params=params,
                    error="CoverageFailure",
                    error_detail=str(e),
                )
            )
            return None

    # ---- item loading --------------------------------------------------

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
                        f"item_tags version mismatch: expected item_tags_v2, "
                        f"got {rec.get('_format_version')}"
                    )
                items.append(
                    ItemTags(
                        item_id=rec["item_id"],
                        item_type=Role(rec["item_type"]),
                        raw_record=rec.get("raw_record", {}),
                        tags=rec["tags"],
                        tag_source=None,
                        enriched_at=datetime.utcnow(),
                        llm_model=rec.get("llm_model", ""),
                    )
                )
        return items

    # ---- per-item processing -------------------------------------------

    def _process_item(self, item: ItemTags) -> list[SFTSample]:
        self.diversity_sampler.reset(item.item_id)

        turn_counts = self.sample_planner.plan_turn_distribution(
            n_samples=self.count_per_item, rng=self._rng
        )
        intents = self.intent_assigner.assign(item.item_type, count_per_item=self.count_per_item)

        item_samples: list[SFTSample] = []
        for i in range(self.count_per_item):
            negative = self.negative_sampler.is_negative()
            negative_type = self.negative_sampler.pick_type() if negative else None
            target_params = self._build_target_params(item, negative, negative_type)
            template = self.diversity_sampler.pick_template(item.item_id)
            target_turns = turn_counts[i]

            try:
                sample = self._generate_one(
                    item=item,
                    target_intent=intents[i],
                    target_params=target_params,
                    target_turns=target_turns,
                    negative=negative,
                    negative_type=negative_type,
                    template=template,
                    forced=False,
                )
                if sample is not None:
                    item_samples.append(sample)
            except Exception as e:
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

        # Force cover remaining non-null dims
        covered = set()
        for s in item_samples:
            covered.update(s.covered_dims)
        target_dims = set(get_non_null_dims(item))
        uncovered = target_dims - covered
        if uncovered:
            for missing_dim in list(uncovered):
                try:
                    target_params = self._force_target_dim(item, missing_dim)
                    sample = self._generate_one(
                        item=item,
                        target_intent="search_item",
                        target_params=target_params,
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
                except Exception as e:
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

    # ---- param building ------------------------------------------------

    def _build_target_params(
        self, item: ItemTags, negative: bool, negative_type: Optional[str]
    ) -> dict:
        """Build target params from item tags.

        LLM-inferred dims use ``contains`` op.
        Passthrough fields (distance, avg_prc) are sampled or derived.
        No order_by.
        """
        params: dict = {d: None for d in DIM_ORDER}

        for d in self._llm_dims:
            if d not in DIM_ORDER:
                continue
            v = item.tags.get(d)
            if v is None:
                continue
            if isinstance(v, list):
                params[d] = [{"op": "contains", "values": v}]
            else:
                params[d] = [{"op": "contains", "values": [v]}]

        # distance: sampled (numeric)
        dist = self.distance_sampler.sample_distance_param(is_negative=negative)
        if dist is not None:
            params["distance"] = [dist]

        # avg_prc: numeric range
        raw_price = item.tags.get("avg_prc")
        if raw_price is not None and params.get("avg_prc"):
            try:
                p = int(raw_price)
                params["avg_prc"] = [{"op": "between", "values": [max(0, p - 10), p + 10]}]
            except (ValueError, TypeError):
                pass

        # store_name: fuzzy text search fallback (15% of samples)
        if self._rng.random() < self.coverage_pos_ratio * 0.25:
            raw_name = item.raw_record.get("str_nm") or item.raw_record.get("shopname") or ""
            if raw_name:
                # Clean: strip location markers for partial match
                import re
                cleaned = re.sub(r"[（(][^）)]*[）)]", "", str(raw_name)).strip()
                if cleaned:
                    params["store_name"] = [{"op": "contains", "values": [cleaned]}]

        return params

    def _force_target_dim(self, item: ItemTags, missing_dim: str) -> dict:
        params: dict = {d: None for d in DIM_ORDER}
        v = item.tags.get(missing_dim)
        if v is None:
            return params
        if isinstance(v, list):
            params[missing_dim] = [{"op": "contains", "values": v}]
        else:
            params[missing_dim] = [{"op": "contains", "values": [v]}]
        return params

    # ---- generation ----------------------------------------------------

    def _generate_one(
        self,
        *,
        item: ItemTags,
        target_intent: str,
        target_params: dict,
        target_turns: int,
        negative: bool,
        negative_type: Optional[str],
        template: str,
        forced: bool,
        covered_dims_override: Optional[list[str]] = None,
    ) -> Optional[SFTSample]:
        item_name = str(item.raw_record.get("str_nm") or item.raw_record.get("shopname") or "")
        messages, guide_text = self.llm_generator.generate(
            target_params=target_params,
            target_turns=target_turns,
            item_name=item_name,
            item_id=item.item_id,
        )
        covered = list({
            k for k, v in target_params.items()
            if v is not None and k not in ("distance",)
        })
        if covered_dims_override:
            covered = list(set(covered) | set(covered_dims_override))
        sample = SFTSample(
            item_id=item.item_id,
            item_type=item.item_type,
            intent=target_intent,
            messages=messages,
            params=target_params,
            guide_text=guide_text,
            order_by=None,
            negative=negative,
            negative_type=negative_type,
            covered_dims=covered,
            forced_coverage=forced,
            generated_at=datetime.utcnow(),
            llm_model=self.llm_generator.model_name,
        )
        ok, errs = validate_sft_sample(sample, self.dim_dict, max_turns=self.max_message_turns)
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
        if len(sample.messages) > self.max_message_turns:
            sample.messages = sample.messages[: self.max_message_turns]
        return sample

    # ---- self-check ----------------------------------------------------

    def _self_check(self, items: list[ItemTags], samples: list[SFTSample]) -> None:
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
