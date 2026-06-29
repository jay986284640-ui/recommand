#!/usr/bin/env python3
"""Generate ES synonyms from Stage 2 item_profile.jsonl.

Reads item_profile.jsonl (training-data-synonym Stage 2 output), extracts
unique brand/category/occasion/taste values, merges with brand_dictionary.yaml
variants, adds Chinese↔English pairs for categories/occasions/tastes,
and writes synonyms_solr.txt in ES Solr multi-way format.

Usage:
    PYTHONPATH=.. python scripts/generate_synonyms_from_profile.py \
        --profile ../training-data-synonym/test_output/item_profile.jsonl \
        --brand-dict configs/brand_dictionary.yaml \
        --output test_output
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


# ── brand dictionary loader ──────────────────────────────────────────

def load_brand_dict(path: Path) -> dict:
    """{canonical → sorted variants}."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for entry in raw.get("brands", []):
        canon = entry.get("canonical", "")
        variants = sorted(set(entry.get("variants", [canon])))
        if canon:
            out[canon] = variants
    return out


def load_category_dict(path: Path) -> dict:
    """{canonical → {variants: [...], aliases: [...]}}."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for entry in raw.get("categories", []):
        canon = entry.get("canonical", "")
        out[canon] = {
            "variants": sorted(set(entry.get("variants", [canon]))),
            "aliases": sorted(set(entry.get("aliases", []))),
        }
    return out


# ── Stage 2 profile reader ───────────────────────────────────────────

def collect_stage2_values(
    profile_path: Path,
    brand_dict: dict[str, list[str]] | None = None,
) -> dict[str, set[str]]:
    """Collect unique brand/category/occasion/taste values.

    Brand values come from 3 sources:
      1. ``merchant`` field (AI tag)
      2. ``str_nm`` field — longest-substring match against known brands
         (catches brands that AI missed, e.g. "瑞幸咖啡 南京西路店" → 瑞幸)
      3. Singleton brands from ``str_nm`` not in dict (preserved as-is)
    """
    values: dict[str, set[str]] = {"brand": set(), "category": set(), "occasion": set(), "taste": set()}
    known_brands = list(brand_dict.keys()) if brand_dict else []

    for line in profile_path.open(encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)

        # Brand source 1: AI tag
        for field in ("merchant",):
            v = row.get(field)
            if v:
                values["brand"].add(v)

        # Brand source 2: str_nm substring match against known brands
        name = row.get("str_nm") or ""
        if name and known_brands:
            for kb in known_brands:
                if kb in name:
                    values["brand"].add(kb)

        for field in ("category", "cat_nm"):
            v = row.get(field)
            if v:
                values["category"].add(v)
        for field in ("occasion",):
            v = row.get(field)
            if v:
                values["occasion"].add(v)
        tv = row.get("taste")
        if tv:
            if isinstance(tv, list):
                values["taste"].update(tv)
            else:
                values["taste"].add(tv)
    return values


# ── bilingual mappings ───────────────────────────────────────────────

_CATEGORY_EN = {
    "咖啡": "coffee", "奶茶": "milk tea", "快餐": "fast food",
    "中餐": "Chinese food", "西餐": "Western food", "日料": "Japanese",
    "火锅": "hotpot", "烧烤": "BBQ", "甜品": "dessert",
    "便利店": "convenience store", "烘焙": "bakery", "水果": "fruit",
}

_OCCASION_EN = {
    "早餐": "breakfast", "午餐": "lunch", "下午茶": "afternoon tea",
    "晚餐": "dinner", "夜宵": "late night", "聚会": "gathering",
    "工作日": "weekday", "周末": "weekend", "节日": "holiday",
    "自取": "pickup", "外卖": "delivery", "堂食": "dine-in", "通勤": "commute",
}

_TASTE_EN = {
    "甜口": "sweet", "咸鲜": "savory", "辣": "spicy", "麻辣": "numbing spicy",
    "酸": "sour", "酸爽": "tangy", "麻": "numbing", "清淡": "light",
    "香辣": "fragrant spicy", "酸辣": "sour spicy", "蒜香": "garlic",
    "酱香": "sauce", "奶香": "creamy", "焦香": "caramelized",
    "烟熏": "smoked", "咖喱风味": "curry", "果味": "fruity",
    "鲜": "umami", "浓郁汤底": "rich broth", "重口味": "heavy flavor",
    "黄焖": "braised", "卤香": "marinated", "红烧风味": "red-braised",
}


# ── main ─────────────────────────────────────────────────────────────

def build_groups(
    stage2: dict[str, set[str]],
    brand_dict: dict[str, list[str]],
    category_dict: dict[str, dict] | None = None,
) -> tuple[list[list[str]], dict[str, int]]:
    groups: list[list[str]] = []
    stats: dict[str, int] = {}

    # Source 1: rule-based brand dictionary (only brands that appear in Stage 2)
    for canon, variants in brand_dict.items():
        if canon in stage2["brand"]:
            groups.append(variants)
    brand_rule_count = sum(1 for g in groups if len(g) > 1)

    # Source 2: data brands NOT in dict → singleton (no variant expansion)
    data_brands = 0
    for b in sorted(stage2["brand"]):
        if b not in brand_dict:
            groups.append([b])
            data_brands += 1
    stats["brand_rule"] = brand_rule_count
    stats["brand_data"] = data_brands

    # Source 3: category dictionary (rule-based, bilingual + aliases)
    cat_rule = 0
    if category_dict:
        for canon, entry in category_dict.items():
            if canon in stage2["category"]:
                groups.append(entry["variants"])
                cat_rule += 1
    # Categories in Stage 2 but NOT in category_dict → fallback to _CATEGORY_EN
    cat_fallback = 0
    for cat in sorted(stage2["category"]):
        if category_dict and cat in category_dict:
            continue  # already handled
        en = _CATEGORY_EN.get(cat)
        if en:
            groups.append(sorted({cat, en}))
            cat_fallback += 1
        else:
            groups.append([cat])
    stats["category_rule"] = cat_rule
    stats["category_fallback"] = cat_fallback

    # Source 4: occasion bilingual
    occ_count = 0
    for occ in sorted(stage2["occasion"]):
        en = _OCCASION_EN.get(occ)
        if en:
            groups.append(sorted({occ, en}))
            occ_count += 1
        else:
            groups.append([occ])
    stats["occasion"] = occ_count

    # Source 5: taste bilingual
    taste_count = 0
    for t in sorted(stage2["taste"]):
        en = _TASTE_EN.get(t)
        if en:
            groups.append(sorted({t, en}))
            taste_count += 1
        else:
            groups.append([t])
    stats["taste"] = taste_count

    return groups, stats


def write_output(groups: list[list[str]], out_dir: Path, stats: dict[str, int]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "synonyms_solr.txt"
    actual = 0
    with out_path.open("w", encoding="utf-8") as f:
        for g in groups:
            if len(g) <= 1:
                continue
            line = ", ".join(g)
            f.write(f"{line} => {line}\n")
            actual += 1

    meta: dict[str, Any] = {
        "version": "1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total_groups_written": actual,
        "total_groups_assembled": len(groups),
        "stats": stats,
    }
    (out_dir / "synonyms_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate ES synonyms from Stage 2 item_profile.jsonl")
    ap.add_argument("--profile", default="../training-data-synonym/test_output/item_profile.jsonl",
                    help="Path to item_profile.jsonl (Stage 2 output)")
    ap.add_argument("--brand-dict", default="configs/brand_dictionary.yaml",
                    help="Path to brand_dictionary.yaml")
    ap.add_argument("--category-dict", default="configs/category_dictionary.yaml",
                    help="Path to category_dictionary.yaml")
    ap.add_argument("--output", default="test_output", help="Output directory")
    args = ap.parse_args(argv)

    profile = Path(args.profile)
    if not profile.exists():
        print(f"ERROR: {profile} not found", file=sys.stderr)
        return 2

    brand_dict_path = Path(args.brand_dict)
    if not brand_dict_path.exists():
        brand_dict_path = Path(__file__).resolve().parent.parent / "configs" / "brand_dictionary.yaml"

    category_dict_path = Path(args.category_dict)
    category_dict = None
    if category_dict_path.exists():
        category_dict = load_category_dict(category_dict_path)
    else:
        print(f"WARNING: category dict not found at {category_dict_path}, using fallback")

    brand_dict = load_brand_dict(brand_dict_path)
    stage2 = collect_stage2_values(profile, brand_dict)

    groups, stats = build_groups(stage2, brand_dict, category_dict)
    out_path = write_output(groups, Path(args.output), stats)

    print(f"=== Synonyms generated ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  groups written: {sum(1 for g in groups if len(g) > 1)}")
    print(f"  → {out_path}")
    print(f"  → {Path(args.output) / 'synonyms_meta.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
