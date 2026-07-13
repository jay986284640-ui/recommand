"""Stage 2 failures writer — sft_failures.jsonl.

Per contracts/sft_corpus_v2.md §失败样本 schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class SFTFailure:
    item_id: str
    raw_response: Optional[str]
    target_params: dict
    error: str
    error_detail: str
    occurred_at: datetime = field(default_factory=datetime.utcnow)


class SFTFailureWriter:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, failure: SFTFailure) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "item_id": failure.item_id,
                        "raw_response": failure.raw_response,
                        "target_params": failure.target_params,
                        "error": failure.error,
                        "error_detail": failure.error_detail,
                        "occurred_at": failure.occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


__all__ = ["SFTFailure", "SFTFailureWriter"]