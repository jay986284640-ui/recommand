"""Incremental state for Stage 1 (per FR-006 + research.md D-003).

4-tuple fingerprint: (item_id, raw_md5, dict_version, source_partition).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class EnrichmentStateRow:
    item_id: str
    raw_md5: str
    dict_version: str
    source_partition: str
    enriched_at: str
    llm_model: str


def compute_raw_md5(raw: dict) -> str:
    """Stable md5 of raw record (sort keys for determinism)."""
    payload = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str).encode()
    return hashlib.md5(payload).hexdigest()


class EnrichmentStateStore:
    """Tiny file-based store (parquet in production; jsonl here for fixtures).

    For CI / dev we use a simple JSONL file. Production would swap to PyArrow
    parquet (mentioned in tasks.md T041 — same interface).
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, EnrichmentStateRow] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self._path.exists():
            with self._path.open(encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    row = EnrichmentStateRow(
                        item_id=rec["item_id"],
                        raw_md5=rec["raw_md5"],
                        dict_version=rec["dict_version"],
                        source_partition=rec["source_partition"],
                        enriched_at=rec["enriched_at"],
                        llm_model=rec["llm_model"],
                    )
                    self._cache[row.item_id] = row
        self._loaded = True

    def get(self, item_id: str) -> Optional[EnrichmentStateRow]:
        self._load()
        return self._cache.get(item_id)

    def needs_recompute(
        self,
        item_id: str,
        raw_md5: str,
        dict_version: str,
        source_partition: str,
    ) -> bool:
        self._load()
        existing = self._cache.get(item_id)
        if existing is None:
            return True
        return (
            existing.raw_md5 != raw_md5
            or existing.dict_version != dict_version
            or existing.source_partition != source_partition
        )

    def upsert(self, row: EnrichmentStateRow) -> None:
        self._load()
        self._cache[row.item_id] = row

    def flush(self) -> None:
        """Persist cache to JSONL. (For parquet, swap implementation.)"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as f:
            for row in self._cache.values():
                f.write(
                    json.dumps(
                        {
                            "item_id": row.item_id,
                            "raw_md5": row.raw_md5,
                            "dict_version": row.dict_version,
                            "source_partition": row.source_partition,
                            "enriched_at": row.enriched_at,
                            "llm_model": row.llm_model,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )


__all__ = [
    "EnrichmentStateStore",
    "EnrichmentStateRow",
    "compute_raw_md5",
]