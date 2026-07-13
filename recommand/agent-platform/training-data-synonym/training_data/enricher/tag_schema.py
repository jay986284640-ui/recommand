"""tag_schema — ItemTags construction helpers (per data-model.md §实体 4,5).

Provides an `assemble` factory that takes raw_record + per-dim results
and produces an ItemTags with valid TagSource invariants:
  tag == None  ⇔  tag_source == missing
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..data_model import DIM_ORDER, ItemTags, Role, TagOrigin, TagSource


def assemble_item_tags(
    item_id: str,
    item_type: Role,
    raw_record: dict,
    tags: dict[str, Optional[Any]],
    sources: dict[str, TagOrigin],
    *,
    llm_model: str = "mock-llm",
) -> ItemTags:
    """Build ItemTags enforcing `tag == None ⇔ source == missing` invariant.

    Special case: `distance` is ALWAYS null at Stage 1 (no user known),
    even when source is `geo`. The invariant therefore does NOT apply to
    distance — source can be `geo` while value is null.

    Falls back to TagOrigin.MISSING for the other 7 dims when source
    indicates raw/derived but value is None (defensive).
    """
    fixed_sources: dict[str, TagOrigin] = {}
    for dim in DIM_ORDER:
        v = tags.get(dim)
        src = sources.get(dim, TagOrigin.MISSING)
        if dim != "distance" and v is None and src != TagOrigin.MISSING:
            src = TagOrigin.MISSING
        fixed_sources[dim] = src

    tag_source = TagSource(**fixed_sources)

    return ItemTags(
        item_id=item_id,
        item_type=item_type,
        raw_record=raw_record,
        tags={k: tags.get(k) for k in DIM_ORDER},
        tag_source=tag_source,
        enriched_at=datetime.utcnow(),
        llm_model=llm_model,
    )


__all__ = ["assemble_item_tags"]