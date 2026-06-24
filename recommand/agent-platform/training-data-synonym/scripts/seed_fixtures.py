"""Generate fixture data for MockHiveReader tests.

Usage:
    python scripts/seed_fixtures.py [--rows-per-table 100]

Produces 7 fixture jsonl files in tests/fixtures/hive/.
This is a development convenience; production never reads these.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "hive"
FIX.mkdir(parents=True, exist_ok=True)

CAT_NUMS = ["咖啡", "奶茶", "快餐", "中餐", "西餐", "日料", "火锅", "烧烤", "烘焙", "甜品", "便利店", "水果"]
MERCH_BY_CAT = {
    "咖啡": ["星巴克", "瑞幸", "Costa"],
    "奶茶": ["喜茶", "奈雪", "蜜雪冰城", "一点点"],
    "快餐": ["肯德基", "麦当劳", "汉堡王", "必胜客"],
    "中餐": ["海底捞", "真功夫", "永和大王"],
    "西餐": ["必胜客"],
    "日料": [],
    "火锅": ["海底捞"],
    "烧烤": [],
    "烘焙": ["味多美", "好利来", "巴黎贝甜"],
    "甜品": ["味多美"],
    "便利店": ["7_Eleven", "全家", "罗森"],
    "水果": [],
}
AVG_RANGE = [(10, 30), (30, 50), (50, 100), (100, 200), (200, 500)]


def rand_lng_lat(rng: random.Random, has_geo: bool):
    if not has_geo:
        return None, None
    return (
        round(rng.uniform(121.3, 121.6), 6),
        round(rng.uniform(31.1, 31.4), 6),
    )


def gen_meituan_shop(rng: random.Random, idx: int, has_geo: bool) -> dict:
    cat = rng.choice(CAT_NUMS)
    merch_pool = MERCH_BY_CAT.get(cat) or ["其他"]
    merch = rng.choice(merch_pool)
    avg = rng.randint(*rng.choice(AVG_RANGE))
    lng, lat = rand_lng_lat(rng, has_geo)
    return {
        "Str_Id": str(100000 + idx),
        "Str_Nm": f"{merch}(测试店 {idx})",
        "Cat_Nm": cat,
        "Brnd_Nm": merch,
        "Avg_Prc": str(avg),
        "Lng": lng if lng is not None else "",
        "Lat": lat if lat is not None else "",
        "str_Meituan_Sta": 1,
        "Str_Type": "美团",
        "City_Cd": "021",
        "City_Nm": "上海",
        "Cnty_Nm": "静安",
        "Addr": f"南京西路 {1000 + idx} 号",
        "Crt_Psn_Id": "OPERATOR_001",  # sensitive — must be stripped by MockHiveReader
        "etl_dt": "20260620",
    }


def gen_self_shop(rng: random.Random, idx: int, has_geo: bool) -> dict:
    cat = rng.choice(CAT_NUMS)
    merch_pool = MERCH_BY_CAT.get(cat) or ["自营品牌"]
    merch = rng.choice(merch_pool)
    avg = rng.randint(*rng.choice(AVG_RANGE))
    return {
        "shopId": str(200000 + idx),
        "shopName": f"{merch}(自营店 {idx})",
        "shopAbbr": merch[:4],
        "shopStatus": "正常",
        "catId": rng.randint(1, 50),
        "Brnd_Nm": merch,
        "Mnt_Pern_Usr_Num": str(avg),
        "Opr_Psn_Id": "OPERATOR_002",  # sensitive
        "etl_dt": "20260620",
    }


def gen_self_address(rng: random.Random, idx: int, has_geo: bool) -> dict:
    """For join with self_shop; 80% have geo."""
    if not has_geo and idx % 5 != 0:
        return None  # 80% coverage
    lng, lat = rand_lng_lat(rng, True)
    return {
        "Id": idx,
        "shopId": str(200000 + idx),
        "cityId": 289,  # Shanghai
        "detailAddr": f"中山北路 {2000 + idx} 号",
        "longitude": lng if lng is not None else 0.0,
        "latitude": lat if lat is not None else 0.0,
    }


def gen_coupon_template(rng: random.Random, idx: int, has_geo: bool) -> dict:
    cat = rng.choice(CAT_NUMS)
    merch_pool = MERCH_BY_CAT.get(cat) or ["通用"]
    merch = rng.choice(merch_pool)
    face = rng.choice([10, 20, 30, 50, 100])
    cur = round(face * rng.uniform(0.3, 0.7), 2)
    return {
        "couponId": str(300000 + idx),
        "couponName": f"{merch}{face}元代金券",
        "couponType": "代金券",
        "facePrice": float(face),
        "currentPrice": cur,
        "productDesc": f"本券适用于{merch}门店,满{face * 2}元可用",
        "ruleDescription": f"本券不可叠加;使用前请出示;门店:{merch}",
        "couponstatus": "在售",
        "couponSource": "兴业银行",
        "creator": "运营_007",  # sensitive
        "etl_dt": "20260620",
    }


def gen_coupon_shop(rng: random.Random, idx: int, has_geo: bool) -> dict:
    """70% of coupons bind to a shop."""
    if idx % 10 < 7:
        return None
    return {
        "id": idx,
        "couponId": str(300000 + idx),
        "suitType": "门店",
        "merchantId": str(100000 + idx),  # matches meituan_shop
        "merchantName": f"美团门店 {idx}",
    }


def gen_category_meituan(rng: random.Random, idx: int, has_geo: bool) -> dict:
    cat = rng.choice(CAT_NUMS)
    return {
        "Id": idx,
        "Cat_Id": rng.randint(1, 999),
        "Cat_Nm": cat,
        "Std_Lv1": 1,
    }


def gen_category_mapping(rng: random.Random, idx: int, has_geo: bool) -> dict:
    cat = rng.choice(CAT_NUMS)
    return {
        "Id": idx,
        "Prnt_Id": 0,
        "Cat_Nm": cat,
        "sortNo": idx,
        "Std_Lv1": 1,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows-per-table", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    n = args.rows_per_table

    # 美团门店: 50 有 lng/lat + 50 无
    rows = []
    for i in range(n):
        has_geo = (i < 50)
        rows.append(gen_meituan_shop(rng, i, has_geo))
    (FIX / "o2o_new_gut_shop_base_third.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    )

    # 自拓展门店
    rows = [gen_self_shop(rng, i, True) for i in range(n)]
    (FIX / "o2o_new_gut_shop_base.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    )

    # 自拓展地址(80% 覆盖)
    rows = [r for i in range(n) if (r := gen_self_address(rng, i, True)) is not None]
    (FIX / "o2o_new_gut_shop_address.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    )

    # 优惠券模板
    rows = [gen_coupon_template(rng, i, True) for i in range(n)]
    (FIX / "o2o_new_gut_coupon_template.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    )

    # 券-门店绑定(70% 覆盖)
    rows = [r for i in range(n) if (r := gen_coupon_shop(rng, i, True)) is not None]
    (FIX / "o2o_new_gut_coupon_shop.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    )

    # 美团品类映射
    rows = [gen_category_meituan(rng, i, True) for i in range(20)]
    (FIX / "o2o_new_gut_shop_category_meituan.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    )

    # 品类 mapping
    rows = [gen_category_mapping(rng, i, True) for i in range(20)]
    (FIX / "o2o_new_gut_shop_category_mapping.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    )

    print(f"Seeded fixtures to {FIX}: {n} rows per core table")


if __name__ == "__main__":
    main()