"""cold_start — Stage 1 8-dim all-null items.

Per spec Edge Cases + T085 — these items are excluded from Stage 2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ..data_model import ItemTags


def is_cold_start(item: ItemTags) -> bool:
    """True if every dim in ItemTags.tags is None (per DIM_ORDER)."""
    from ..data_model import DIM_ORDER
    return all(item.tags.get(d) is None for d in DIM_ORDER if d != "distance")


class ColdStartWriter:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, items: Iterable[ItemTags]) -> int:
        n = 0
        with self._path.open("w", encoding="utf-8") as f:
            for it in items:
                if is_cold_start(it):
                    f.write(
                        json.dumps(
                            {"item_id": it.item_id, "item_type": it.item_type.value},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    n += 1
        return n


__all__ = ["is_cold_start", "ColdStartWriter"]