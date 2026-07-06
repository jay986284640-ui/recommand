"""Unit tests for synonym builder module."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from synonym_builder.builder import (
    _build_brand_groups,
    _build_dim_groups,
    _build_store_name_groups,
    _build_taste_groups,
    _clean_store_name,
    _collect_profile_values,
    _load_brand_dict,
    _match_known_brand,
    _write_solr_synonyms,
    build_synonyms,
)


# ---------------------------------------------------------------------------
# _load_brand_dict
# ---------------------------------------------------------------------------


def test_load_brand_dict_parses_canonical_and_variants(tmp_path: Path):
    data = {
        "brands": [
            {
                "canonical": "星巴克",
                "variants": ["星巴克", "Starbucks", "星巴克咖啡"],
                "category": "咖啡",
            },
            {
                "canonical": "瑞幸",
                "variants": ["瑞幸", "瑞幸咖啡", "luckin"],
                "category": "咖啡",
            },
        ]
    }
    path = tmp_path / "brand_dict.yaml"
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

    result = _load_brand_dict(path)
    assert result["星巴克"] == ["Starbucks", "星巴克", "星巴克咖啡"]
    assert result["瑞幸"] == ["luckin", "瑞幸", "瑞幸咖啡"]


def test_load_brand_dict_empty_file(tmp_path: Path):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    result = _load_brand_dict(path)
    assert result == {}


# ---------------------------------------------------------------------------
# _collect_profile_values
# ---------------------------------------------------------------------------


def test_collect_profile_values_basic(tmp_path: Path):
    profile = tmp_path / "item_profile.jsonl"
    rows = [
        {
            "str_id": "1", "str_nm": "星巴克",
            "brand": "星巴克", "category": "咖啡", "cuisine": "西餐",
            "meal_time": "下午茶", "occasion": "约会",
            "taste": ["甜", "奶香"],
        },
        {
            "str_id": "2", "str_nm": "海底捞",
            "brand": "海底捞", "category": "火锅", "cuisine": "火锅",
            "meal_time": "晚餐", "occasion": "聚餐",
            "taste": ["辣", "麻"],
        },
        {
            "str_id": "3", "str_nm": "正韩料理",
            "brand": None, "category": "韩式料理", "cuisine": "韩式料理",
            "meal_time": "午餐", "occasion": None,
            "taste": ["辣", "酱香"],
        },
    ]
    profile.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )

    vals = _collect_profile_values(profile)

    assert vals["brand"] == {"星巴克", "海底捞"}
    assert vals["category"] == {"咖啡", "火锅", "韩式料理"}
    assert vals["cuisine"] == {"西餐", "火锅", "韩式料理"}
    assert vals["meal_time"] == {"下午茶", "晚餐", "午餐"}
    assert vals["occasion"] == {"约会", "聚餐"}
    assert vals["taste"] == {"甜", "奶香", "辣", "麻", "酱香"}


def test_collect_profile_values_handles_empty_taste(tmp_path: Path):
    profile = tmp_path / "item_profile.jsonl"
    rows = [
        {"str_id": "1", "brand": "A", "category": "X",
         "cuisine": None, "meal_time": None, "occasion": None, "taste": []},
    ]
    profile.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )
    vals = _collect_profile_values(profile)
    assert vals["taste"] == set()
    assert vals["cuisine"] == set()


# ---------------------------------------------------------------------------
# _build_brand_groups
# ---------------------------------------------------------------------------


def test_build_brand_groups_matches_canonical():
    profile_brands = {"星巴克"}
    brand_dict = {"星巴克": ["星巴克", "Starbucks", "星巴克咖啡"]}

    groups, config, cluster, single = _build_brand_groups(profile_brands, brand_dict)
    assert config == 1
    assert single >= 0
    assert len(groups) == 1
    assert set(groups[0]) == {"星巴克", "Starbucks", "星巴克咖啡"}


def test_build_brand_groups_matches_variant():
    """Brand matched via a variant appearing in profile data."""
    profile_brands = {"Starbucks"}
    brand_dict = {"星巴克": ["星巴克", "Starbucks", "星巴克咖啡"]}

    groups, config, cluster, single = _build_brand_groups(profile_brands, brand_dict)
    assert config == 1
    assert single >= 0


def test_build_brand_groups_unknown_singleton():
    profile_brands = {"牧白手作"}
    brand_dict = {"星巴克": ["星巴克", "Starbucks"]}

    groups, config, cluster, single = _build_brand_groups(profile_brands, brand_dict)
    assert config == 0
    assert cluster == 0  # only 1 brand → can't cluster
    assert single == 1
    assert groups == [["牧白手作"]]


def test_build_brand_groups_mixed():
    profile_brands = {"星巴克", "牧白手作", "海底捞"}
    brand_dict = {
        "星巴克": ["星巴克", "Starbucks"],
        "海底捞": ["海底捞", "Haidilao", "海底捞火锅"],
    }

    groups, config, cluster, single = _build_brand_groups(profile_brands, brand_dict)
    assert config == 2
    assert single == 1  # 牧白手作


# ---------------------------------------------------------------------------
# _build_dim_groups
# ---------------------------------------------------------------------------


def test_build_dim_groups_bilingual():
    en_map = {"咖啡": "coffee", "奶茶": "milk tea"}
    groups, en_count = _build_dim_groups({"咖啡", "奶茶"}, en_map)
    assert en_count == 2
    assert len(groups) == 2
    # Each group should contain both Chinese and English
    all_terms = set().union(*groups)
    assert "coffee" in all_terms
    assert "milk tea" in all_terms


def test_build_dim_groups_no_translation():
    en_map = {"咖啡": "coffee"}
    groups, en_count = _build_dim_groups({"未知品类"}, en_map)
    assert en_count == 0
    assert groups == [["未知品类"]]


def test_build_dim_groups_with_variants():
    en_map = {"咖啡": "coffee"}
    variant_map = {"咖啡": ["咖啡店", "咖啡馆", "cafe"]}
    groups, en_count = _build_dim_groups({"咖啡"}, en_map, variant_map)
    assert en_count == 1
    # All variants + EN should be in the group
    all_terms = set(groups[0])
    assert all_terms >= {"咖啡", "coffee", "咖啡店", "咖啡馆", "cafe"}


# ---------------------------------------------------------------------------
# _build_taste_groups
# ---------------------------------------------------------------------------


def test_build_taste_groups():
    en_map = {"甜": "sweet", "辣": "spicy", "麻": "numbing"}
    groups, en_count = _build_taste_groups({"甜", "辣", "麻"}, en_map)
    assert en_count == 3
    assert len(groups) == 3


def test_build_taste_groups_missing_en():
    groups, en_count = _build_taste_groups({"奇异口味"}, {})
    assert en_count == 0
    assert groups == [["奇异口味"]]


# ---------------------------------------------------------------------------
# _clean_store_name
# ---------------------------------------------------------------------------


def test_clean_store_name_strips_chinese_parens():
    assert _clean_store_name("瑞幸咖啡（金融街购物中心店）") == "瑞幸咖啡"
    assert _clean_store_name("牧白手作（上海金融街店）") == "牧白手作"


def test_clean_store_name_strips_ascii_parens():
    assert _clean_store_name("海底捞火锅(望京店)") == "海底捞火锅"


def test_clean_store_name_strips_dash_separator():
    assert _clean_store_name("28度海仙面-温州味道（金融街店）") == "28度海仙面"


def test_clean_store_name_strips_dot_separator():
    assert _clean_store_name("正韩·韩式料理（上大店）") == "正韩"


def test_clean_store_name_no_parens():
    assert _clean_store_name("牧白手作") == "牧白手作"


def test_clean_store_name_empty():
    assert _clean_store_name("") == ""
    assert _clean_store_name("   ") == ""


# ---------------------------------------------------------------------------
# _match_known_brand
# ---------------------------------------------------------------------------


def test_match_known_brand_exact():
    lookup = {"瑞幸": "瑞幸", "瑞幸咖啡": "瑞幸", "luckin": "瑞幸"}
    assert _match_known_brand("瑞幸咖啡", lookup) == "瑞幸"
    assert _match_known_brand("瑞幸", lookup) == "瑞幸"


def test_match_known_brand_substring_in_store_name():
    lookup = {"瑞幸": "瑞幸", "瑞幸咖啡": "瑞幸"}
    # "瑞幸咖啡" is a substring of the store name
    assert _match_known_brand("瑞幸咖啡（金融街购物中心店）", lookup) == "瑞幸"


def test_match_known_brand_longest_match_wins():
    lookup = {
        "瑞幸": "瑞幸",
        "瑞幸咖啡": "瑞幸",
        "luckin": "瑞幸",
    }
    # "瑞幸咖啡" (4 chars) > "瑞幸" (2 chars)
    assert _match_known_brand("瑞幸咖啡（金融街店）", lookup) == "瑞幸"


def test_match_known_brand_no_match():
    lookup = {"星巴克": "星巴克", "Starbucks": "星巴克"}
    assert _match_known_brand("牧白手作（上海金融街店）", lookup) is None


def test_match_known_brand_empty():
    assert _match_known_brand("", {"瑞幸": "瑞幸"}) is None
    assert _match_known_brand("瑞幸", {}) is None


# ---------------------------------------------------------------------------
# _collect_profile_values — store name + brand matching
# ---------------------------------------------------------------------------


def test_collect_profile_values_discovers_brand_from_str_nm(tmp_path: Path):
    """Brand discovered via str_nm substring match when brand field is null."""
    profile = tmp_path / "item_profile.jsonl"
    rows = [
        {
            "str_id": "1", "str_nm": "瑞幸咖啡（金融街购物中心店）",
            "brand": None, "category": "咖啡",
            "cuisine": None, "meal_time": None, "occasion": None,
            "taste": [],
        },
    ]
    profile.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )

    brand_map = {"瑞幸": ["瑞幸", "瑞幸咖啡", "luckin"]}
    vals = _collect_profile_values(profile, brand_map)

    # Brand discovered from str_nm
    assert "瑞幸" in vals["brand"]
    # Store name collected
    assert "瑞幸咖啡（金融街购物中心店）" in vals["store_name"]


def test_collect_profile_values_collects_store_names(tmp_path: Path):
    profile = tmp_path / "item_profile.jsonl"
    rows = [
        {"str_id": "1", "str_nm": "牧白手作（上海金融街店）",
         "brand": "牧白手作", "category": "奶茶",
         "cuisine": None, "meal_time": None, "occasion": None, "taste": []},
    ]
    profile.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )

    vals = _collect_profile_values(profile)
    assert "牧白手作（上海金融街店）" in vals["store_name"]


# ---------------------------------------------------------------------------
# _build_store_name_groups
# ---------------------------------------------------------------------------


def test_build_store_name_groups_clean_only():
    """Non-brand store names: only emit group when ≥2 stores share same cleaned name."""
    store_names = {
        "牧白手作（上海金融街店）",
        "霸王茶姬（金融街购物中心店）",
    }
    brand_map = {"星巴克": ["星巴克", "Starbucks"]}

    groups, clean, brand = _build_store_name_groups(store_names, brand_map)
    # 0 — each cleaned name has only 1 store, no group emitted
    assert clean == 0
    assert brand == 0
    assert len(groups) == 0


def test_build_store_name_groups_brand_match():
    """Store names matching known brands → brand variant groups (no full names)."""
    store_names = {
        "瑞幸咖啡（金融街购物中心店）",
        "奈雪的茶（静安金融街融悦中心店）",
    }
    brand_map = {
        "瑞幸": ["瑞幸", "瑞幸咖啡", "luckin"],
        "奈雪": ["奈雪", "奈雪的茶", "nayuki"],
    }

    groups, clean, brand = _build_store_name_groups(store_names, brand_map)
    assert brand == 2  # Both matched known brands
    assert len(groups) == 2

    # Groups contain brand variants only — NO full store names
    all_tokens = set().union(*[set(g) for g in groups])
    assert "luckin" in all_tokens
    assert "nayuki" in all_tokens
    # Full store names are NOT in output
    assert "瑞幸咖啡（金融街购物中心店）" not in all_tokens
    assert "奈雪的茶（静安金融街融悦中心店）" not in all_tokens


def test_build_store_name_groups_no_parens():
    """Store name without branch markers → no group generated."""
    store_names = {"牧白手作"}  # already clean
    brand_map = {}

    groups, clean, brand = _build_store_name_groups(store_names, brand_map)
    assert clean == 0
    assert brand == 0
    assert len(groups) == 0


def test_build_store_name_groups_mixed():
    """Mix of brand-matched and non-matched store names — no full names in output."""
    store_names = {
        "瑞幸咖啡（金融街购物中心店）",  # matches brand
        "牧白手作（上海金融街店）",       # no brand match, only 1 store → skip
        "星巴克臻选（静安寺店）",         # matches brand
    }
    brand_map = {
        "瑞幸": ["瑞幸", "瑞幸咖啡"],
        "星巴克": ["星巴克", "Starbucks", "星巴克臻选"],
    }

    groups, clean, brand = _build_store_name_groups(store_names, brand_map)
    assert clean == 0   # 牧白手作: only 1 store → no group
    assert brand == 2   # 瑞幸 + 星巴克
    assert len(groups) == 2

    # Brand variant groups — NO full store names
    all_tokens = set().union(*[set(g) for g in groups])
    assert "Starbucks" in all_tokens
    assert "瑞幸咖啡" in all_tokens
    assert "星巴克臻选（静安寺店）" not in all_tokens
    assert "瑞幸咖啡（金融街购物中心店）" not in all_tokens


# ---------------------------------------------------------------------------
# _write_solr_synonyms
# ---------------------------------------------------------------------------


def test_write_solr_synonyms_format(tmp_path: Path):
    groups = [
        ["咖啡", "coffee", "咖啡馆"],
        ["星巴克", "Starbucks"],
        ["单独词"],  # singleton — should be skipped
    ]
    out = tmp_path / "synonyms_solr.txt"
    written = _write_solr_synonyms(groups, out, source_description="test")

    assert written == 2  # only multi-member groups
    content = out.read_text(encoding="utf-8")

    # No comments — pure synonym lines only
    assert not content.strip().startswith("#")

    # Solr multi-way format (comma-separated, no =>)
    assert "咖啡, coffee, 咖啡馆" in content
    assert "星巴克, Starbucks" in content
    assert " => " not in content

    # Singleton NOT written
    assert "单独词" not in content


def test_write_solr_synonyms_skips_singletons(tmp_path: Path):
    groups = [["only_one"]]
    out = tmp_path / "synonyms_solr.txt"
    written = _write_solr_synonyms(groups, out)
    assert written == 0


# ---------------------------------------------------------------------------
# build_synonyms end-to-end
# ---------------------------------------------------------------------------


def test_build_synonyms_end_to_end(tmp_path: Path):
    """Full pipeline: profile + brand_dict → synonyms_solr.txt."""
    # Setup: item_profile.jsonl
    profile_path = tmp_path / "item_profile.jsonl"
    rows = [
        {
            "str_id": "1", "str_nm": "星巴克咖啡（人民广场店）",
            "brand": "星巴克", "category": "咖啡",
            "cuisine": None, "meal_time": "下午茶", "occasion": "约会",
            "taste": ["甜", "奶香"],
        },
        {
            "str_id": "2", "str_nm": "海底捞火锅（望京店）",
            "brand": "海底捞", "category": "火锅",
            "cuisine": "火锅", "meal_time": "晚餐", "occasion": "聚餐",
            "taste": ["辣", "麻"],
        },
        {
            "str_id": "3", "str_nm": "牧白手作（上海金融街店）",
            "brand": "牧白手作", "category": "奶茶",
            "cuisine": None, "meal_time": None, "occasion": None,
            "taste": ["甜"],
        },
    ]
    profile_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )

    # Setup: brand_dictionary.yaml
    brand_dict_path = tmp_path / "brand_dictionary.yaml"
    brand_data = {
        "brands": [
            {
                "canonical": "星巴克",
                "variants": ["星巴克", "Starbucks", "星巴克咖啡", "星巴克臻选"],
                "category": "咖啡",
            },
            {
                "canonical": "海底捞",
                "variants": ["海底捞", "Haidilao", "海底捞火锅"],
                "category": "火锅",
            },
        ]
    }
    brand_dict_path.write_text(
        yaml.dump(brand_data, allow_unicode=True), encoding="utf-8"
    )

    output_dir = tmp_path / "synonyms_out"

    # Run
    stats = build_synonyms(
        profile_path=profile_path,
        brand_dict_path=brand_dict_path,
        output_dir=output_dir,
    )

    # Assertions
    assert (output_dir / "synonyms_solr.txt").exists()
    assert (output_dir / "synonyms_meta.json").exists()

    # Stats
    assert stats["brand_config"] == 2  # 星巴克 + 海底捞
    assert stats["brand_single"] >= 1  # 牧白手作 (singleton)
    assert stats["category"] >= 3
    assert stats["taste"] >= 4
    # Store name synonyms — non-brand singles skipped; only brand-matched emit groups
    assert stats["store_name_clean"] == 0  # 牧白手作: only 1 store → no group
    assert stats["store_name_brand"] == 2  # 星巴克 + 海底捞 → brand match
    assert stats["total_written"] > 0

    # Verify output content
    content = (output_dir / "synonyms_solr.txt").read_text(encoding="utf-8")
    # No comments
    assert not content.strip().startswith("#")
    # Brand synonyms
    assert "星巴克" in content
    assert "Starbucks" in content
    assert "海底捞" in content
    assert "Haidilao" in content
    # No full store names with locations
    assert "（人民广场店）" not in content
    assert "（望京店）" not in content
    assert "（上海金融街店）" not in content
    # Solr multi-way format (no => arrow)
    assert " => " not in content
    # Category bilingual
    assert "coffee" in content
    # Taste bilingual
    assert "sweet" in content
    assert "spicy" in content

    # Verify meta
    meta = json.loads((output_dir / "synonyms_meta.json").read_text(encoding="utf-8"))
    assert meta["_format_version"] == "synonyms_v1"
    assert meta["total_groups_written"] > 0
    assert "stats" in meta


def test_build_synonyms_no_brand_dict_match(tmp_path: Path):
    """All brands are singletons — data-only output."""
    profile_path = tmp_path / "item_profile.jsonl"
    rows = [
        {
            "str_id": "1", "brand": "牧白手作", "category": "奶茶",
            "cuisine": None, "meal_time": None, "occasion": None,
            "taste": ["甜"],
        },
    ]
    profile_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )

    brand_dict_path = tmp_path / "brand_dict.yaml"
    brand_data = {
        "brands": [
            {"canonical": "星巴克", "variants": ["星巴克", "Starbucks"]},
        ]
    }
    brand_dict_path.write_text(
        yaml.dump(brand_data, allow_unicode=True), encoding="utf-8"
    )

    output_dir = tmp_path / "synonyms_out"
    stats = build_synonyms(
        profile_path=profile_path,
        brand_dict_path=brand_dict_path,
        output_dir=output_dir,
    )

    assert stats["brand_config"] == 0
    assert stats["brand_single"] >= 1
    # Category and taste groups still generated
    assert stats["category"] >= 1
    assert stats["taste"] >= 1


def test_build_synonyms_store_name_brand_discovery(tmp_path: Path):
    """Store names with branch markers → brand discovery + synonym groups."""
    profile_path = tmp_path / "item_profile.jsonl"
    rows = [
        {
            "str_id": "1", "str_nm": "瑞幸咖啡（金融街购物中心店）",
            "brand": None,  # AI tagger missed this brand
            "category": "咖啡", "cuisine": None,
            "meal_time": None, "occasion": None, "taste": [],
        },
        {
            "str_id": "2", "str_nm": "奈雪的茶（静安金融街融悦中心店）",
            "brand": "奈雪的茶",  # AI tagger caught this one
            "category": "奶茶", "cuisine": None,
            "meal_time": None, "occasion": None, "taste": [],
        },
        {
            "str_id": "3", "str_nm": "甬江鲜·江浙菜家宴（金融街店）",
            "brand": None,  # no brand, not in dict
            "category": "江浙菜", "cuisine": None,
            "meal_time": None, "occasion": None, "taste": [],
        },
    ]
    profile_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )

    brand_dict_path = tmp_path / "brand_dictionary.yaml"
    brand_data = {
        "brands": [
            {
                "canonical": "瑞幸",
                "variants": ["瑞幸", "瑞幸咖啡", "luckin"],
                "category": "咖啡",
            },
            {
                "canonical": "奈雪",
                "variants": ["奈雪", "奈雪的茶", "nayuki"],
                "category": "奶茶",
            },
        ]
    }
    brand_dict_path.write_text(
        yaml.dump(brand_data, allow_unicode=True), encoding="utf-8"
    )

    output_dir = tmp_path / "synonyms_out"
    stats = build_synonyms(
        profile_path=profile_path,
        brand_dict_path=brand_dict_path,
        output_dir=output_dir,
    )

    # Brand discovered from str_nm for item #1 (brand was null)
    assert stats["brand_config"] == 2  # 瑞幸 + 奈雪 from config
    # Store name → brand: 2 brand-matched groups (brand variants only)
    assert stats["store_name_brand"] == 2
    # Store name → clean: 0 (only 1 store per cleaned name, no group)
    assert stats["store_name_clean"] == 0

    content = (output_dir / "synonyms_solr.txt").read_text(encoding="utf-8")
    # No comments
    assert not content.strip().startswith("#")
    # Brand variants present
    assert "luckin" in content
    assert "nayuki" in content
    # Full store names NOT in output
    assert "瑞幸咖啡（金融街购物中心店）" not in content
    assert "奈雪的茶（静安金融街融悦中心店）" not in content
    assert "甬江鲜·江浙菜家宴（金融街店）" not in content
    # No comments
    assert "#" not in content


def test_build_synonyms_missing_profile_raises(tmp_path: Path):
    """Missing profile file should raise FileNotFoundError."""
    import pytest

    brand_dict = tmp_path / "brand.yaml"
    brand_dict.write_text("brands: []", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="item_profile.jsonl"):
        build_synonyms(
            profile_path=tmp_path / "nonexistent.jsonl",
            brand_dict_path=brand_dict,
            output_dir=tmp_path / "out",
        )
