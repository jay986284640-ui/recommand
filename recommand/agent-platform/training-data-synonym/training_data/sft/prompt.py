"""sft/prompt — SFT prompt template loading + placeholder substitution.

All prompt-related logic in one place:
  - ``load_template()`` — read ``sft_v1.txt``
  - ``build_sft_prompt()`` — fill in ``{item}``
"""

from __future__ import annotations

from pathlib import Path

_DEFAULT_TEMPLATE = (
    Path(__file__).resolve().parent.parent.parent
    / "configs" / "prompts" / "sft_v1.txt"
)


def load_template(path: str | Path | None = None) -> str:
    """Read the SFT prompt template file.

    Args:
        path: template path; defaults to ``configs/prompts/sft_v1.txt``.
    """
    pt = Path(path) if path else _DEFAULT_TEMPLATE
    return pt.read_text(encoding="utf-8") if pt.exists() else ""


def build_sft_prompt(
    *,
    item: dict,
    scenario_type: str,
    target_turns: int,
    template: str,
) -> str:
    """Substitute ``{item}``, ``{scenario_type}``, ``{target_turns}``."""
    import json

    # Use whatever fields the item has (config-driven, no hardcoded field names)
    item_view = {k: v for k, v in item.items() if v is not None}

    return (
        template.replace(
            "{item}", json.dumps(item_view, ensure_ascii=False, indent=2)
        ).replace("{scenario_type}", scenario_type)
        .replace("{target_turns}", str(target_turns))
    )


__all__ = ["load_template", "build_sft_prompt"]
