"""EnrichmentPipeline — Stage 1 orchestrator (per FR-001 ~ FR-009 + plan T046).

Reads 3 core tables via HiveReader → for each row:
  - distance_geo (no LLM)
  - consumable_mapper (map → LLM fallback)
  - llm_enricher (6 dims, LLM fallback only)
Assembles ItemTags, enforces `tag == null ⇔ source == missing` invariant,
emits item_tags.jsonl + failures + state + cold_start + summary.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

import yaml

from ..common.config import Config
from ..common.llm_client import LLMClient
from ..common.logging import get_logger
from ..common.tables_config import (
    TablesConfigError,
    derive_sensitive_blocklist,
    load_tables_config,
)
from ..data_model import (
    DIM_ORDER,
    HiveReadSpec,
    ItemTags,
    Role,
    TagOrigin,
)
from ..hive_reader.base import HiveReader
from .consumable_mapper import ConsumableMapper
from .distance_geo import extract_distance_tag
from .failures import EnrichmentFailure, EnrichmentFailureWriter
from .llm_enricher import LLMEnricher
from .state import EnrichmentStateRow, EnrichmentStateStore, compute_raw_md5
from .tag_schema import assemble_item_tags
from .profile_writer import write_item_profile
from .writer import ItemTagsWriter

logger = get_logger(__name__)


# no-op context manager for single-threaded path
class _NoopLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


@dataclass
class EnrichmentSummary:
    items_processed: int = 0
    items_enriched: int = 0
    items_cold_start: int = 0
    items_skipped_cached: int = 0
    llm_calls: int = 0
    llm_failures: int = 0
    dict_pass_rate: float = 0.0
    coverage_avg: float = 0.0
    dict_rejected_count: int = 0
    sc_pass: dict[str, bool] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    finished_at: Optional[str] = None


class EnrichmentPipeline:
    def __init__(
        self,
        config: Config,
        *,
        tables_config_path: str | Path | None = None,
        sql_path: str | Path | None = None,
        hive_reader: HiveReader,
        llm_client: LLMClient,
        output_dir: str | Path,
        prompt_template_path: str | Path | None = None,
        constrain_to_dict: bool = True,
        sample_n_per_type: int | None = None,
    ) -> None:
        """Stage 1/2 orchestrator.

        Args:
            constrain_to_dict: Stage 1 = False (LLM freely infers),
                Stage 2 = True (dictionary-constrained).
            sample_n_per_type: Max rows per table to read.  Takes precedence
                over ``pipeline.yaml``.  ``None`` means read all rows.
        """
        if tables_config_path is None and sql_path is None:
            raise ValueError("EnrichmentPipeline requires either tables_config_path= or sql_path=")

        self.config = config
        # Track both for diagnostic purposes; the loader chosen below.
        self.tables_config_path = Path(tables_config_path) if tables_config_path else None
        self.sql_path = Path(sql_path) if sql_path else None
        self._use_legacy_sql = sql_path is not None
        self._constrain_to_dict = constrain_to_dict
        self._sample_n_per_type = sample_n_per_type

        self.hive = hive_reader
        self.llm = llm_client
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.summary = EnrichmentSummary()

        # Load prompt template
        if prompt_template_path is None:
            pt = (
                Path(__file__).resolve().parent.parent.parent
                / "configs"
                / "prompts"
                / "enrichment_v1.txt"
            )
        else:
            pt = Path(prompt_template_path)
        self.prompt_template = pt.read_text(encoding="utf-8") if pt.exists() else ""

        # Setup downstream services
        self.consumable_mapper = ConsumableMapper(
            self.config.consumable_type_map,
            llm_client=self.llm,
            category_values=(self.config.dim_dictionary.get("category") or {}).get("values", [])
            or [],
        )
        # Read LLM inference config from tables.yaml _meta
        raw_yaml = yaml.safe_load(self.tables_config_path.read_text(encoding="utf-8")) or {}
        inference_config = (raw_yaml.get("_meta") or {}).get("llm_inference") or [
            {"field": "category", "desc": "品类", "multiple": False},
            {"field": "brand", "desc": "品牌", "multiple": False},
            {"field": "taste", "desc": "口味", "multiple": True},
            {"field": "cuisine", "desc": "菜系", "multiple": False},
            {"field": "occasion", "desc": "场合", "multiple": False},
            {"field": "consumable_type", "desc": "食饮类型", "multiple": False},
        ]
        # Extract field names for profile writer (config-driven, not hardcoded)
        self._llm_dim_fields: set[str] = {
            item["field"] for item in inference_config if isinstance(item, dict) and "field" in item
        }
        # Build: role → {column names} from tables.yaml (replaces field_contract)
        self._table_columns: dict[str, set[str]] = {}
        for t in raw_yaml.get("tables") or []:
            role = (t.get("role") or "").lower()
            self._table_columns[role] = {
                str(c["name"]) for c in (t.get("columns") or [])
                if isinstance(c, dict) and c.get("name")
            }

        self.llm_enricher = LLMEnricher(
            llm_client=self.llm,
            inference_config=inference_config,
            dictionary=self.config.dim_dictionary,
            prompt_template=self.prompt_template,
            constrain_to_dict=getattr(self, "_constrain_to_dict", True),
        )

        # Writers
        self.writer = ItemTagsWriter(self.output_dir / "item_tags.jsonl")
        self.failures = EnrichmentFailureWriter(self.output_dir / "tag_enrichment_failures.jsonl")
        self.state = EnrichmentStateStore(self.output_dir / "tag_enrichment_state.jsonl")
        # Counters for Part B: dict-rejection observability.
        # LLMEnricher / ConsumableMapper expose .rejection_count that grows
        # monotonically across calls; we subtract the last-seen snapshot to
        # compute per-item deltas.
        self._last_llm_rej: int = 0
        self._last_ct_rej: int = 0

        # Sensitive blocklist: derived from tables.yaml sensitive flags so
        # we no longer depend on a hard-coded list in data_model.py. For
        # legacy --sql path, fall back to the hard-coded blocklist.
        if self._use_legacy_sql:
            self._sensitive_blocklist = [
                "MASTERCARD_CUST_ID",
                "Crt_Psn_Id",
                "Updt_Psn_Id",
                "Opr_Psn_Id",
                "creator",
                "updatePerson",
            ]
        else:
            try:
                raw_yaml = yaml.safe_load(self.tables_config_path.read_text(encoding="utf-8")) or {}
            except FileNotFoundError as e:
                raise TablesConfigError(
                    f"tables config not found: {self.tables_config_path}"
                ) from e
            except (OSError, yaml.YAMLError) as e:
                raise TablesConfigError(
                    f"failed to load tables config {self.tables_config_path}: {e}"
                ) from e
            self._sensitive_blocklist = derive_sensitive_blocklist([], raw_yaml=raw_yaml)

    def run(self) -> EnrichmentSummary:
        # 1. Load tables (YAML preferred; legacy SQL DDL parsing supported).
        if self._use_legacy_sql:
            from ..sql_parser.parser import parse_sql

            tables_meta = parse_sql(self.sql_path)
        else:
            try:
                tables_meta = load_tables_config(self.tables_config_path)
            except TablesConfigError as e:
                raise TablesConfigError(str(e)) from e
        tables_meta_path = self.output_dir / "tables_meta.json"  # no longer written

        # 2. Filter by item_types from pipeline.yaml (default: all configured tables)
        input_cfg = (self.config.pipeline.get("training_data_synonym") or {}).get("input") or {}
        types_str = input_cfg.get("item_types") or [t.inferred_role.value for t in tables_meta]
        target_roles = {getattr(Role, t.upper(), None) for t in types_str}
        target_roles.discard(None)
        core_tables = [t for t in tables_meta if t.inferred_role in target_roles]
        if not core_tables:
            raise RuntimeError(f"No tables found for item_types={types_str}")

        # 3. Stream-read + enrich in batches to keep peak memory bounded.
        #    Each batch: read N rows → enrich concurrently → persist → next batch.
        # sample_n_per_type: constructor arg > pipeline.yaml > None (all rows)
        if self._sample_n_per_type is not None:
            sample_n = self._sample_n_per_type
        else:
            yaml_sample = (
                (self.config.pipeline.get("training_data_synonym") or {}).get("input") or {}
            ).get("hive") or {}
            sample_n = yaml_sample.get("sample_n_per_type") or None

        enrichment_cfg = (self.config.pipeline.get("training_data_synonym") or {}).get(
            "enrichment"
        ) or {}
        concurrency = int(enrichment_cfg.get("concurrency") or 4)
        batch_size = int(enrichment_cfg.get("batch_size") or 500)
        lock = Lock()

        # Per-batch write: flush items to disk after each batch so peak
        # memory stays at O(batch_size) rather than O(total_rows).
        self.writer.reset()
        total_enriched = 0
        total_rows = 0
        # Accumulate coverage stats incrementally (avoid buffering all ItemTags)
        coverage_sum: float = 0.0
        coverage_count: int = 0
        batch: list = []  # list[RawRecord]
        profile_items: list = []  # profile writer still needs all items

        for tm in core_tables:
            spec = HiveReadSpec(
                source="hive",
                sample_n_per_type=sample_n,
                sensitive_columns_blocklist=list(self._sensitive_blocklist),
            )
            table_rows = 0
            for raw_rec in self.hive.read(tm, spec):
                self.summary.items_processed += 1
                batch.append(raw_rec)
                table_rows += 1
                total_rows += 1

                if len(batch) >= batch_size:
                    enriched = self._enrich_batch(batch, lock, concurrency)
                    n = self.writer.write(enriched)
                    total_enriched += n
                    profile_items.extend(enriched)
                    # Track coverage incrementally
                    for it in enriched:
                        non_null = sum(
                            1 for d in DIM_ORDER if d != "distance" and it.tags.get(d) is not None
                        )
                        coverage_sum += non_null
                        coverage_count += 1
                    print(
                        f"  [enrich] {total_rows} rows read, "
                        f"{total_enriched} enriched "
                        f"(batch size={batch_size}, concurrency={concurrency})"
                    )
                    batch = []

            # Flush remaining rows for this table
            if batch:
                enriched = self._enrich_batch(batch, lock, concurrency)
                n = self.writer.write(enriched)
                total_enriched += n
                profile_items.extend(enriched)
                for it in enriched:
                    non_null = sum(
                        1 for d in DIM_ORDER if d != "distance" and it.tags.get(d) is not None
                    )
                    coverage_sum += non_null
                    coverage_count += 1
                batch = []

            print(f"  [enrich] {tm.table_name} ({tm.inferred_role.value}): {table_rows} rows")

        if total_enriched == 0 and total_rows == 0:
            print(
                "  [enrich] WARNING: 0 rows loaded from all tables — "
                "check --csv-dir / table config / pipeline.yaml item_types"
            )
            return self.summary

        # 4. Persist item_profile.jsonl (keep this — core output)
        write_item_profile(
            profile_items,
            self.output_dir / "item_profile.jsonl",
            llm_dims=self._llm_dim_fields,
            allowed_fields=self._table_columns,
        )
        self.state.flush()

        # Cold-start tracking skipped (simplified output)

        # 5. SC self-check (incremental stats)
        self.summary.coverage_avg = coverage_sum / coverage_count if coverage_count > 0 else 0.0
        total_calls = max(self.summary.llm_calls, 1)
        self.summary.dict_pass_rate = round(
            1.0 - (self.summary.dict_rejected_count / total_calls), 4
        )
        self.summary.sc_pass = {
            "SC-001": True,
            "SC-002": self.summary.dict_pass_rate == 1.0,
            "SC-003": self.summary.coverage_avg >= 6.5,
        }

        self.summary.items_enriched = total_enriched
        self.summary.finished_at = datetime.utcnow().isoformat() + "Z"

        # summary.json no longer written here — CLI consolidates into llm_stats.json

        return self.summary

    # ---- internal -------------------------------------------------------

    def _enrich_batch(self, batch: list, lock: Lock, concurrency: int) -> list[ItemTags]:
        """Enrich a batch of RawRecords concurrently, return enriched ItemTags."""
        if concurrency <= 1:
            items = []
            for r in batch:
                item = self._enrich_one(r, lock)
                if item:
                    items.append(item)
            return items

        items: list[ItemTags] = []
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(self._enrich_one, r, lock): r for r in batch}
            for fut in as_completed(futures):
                item = fut.result()
                if item:
                    items.append(item)
        return items

    def _enrich_one(self, raw_rec, lock: Optional[Lock] = None) -> Optional[ItemTags]:
        """Enrich one RawRecord → ItemTags or None (cached skip).

        ``lock`` guards thread-safe counter updates when concurrency > 1.
        """
        raw = raw_rec.raw
        raw_md5 = compute_raw_md5(raw)
        # Cache check
        if not self.state.needs_recompute(
            raw_rec.item_id, raw_md5, self.config.dict_version, raw_rec.etl_dt
        ):
            with lock or _NoopLock():
                self.summary.items_skipped_cached += 1
            return None

        sources: dict[str, TagOrigin] = {}
        tags: dict[str, Optional[object]] = {d: None for d in DIM_ORDER}

        # 1. distance_geo (no LLM)
        d_val, d_src = extract_distance_tag(raw_rec.item_type, raw_rec.shop_lng, raw_rec.shop_lat)
        tags["distance"] = d_val
        sources["distance"] = d_src

        # 2. consumable_type — needs category first; defer; placeholder, will fill below
        #    Will be set after we get category from llm_enricher
        sources["consumable_type"] = TagOrigin.MISSING  # temporary

        # 3. LLM enricher (fields defined by config)
        enriched = self.llm_enricher.enrich(raw, item_id=raw_rec.item_id)
        with lock or _NoopLock():
            self.summary.llm_calls += 1
        for item in self.llm_enricher._config:
            dim = item["field"]
            v = enriched.get(dim)
            tags[dim] = v
            if v is not None:
                sources[dim] = (
                    TagOrigin.AI if self._is_ai_dim_source(dim, raw, v) else TagOrigin.RAW
                )

        # avg_prc: use raw column with same name; fall back to common aliases
        avg_val = self._bucket_price(raw, "avg_prc")
        if avg_val is None:
            # Fallback: some tables use alternative column names for price
            for alt in ("mnt_pern_usr_num", "faceprice"):
                avg_val = self._bucket_price(raw, alt)
                if avg_val is not None:
                    break
        tags["avg_prc"] = avg_val
        sources["avg_prc"] = TagOrigin.RAW if avg_val else TagOrigin.MISSING

        # 3b. Part B: capture LLM-enricher dict rejections (per-item delta).
        # llm_enricher.rejection_count is cumulative across all calls; the
        # delta since the previous call tells us how many dims THIS item
        # had silently dropped. We sum into summary.dict_rejected_count and
        # write a single EnrichmentFailure row per item (aggregated details).
        rej_total = self.llm_enricher.rejection_count
        with lock or _NoopLock():
            delta = max(0, rej_total - self._last_llm_rej)
            self._last_llm_rej = rej_total
            if delta > 0:
                self.summary.dict_rejected_count += delta
                self.failures.append(
                    EnrichmentFailure(
                        item_id=raw_rec.item_id,
                        raw_response=None,
                        error="dict_rejection",
                        error_detail=json.dumps(
                            self.llm_enricher.rejection_log[-delta:],
                            ensure_ascii=False,
                        ),
                    )
                )

        # 4. consumable_type mapping (uses category from above)
        ct_val, ct_src = self.consumable_mapper.map(
            category=tags.get("category"),
            item_id=raw_rec.item_id,
            raw_record=raw,
        )
        tags["consumable_type"] = ct_val
        sources["consumable_type"] = ct_src

        # 4b. Part B: capture consumable_mapper rejections
        with lock or _NoopLock():
            ct_rej_total = self.consumable_mapper.rejection_count
            ct_delta = max(0, ct_rej_total - self._last_ct_rej)
            self._last_ct_rej = ct_rej_total
            self.summary.dict_rejected_count += ct_delta

        # 5. assemble (enforces invariant)
        item = assemble_item_tags(
            item_id=raw_rec.item_id,
            item_type=raw_rec.item_type,
            raw_record=raw,
            tags=tags,
            sources=sources,
            llm_model=self.llm.model_name,
        )

        # 6. update state
        self.state.upsert(
            EnrichmentStateRow(
                item_id=raw_rec.item_id,
                raw_md5=raw_md5,
                dict_version=self.config.dict_version,
                source_partition=raw_rec.etl_dt,
                enriched_at=item.enriched_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                llm_model=self.llm.model_name,
            )
        )

        return item

    @staticmethod
    def _bucket_price(raw: dict, col: str) -> Optional[str]:
        """Bucket a single raw column into price range."""
        val = raw.get(col)
        if val is None:
            return None
        try:
            avg = float(val)
        except (TypeError, ValueError):
            return None
        if avg <= 0:
            return None
        if avg <= 30:
            return "0-30"
        if avg <= 50:
            return "30-50"
        if avg <= 100:
            return "50-100"
        if avg <= 200:
            return "100-200"
        return "200+"

    def _is_ai_dim_source(self, dim: str, raw: dict, value) -> bool:
        """Heuristic: source = raw if value matches raw column; else ai."""
        if dim == "brand":
            raw_candidates = [raw.get("brnd_nm"), raw.get("str_nm"), raw.get("shopname")]
            return value not in [str(c) for c in raw_candidates if c]
        if dim == "category":
            return value != raw.get("cat_nm")
        if dim == "avg_prc":
            try:
                avg_raw = float(raw.get("avg_prc") or raw.get("mnt_pern_usr_num") or -1)
            except (TypeError, ValueError):
                return True
            buckets = [(0, 30), (30, 50), (50, 100), (100, 200), (200, 10**9)]
            for label, (lo, hi) in zip(["0-30", "30-50", "50-100", "100-200", "200+"], buckets):
                if lo <= avg_raw < hi:
                    return value != label
            return True
        return True

    def _self_check(self, items: list[ItemTags]) -> None:
        """SC-002 / SC-003 / SC-001 partial verification."""
        if not items:
            return
        # SC-002 dictionary validity (already enforced in assemble + llm_enricher)
        # SC-003 coverage: average non-null dims per item (distance excluded — always null at stage 1)
        per_item_non_null = []
        for it in items:
            non_null = sum(1 for d in DIM_ORDER if d != "distance" and it.tags.get(d) is not None)
            per_item_non_null.append(non_null)
        self.summary.coverage_avg = sum(per_item_non_null) / len(per_item_non_null)
        # Part B: compute dict_pass_rate from observed rejections instead of
        # hard-coding 1.0. SC-002 stays == 1.0 for the demo because mock LLM
        # outputs are in-vocab; production should adjust the threshold.
        total_calls = max(self.summary.llm_calls, 1)
        self.summary.dict_pass_rate = round(
            1.0 - (self.summary.dict_rejected_count / total_calls), 4
        )

        # SC-001 (3 core tables present) is checked upstream in run()
        self.summary.sc_pass = {
            "SC-001": True,  # core tables found
            "SC-002": self.summary.dict_pass_rate == 1.0,
            "SC-003": self.summary.coverage_avg >= 6.5,  # >=6.5 of 7 enrichable dims
        }


__all__ = ["EnrichmentPipeline", "EnrichmentSummary"]
