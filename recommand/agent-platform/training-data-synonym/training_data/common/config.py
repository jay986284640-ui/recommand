"""Configuration loader (yaml → dataclass) + dict_version computation.

Per research.md D-003: dict_version is md5(dim_dictionary._meta.version ||
consumable_type_map._meta.version) for incremental fingerprinting.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    """Top-level configuration loaded from configs/pipeline.yaml + dict yamls."""

    configs_dir: Path
    pipeline: dict = field(default_factory=dict)
    dim_dictionary: dict = field(default_factory=dict)
    consumable_type_map: dict = field(default_factory=dict)
    brand_dictionary: dict = field(default_factory=dict)
    intent_keywords: dict = field(default_factory=dict)
    sentence_templates: dict = field(default_factory=dict)

    @classmethod
    def load(cls, configs_dir: str | Path) -> "Config":
        configs_dir = Path(configs_dir)
        cfg = cls(configs_dir=configs_dir)
        for name in (
            "pipeline",
            "dim_dictionary",
            "consumable_type_map",
            "brand_dictionary",
            "intent_keywords",
            "sentence_templates",
        ):
            path = configs_dir / f"{name}.yaml"
            if path.exists():
                with path.open() as f:
                    setattr(cfg, name, yaml.safe_load(f) or {})
        return cfg

    @property
    def dict_version(self) -> str:
        """md5 of dim_dictionary + consumable_type_map _meta.version."""
        parts = [
            str(self.dim_dictionary.get("_meta", {}).get("version", "")),
            str(self.consumable_type_map.get("_meta", {}).get("version", "")),
        ]
        return hashlib.md5("||".join(parts).encode()).hexdigest()


def env_or(default: str, *keys: str) -> str:
    """Read environment variable (first hit wins)."""
    for k in keys:
        v = os.environ.get(k)
        if v:
            return v
    return default