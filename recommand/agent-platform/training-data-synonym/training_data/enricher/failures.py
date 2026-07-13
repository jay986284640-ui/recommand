"""Stage 1 failures writer (tag_enrichment_failures.jsonl).

Per contracts/item_tags_v2.md §失败样本 schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class EnrichmentFailure:
    item_id: str
    raw_response: str | None
    error: str
    error_detail: str
    occurred_at: datetime = field(default_factory=datetime.utcnow)


class EnrichmentFailureWriter:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, failure: EnrichmentFailure) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "item_id": failure.item_id,
                        "raw_response": failure.raw_response,
                        "error": failure.error,
                        "error_detail": failure.error_detail,
                        "occurred_at": failure.occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


__all__ = ["EnrichmentFailure", "EnrichmentFailureWriter"]