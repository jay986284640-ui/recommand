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
        self._first_write = True

    def write(self, samples: Iterable[ItemTags]) -> int:
        """Write items, truncating the file on first call (per pipeline run)."""
        mode = "w" if self._first_write else "a"
        self._first_write = False
        n = 0
        with self._path.open(mode, encoding="utf-8") as f:
            for sample in samples:
                obj = sample.to_jsonl_dict()
                assert obj["_format_version"] == ITEM_TAGS_V
                f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
                n += 1
        return n

    def reset(self) -> None:
        """Reset the first-write flag (e.g. for a fresh pipeline run)."""
        self._first_write = True


__all__ = ["ItemTagsWriter"]