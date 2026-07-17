"""Core dataclasses per spec.md (v2.4) + data-model.md.

Roles:
  MEITUAN_SHOP / SELF_SHOP / COUPON (active item types in this batch)
  ADDRESS / CATEGORY / COUPON_SHOP / DISCOUNT / CUSTOMER / EVENTS / UNKNOWN
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from .common.versioning import (
    DISTRIBUTION_REPORT_V,
    ITEM_TAGS_V,
    SFT_CORPUS_V,
    TABLE_META_V,
    TRAIN_SPLIT_V,
)


class Role(str, Enum):
    MEITUAN_SHOP = "meituan_shop"
    SELF_SHOP = "self_shop"
    COUPON = "coupon"
    ADDRESS = "address"
    CATEGORY = "category"
    COUPON_SHOP = "coupon_shop"
    DISCOUNT = "discount"
    CUSTOMER = "customer"
    EVENTS = "events"
    UNKNOWN = "unknown"


class TagOrigin(str, Enum):
    RAW = "raw"
    AI = "ai"
    DERIVED = "derived"
    GEO = "geo"
    MISSING = "missing"


# --- T012: TableMeta ------------------------------------------------------


@dataclass
class ColumnMeta:
    name: str
    type: str
    nullable: bool = True
    comment: Optional[str] = None


@dataclass
class TableMeta:
    db: str
    table_name: str
    columns: list[ColumnMeta]
    partition_keys: list[str] = field(default_factory=list)
    inferred_role: Role = Role.UNKNOWN
    item_id: str = ""       # primary-key column name (v1.4, replaces columns[*].role:id)
    _format_version: str = TABLE_META_V


# --- T015: HiveReadSpec + RawRecord --------------------------------------


@dataclass(frozen=True)
class HiveReadSpec:
    source: str = "hive"  # "hive" | "mock"
    catalog: Optional[str] = None
    databases: dict[str, str] = field(
        default_factory=lambda: {
            "recommand_workspace": "recommand_workspace",
            "cdm": "cdm",
        }
    )
    etl_dt_mode: str = "latest_n"  # "single" | "range" | "latest_n"
    etl_dt_single: Optional[str] = None
    etl_dt_range: Optional[tuple[str, str]] = None
    etl_dt_latest_n: int = 1
    sample_n_per_type: Optional[int] = 100
    sensitive_columns_blocklist: list[str] = field(
        default_factory=lambda: [
            "MASTERCARD_CUST_ID",
            "Crt_Psn_Id",
            "Updt_Psn_Id",
            "Opr_Psn_Id",
            "creator",
            "updatePerson",
        ]
    )


@dataclass
class RawRecord:
    item_id: str
    item_type: Role
    raw: dict[str, Any]
    shop_lng: Optional[float] = None
    shop_lat: Optional[float] = None
    etl_dt: str = ""


# --- T037: ItemTags / TagSource (Stage 1 output) -------------------------


DIM_ORDER = (
    "category",
    "consumable_type",
    "brand",
    "avg_prc",
    "distance",
    "occasion",
    "taste",
)

# PARAM_ORDER fallback — overridden by pipeline.yaml sft.param_keys
_PARAM_ORDER_FALLBACK = (
    "category", "brand", "distance", "price", "taste", "occasion", "consumable_type",
)

# tag_source allowed values per dim (per contracts/item_tags_v2.md §三族枚举)
TAG_SOURCE_ALLOWED: dict[str, set[str]] = {
    "category": {TagOrigin.RAW, TagOrigin.AI, TagOrigin.MISSING},
    "consumable_type": {TagOrigin.DERIVED, TagOrigin.AI, TagOrigin.MISSING},
    "brand": {TagOrigin.RAW, TagOrigin.AI, TagOrigin.MISSING},
    "avg_prc": {TagOrigin.RAW, TagOrigin.AI, TagOrigin.MISSING},
    "distance": {TagOrigin.GEO, TagOrigin.MISSING},
    "occasion": {TagOrigin.RAW, TagOrigin.AI, TagOrigin.MISSING},
    "taste": {TagOrigin.RAW, TagOrigin.AI, TagOrigin.MISSING},
}


@dataclass
class TagSource:
    category: TagOrigin
    consumable_type: TagOrigin
    brand: TagOrigin
    avg_prc: TagOrigin
    distance: TagOrigin
    occasion: TagOrigin
    taste: TagOrigin

    def as_dict(self) -> dict[str, str]:
        return {
            "category": self.category.value,
            "consumable_type": self.consumable_type.value,
            "brand": self.brand.value,
            "avg_prc": self.avg_prc.value,
            "distance": self.distance.value,
            "occasion": self.occasion.value,
            "taste": self.taste.value,
        }


@dataclass
class ItemTags:
    item_id: str
    item_type: Role
    raw_record: dict[str, Any]
    tags: dict[str, Optional[Any]]  # 8 dims
    tag_source: TagSource
    enriched_at: datetime = field(default_factory=datetime.utcnow)
    llm_model: str = ""
    _format_version: str = ITEM_TAGS_V

    def to_jsonl_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "item_type": self.item_type.value,
            "raw_record": self.raw_record,
            "tags": {k: self.tags.get(k) for k in DIM_ORDER},
            "tag_source": self.tag_source.as_dict(),
            "enriched_at": self.enriched_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "llm_model": self.llm_model,
            "_format_version": self._format_version,
        }


# --- T060: SFTSample / MessageTurn (Stage 3 output) ----------------------


@dataclass
class MessageTurn:
    role: str  # "user" | "assistant" | "system"
    content: str


@dataclass
class SFTSample:
    item_id: str
    item_type: Role
    intent: str
    messages: list[MessageTurn]
    params: dict[str, Optional[Any]]  # {field: [{"op":...,"values":[...]}] or null}
    guide_text: str = ""
    order_by: Optional[str] = None
    scenario_type: str = ""
    negative: bool = False
    negative_type: Optional[str] = None
    covered_dims: list[str] = field(default_factory=list)
    forced_coverage: bool = False
    generated_at: datetime = field(default_factory=datetime.utcnow)
    llm_model: str = ""
    _format_version: str = SFT_CORPUS_V

    def to_jsonl_dict(self, param_order: tuple[str, ...] | None = None) -> dict[str, Any]:
        fields = param_order or _PARAM_ORDER_FALLBACK
        return {
            "messages": [
                {"role": m.role, "content": m.content} for m in self.messages
            ],
            "params": {k: self.params.get(k) for k in fields},
            "guide_text": self.guide_text,
            "_format_version": self._format_version,
            "_meta": {
                "item_id": self.item_id,
                "item_type": self.item_type.value,
                "intent": self.intent,
                "scenario_type": self.scenario_type,
                "generated_at": self.generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "llm_model": self.llm_model,
            },
        }


# --- T079: DistributionReport --------------------------------------------


@dataclass
class DistributionReport:
    total_samples: int
    intent_distribution: dict[str, int]
    param_coverage: dict[str, dict[str, int]]
    op_distribution: dict[str, int]
    negative_distribution: dict[str, int]
    turn_distribution: dict[int, int]
    avg_message_length: float
    dict_coverage: dict[str, int]
    param_combo_count: int
    warnings: list[str] = field(default_factory=list)
    _format_version: str = DISTRIBUTION_REPORT_V


# --- TrainSplit — for splitter output (T089) -----------------------------


@dataclass
class TrainSplit:
    train_path: str
    val_path: str
    test_path: str
    train_ratio: float = 0.8
    val_ratio: float = 0.1
    test_ratio: float = 0.1
    _format_version: str = TRAIN_SPLIT_V