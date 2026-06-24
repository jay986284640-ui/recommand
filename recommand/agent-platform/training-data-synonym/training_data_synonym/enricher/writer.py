"""Stage 1 main writer — item_tags_v2.jsonl.

Fixed 8-dim tag order (DIM_ORDER); _format_version = item_tags_v2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ..common.versioning import ITEM_TAGS_V
from ..data_model import ItemTags


class ItemTagsWriter:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, samples: Iterable[ItemTags]) -> int:
        n = 0
        with self._path.open("w", encoding="utf-8") as f:
            for sample in samples:
                obj = sample.to_jsonl_dict()
                # Validate _format_version
                assert obj["_format_version"] == ITEM_TAGS_V
                f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
                n += 1
        return n


__all__ = ["ItemTagsWriter"]