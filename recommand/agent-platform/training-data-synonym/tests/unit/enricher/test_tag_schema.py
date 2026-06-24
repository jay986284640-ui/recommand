"""Unit tests for tag_schema.assemble_item_tags invariant (T033)."""

from __future__ import annotations

from training_data_synonym.data_model import DIM_ORDER, Role, TagOrigin
from training_data_synonym.enricher.tag_schema import assemble_item_tags


def test_invariant_non_distance():
    item = assemble_item_tags(
        item_id="x",
        item_type=Role.MEITUAN_SHOP,
        raw_record={},
        tags={"category": None, "consumable_type": "drink", "merchant": None,
              "avg_prc": "30-50", "distance": None, "age": None,
              "occasion": None, "taste": None},
        sources={"category": TagOrigin.MISSING, "consumable_type": TagOrigin.DERIVED,
                 "merchant": TagOrigin.MISSING, "avg_prc": TagOrigin.RAW,
                 "distance": TagOrigin.GEO, "age": TagOrigin.MISSING,
                 "occasion": TagOrigin.MISSING, "taste": TagOrigin.MISSING},
    )
    assert item.tag_source.category == TagOrigin.MISSING
    assert item.tag_source.consumable_type == TagOrigin.DERIVED
    assert item.tag_source.distance == TagOrigin.GEO  # special case


def test_distance_can_be_geo_with_null_value():
    """distance is always null at Stage 1, even when geo is set."""
    item = assemble_item_tags(
        item_id="x",
        item_type=Role.MEITUAN_SHOP,
        raw_record={},
        tags={d: None for d in DIM_ORDER},
        sources={d: TagOrigin.MISSING for d in DIM_ORDER} | {"distance": TagOrigin.GEO},
    )
    assert item.tags["distance"] is None
    assert item.tag_source.distance == TagOrigin.GEO


def test_invariant_downgrade_non_distance():
    """If source != missing but value is None for non-distance, downgrade source to missing."""
    item = assemble_item_tags(
        item_id="x",
        item_type=Role.MEITUAN_SHOP,
        raw_record={},
        tags={d: None for d in DIM_ORDER},
        sources={d: TagOrigin.RAW for d in DIM_ORDER} | {"distance": TagOrigin.GEO},
    )
    # Non-distance dims: source should downgrade to MISSING
    for d in DIM_ORDER:
        if d != "distance":
            assert item.tag_source.__dict__[d] == TagOrigin.MISSING
    assert item.tag_source.distance == TagOrigin.GEO


def test_assemble_default_8dim_order():
    item = assemble_item_tags(
        item_id="x",
        item_type=Role.MEITUAN_SHOP,
        raw_record={},
        tags={d: None for d in DIM_ORDER} | {"distance": None},
        sources={d: TagOrigin.MISSING for d in DIM_ORDER},
    )
    assert list(item.tags.keys()) == list(DIM_ORDER)