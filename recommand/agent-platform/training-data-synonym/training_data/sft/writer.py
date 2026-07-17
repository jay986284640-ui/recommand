"""Stage 2 main writer — sft_corpus_v2.jsonl.

Per contracts/sft_corpus_v2.md §主样本 schema.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from ..common.versioning import SFT_CORPUS_V
from ..data_model import SFTSample


class SFTSampleWriter:
    def __init__(self, path: str | Path, param_order: tuple[str, ...] | None = None) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._param_order = param_order

    def write(self, samples: Iterable[SFTSample]) -> int:
        n = 0
        with self._path.open("w", encoding="utf-8") as f:
            for sample in samples:
                obj = sample.to_jsonl_dict(self._param_order)
                assert obj["_format_version"] == SFT_CORPUS_V
                f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
                n += 1
        return n


__all__ = ["SFTSampleWriter"]