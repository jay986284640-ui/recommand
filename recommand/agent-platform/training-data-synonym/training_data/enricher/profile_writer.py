"""item_profile writer — flat JSONL: declared columns + AI-inferred dims.

Produces ``item_profile.jsonl`` where each line carries the raw columns
declared in tables.yaml ``columns`` plus the AI-inferred dimensions from
``_meta.llm_inference``.

Synthetic fields (type, distance) are intentionally excluded.
``avg_prc`` comes from the raw column, never from AI inference.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..data_model import ItemTags


def write_item_profile(
    items: list[ItemTags],
    path: str | Path,
    *,
    llm_dims: set[str] | None = None,
    allowed_fields: dict[str, set[str]] | None = None,
) -> int:
    """Write ``item_profile.jsonl``. Returns number of rows written.

    Args:
        items: enriched items with raw_record + tags.
        path: output JSONL path.
        llm_dims: dimension names to overlay from ``item.tags``.
                  Should be derived from tables.yaml ``_meta.llm_inference``.
        allowed_fields: ``{role: {column_name, ...}}`` — only these raw
                        columns are emitted.  Built from tables.yaml
                        ``columns[*].name``.  When None, all raw columns kept.
    """
    dims: set[str] = llm_dims or set()
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", encoding="utf-8") as f:
        for item in items:
            raw = item.raw_record
            role_key = item.item_type.value if item.item_type else "unknown"
            keep = allowed_fields.get(role_key) if allowed_fields else None

            if keep is not None:
                profile: dict[str, object] = {
                    k: v for k, v in raw.items() if k in keep
                }
            else:
                profile = dict(raw)
                profile.pop("_extra", None)
                profile.pop("etl_dt", None)

            # Overlay AI-inferred dimension tags (always write, even if null)
            for dim in dims:
                profile[dim] = item.tags.get(dim)

            f.write(json.dumps(profile, ensure_ascii=False) + "\n")
            written += 1
    return written


__all__ = ["write_item_profile"]
