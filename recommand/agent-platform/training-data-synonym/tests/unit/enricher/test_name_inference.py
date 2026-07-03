"""Unit tests for ``enricher/name_inference`` (v2.5 fallback path).

Covers rule-text detection + substring inference for brand / category /
taste / occasion, plus the ``compute_name_hints`` aggregate entry point.
"""

from __future__ import annotations

from training_data_synonym.enricher.name_inference import (
    compute_name_hints,
    get_product_name,
    infer_brand,
    infer_category,
    infer_occasion,
    infer_taste,
    is_rule_text,
)


# ──────────────────────── is_rule_text ────────────────────────


class TestIsRuleText:
    def test_discount_pattern(self):
        assert is_rule_text("满50减10")

    def test_coupon_pattern(self):
        assert is_rule_text("[券] 满50减10")
        assert is_rule_text("星巴克 30元代金券")
        assert is_rule_text("全场优惠券")

    def test_time_limit(self):
        assert is_rule_text("限时抢购")
        assert is_rule_text("8折优惠")

    def test_redemption(self):
        assert is_rule_text("到店核销")
        assert is_rule_text("有效期至 2027-01-01")

    def test_clean_name(self):
        assert not is_rule_text("星巴克(测试店 0)")
        assert not is_rule_text("瑞幸咖啡")
        assert not is_rule_text("海底捞火锅 人民广场店")

    def test_empty(self):
        assert not is_rule_text("")
        assert not is_rule_text(None)


# ──────────────────────── get_product_name ────────────────────────


class TestGetProductName:
    def test_priority_str_nm(self):
        assert get_product_name({"str_nm": "星巴克(测试店 0)"}) == "星巴克(测试店 0)"

    def test_fallback_shop_name(self):
        assert get_product_name({"shopname": "瑞幸"}) == "瑞幸"

    def test_fallback_coupon_name(self):
        assert get_product_name({"couponname": "[券] 星巴克 30元代金券"}) == (
            "星巴克 30元代金券"  # leading "[券]" stripped
        )

    def test_strip_only_when_informative(self):
        # If only "[券]" remains after strip, keep raw
        n = get_product_name({"couponname": "[券]"})
        assert n == "[券]"

    def test_empty_returns_empty(self):
        assert get_product_name({}) == ""


# ──────────────────────── infer_brand ────────────────────────


class TestInferBrand:
    BRANDS = ["星巴克", "瑞幸", "Costa", "麦当劳"]

    def test_longest_match_wins(self):
        # "星巴克咖啡馆" (5 chars) beats "麦当劳" (3 chars) when both match.
        brands = ["麦当劳", "星巴克咖啡馆", "星巴克"]
        assert infer_brand("星巴克咖啡馆 麦当劳 早餐", brands) == "星巴克咖啡馆"

    def test_basic(self):
        assert infer_brand("星巴克(测试店 0)", self.BRANDS) == "星巴克"

    def test_no_match(self):
        assert infer_brand("外星咖啡馆", self.BRANDS) is None

    def test_empty_name(self):
        assert infer_brand("", self.BRANDS) is None

    def test_rule_text_suppresses(self):
        assert infer_brand("星巴克 30元代金券", self.BRANDS) is None  # rule text

    def test_empty_brands(self):
        assert infer_brand("星巴克", []) is None


# ──────────────────────── infer_category ────────────────────────


class TestInferCategory:
    CATEGORIES = ["咖啡", "奶茶", "快餐", "中餐", "西餐"]

    def test_basic(self):
        assert infer_category("星巴克 咖啡 馆", self.CATEGORIES) == "咖啡"

    def test_longest_match(self):
        # categories with different lengths; "西餐正餐" (4) > "中餐" (2) when both match.
        cats = ["咖啡", "奶茶", "快餐", "中餐", "西餐正餐"]
        assert infer_category("中餐 西餐正餐 套餐", cats) == "西餐正餐"

    def test_no_match(self):
        assert infer_category("未知料理", self.CATEGORIES) is None

    def test_rule_text(self):
        assert infer_category("咖啡 满50减10", self.CATEGORIES) is None


# ──────────────────────── infer_taste ────────────────────────


class TestInferTaste:
    TASTES = ["甜", "咸", "辣", "微辣", "冰"]

    def test_single_match(self):
        assert infer_taste("冰咖啡", self.TASTES) == ["冰"]

    def test_multiple_matches(self):
        # both 甜 and 冰 present
        result = infer_taste("甜味冰镇", self.TASTES)
        assert "甜" in result
        assert "冰" in result

    def test_no_match(self):
        assert infer_taste("原味", self.TASTES) == []

    def test_rule_text(self):
        assert infer_taste("甜 满50减10", self.TASTES) == []


# ──────────────────────── infer_occasion ────────────────────────


class TestInferOccasion:
    OCCASIONS = ["早餐", "午餐", "下午茶", "晚餐", "周末", "通勤"]

    def test_basic(self):
        assert infer_occasion("周末咖啡", self.OCCASIONS) == "周末"

    def test_longest_match(self):
        # 下午茶 (3 chars) > 早餐 (2) when both present
        assert infer_occasion("早餐 + 下午茶 套餐", self.OCCASIONS) == "下午茶"

    def test_rule_text(self):
        assert infer_occasion("下午茶 限时抢购", self.OCCASIONS) is None


# ──────────────────────── compute_name_hints (aggregate) ────────────────────────


class TestComputeNameHints:
    DIM_DICT = {
        "category": {"values": ["咖啡", "奶茶", "快餐", "中餐"]},
        "brand": {"values": ["星巴克", "瑞幸", "麦当劳"]},
        "taste": {"values": ["甜", "咸", "辣", "冰"]},
        "occasion": {"values": ["早餐", "下午茶", "周末"]},
    }

    def test_full_inference(self):
        raw = {"str_nm": "星巴克 咖啡 下午茶 冰"}
        hints = compute_name_hints(raw, self.DIM_DICT, ["星巴克", "瑞幸"])
        assert hints["brand"] == "星巴克"
        assert hints["category"] == "咖啡"
        assert hints["occasion"] == "下午茶"
        assert "冰" in hints["taste"]

    def test_empty_raw(self):
        assert compute_name_hints({}, self.DIM_DICT, []) == {}

    def test_rule_text_name(self):
        raw = {"couponname": "星巴克 30元代金券"}
        hints = compute_name_hints(raw, self.DIM_DICT, ["星巴克"])
        assert hints == {}  # rule text → no inference

    def test_no_match(self):
        raw = {"str_nm": "外星料理"}
        hints = compute_name_hints(raw, self.DIM_DICT, ["星巴克"])
        assert all(v in (None, [], "") for v in hints.values())

    def test_brand_only_from_separate_dict(self):
        """brand_values passed separately from dim_dict (e.g., from
        brand_dictionary.yaml with 60+ entries)."""
        raw = {"str_nm": "Tim_Hortons 咖啡"}
        hints = compute_name_hints(
            raw,
            self.DIM_DICT,
            ["星巴克", "瑞幸", "Tim_Hortons", "Costa"],
        )
        assert hints["brand"] == "Tim_Hortons"
        assert hints["category"] == "咖啡"
