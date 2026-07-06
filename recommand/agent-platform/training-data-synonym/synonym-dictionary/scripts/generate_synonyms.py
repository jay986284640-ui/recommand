"""同义词词表生成主脚本(对齐兴业 O2O 真实业务)

3 源混合(沿用 spec 003 D-007 合并去重):
  1. 品牌词典(brand_dictionary.yaml, 60+ 品牌)→ SynonymGroup
  2. 品类词典(category_dictionary.yaml, 30+ 品类)→ SynonymGroup
  3. mock-llm 抽取(从门店名 + 品类名启发式)→ SynonymGroup
  + 字符 n-gram 简单聚类(替代 embedding 聚类,无 bge-small-zh 依赖)
  + 反义词过滤(内置 50+ 对)
  → ES Solr 多向格式输出

输出:
  - synonyms_solr.txt       ES synonym_graph filter 消费
  - synonyms_meta.json      元信息
  - synonyms_stats.json     统计
  - synonym_rejections.jsonl  反义词拒收日志
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required: pip install pyyaml", file=sys.stderr)
    raise

sys.path.insert(0, str(Path(__file__).parent))
from mock_llm_client import MockLLMClient  # noqa: E402


# ── 反义词表(内置 50+ 对,代码常量) ────────────────────────────────
ANTONYM_PAIRS: List[Tuple[str, str]] = [
    # 程度
    ("大", "小"), ("高", "低"), ("长", "短"), ("多", "少"),
    ("胖", "瘦"), ("厚", "薄"), ("宽", "窄"), ("深", "浅"),
    # 温度
    ("热", "冷"), ("温", "凉"), ("冰", "烫"), ("热", "凉"),
    # 味道
    ("甜", "咸"), ("甜", "辣"), ("咸", "辣"), ("甜", "酸"),
    ("咸", "酸"), ("辣", "酸"), ("苦", "甜"), ("苦", "咸"),
    ("浓", "淡"), ("鲜", "涩"),
    # 方向
    ("左", "右"), ("上", "下"), ("前", "后"), ("里", "外"),
    ("东", "西"), ("南", "北"),
    # 状态
    ("好", "坏"), ("新", "旧"), ("干", "湿"), ("生", "熟"),
    ("开", "关"), ("满", "空"),
    # 数量
    ("有", "无"), ("加", "减"), ("满", "缺"),
    # 速度/时间
    ("快", "慢"), ("早", "晚"), ("今", "明"), ("日", "夜"),
    # 偏好
    ("喜欢", "讨厌"), ("接受", "拒绝"),
]


# ── 工具 ──────────────────────────────────────────────────────────
def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def char_ngrams(s: str, n: int = 2) -> Set[str]:
    """字符 n-gram(用于简单相似度)"""
    s = s.lower().strip()
    if len(s) < n:
        return {s}
    return {s[i:i+n] for i in range(len(s) - n + 1)}


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── 1. 品牌源 ─────────────────────────────────────────────────────
def groups_from_brand_dict(path: Path) -> List[Dict[str, Any]]:
    """从 brand_dictionary.yaml 抽 SynonymGroup"""
    data = load_yaml(path)
    groups: List[Dict[str, Any]] = []
    for b in data.get("brands", []):
        canonical = b["canonical"]
        variants = b.get("variants", [])
        if len(variants) < 2:
            continue
        groups.append({
            "group_id": hashlib.md5(canonical.encode()).hexdigest()[:12],
            "canonical": canonical,
            "variants": list(set(variants + [canonical])),
            "source": ["rule_brand"],
            "confidence": 1.0,
            "category": b.get("category"),
        })
    return groups


# ── 2. 品类源 ─────────────────────────────────────────────────────
def groups_from_category_dict(path: Path) -> List[Dict[str, Any]]:
    """从 category_dictionary.yaml 抽 SynonymGroup"""
    data = load_yaml(path)
    groups: List[Dict[str, Any]] = []
    for c in data.get("categories", []):
        canonical = c["canonical"]
        variants = c.get("variants", [])
        # 也把 aliases 加进去
        variants = list(set(variants + c.get("aliases", []) + [canonical]))
        if len(variants) < 2:
            continue
        groups.append({
            "group_id": hashlib.md5(f"cat-{canonical}".encode()).hexdigest()[:12],
            "canonical": canonical,
            "variants": variants,
            "source": ["rule_category"],
            "confidence": 1.0,
            "category": canonical,
        })
    return groups


# ── 3. LLM 抽取(从门店名 + 品类) ─────────────────────────────────
def groups_from_llm(
    shop_names: List[str],
    client: MockLLMClient,
    brand_dict: Dict[str, List[str]],
    category_dict: Dict[str, List[str]],
) -> List[Dict[str, Any]]:
    """mock-llm 启发式:对每门店,生成该品牌的 1 组同义变体

    简单策略:对每个门店名,先在品牌词典里找 hit,扩展其 variants
    """
    groups: List[Dict[str, Any]] = []
    seen_canonicals: Set[str] = set()

    for shop_name in shop_names:
        # 启发:扫描 shop_name 是否含 brand 词典里的 canonical
        shop_lower = shop_name.lower()
        for canonical, variants in brand_dict.items():
            if canonical.lower() in shop_lower or any(
                v.lower() in shop_lower for v in variants
            ):
                if canonical in seen_canonicals:
                    continue
                seen_canonicals.add(canonical)
                # 二次启发:让 mock-llm "扩展" 1-2 个同义变体
                extended = client.extract_synonyms(shop_name, {canonical: variants})
                if extended:
                    variants = list(set(extended[0] + [canonical]))
                groups.append({
                    "group_id": hashlib.md5(f"llm-{canonical}".encode()).hexdigest()[:12],
                    "canonical": canonical,
                    "variants": variants,
                    "source": ["llm"],
                    "confidence": 0.8,
                    "category": None,
                })
    return groups


# ── 4. 字符 n-gram 聚类(替代 embedding) ──────────────────────────
def groups_from_ngram(
    tokens: List[str],
    threshold: float = 0.7,
) -> List[Dict[str, Any]]:
    """字符 n-gram Jaccard 聚类,无 embedding 依赖

    策略:连通分量,阈值 ≥ 0.7 视为同组
    """
    ngrams = [(t, char_ngrams(t, 2)) for t in tokens if t]
    parent = list(range(len(ngrams)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for i in range(len(ngrams)):
        for j in range(i + 1, len(ngrams)):
            if jaccard(ngrams[i][1], ngrams[j][1]) >= threshold:
                union(i, j)

    clusters: Dict[int, List[str]] = defaultdict(list)
    for idx, (token, _) in enumerate(ngrams):
        clusters[find(idx)].append(token)

    groups: List[Dict[str, Any]] = []
    for cluster_tokens in clusters.values():
        if len(cluster_tokens) < 2:
            continue
        # 长度限制:每组 2~10
        if len(cluster_tokens) > 10:
            cluster_tokens = cluster_tokens[:10]
        canonical = cluster_tokens[0]
        groups.append({
            "group_id": hashlib.md5(
                f"ng-{'-'.join(sorted(cluster_tokens))}".encode()
            ).hexdigest()[:12],
            "canonical": canonical,
            "variants": list(set(cluster_tokens + [canonical])),
            "source": ["ngram"],
            "confidence": 0.6,
            "category": None,
        })
    return groups


# ── 5. 反义词过滤(SC-004) ────────────────────────────────────────
def filter_antonyms(
    groups: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """拒收含反义词的组"""
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    antonym_set: Set[Tuple[str, str]] = set()
    for a, b in ANTONYM_PAIRS:
        antonym_set.add((a, b))
        antonym_set.add((b, a))

    for g in groups:
        variants_lower = {v.lower() for v in g["variants"]}
        is_antonym = False
        for a, b in antonym_set:
            if a in variants_lower and b in variants_lower:
                is_antonym = True
                g["_rejection"] = f"antonym pair ({a}, {b})"
                break
        if is_antonym:
            rejected.append(g)
        else:
            kept.append(g)
    return kept, rejected


# ── 6. 长度限制 + 去重(FR-004) ──────────────────────────────────
def length_filter(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """单词 ≤ 20 字符 + 每组 2~10 词"""
    out: List[Dict[str, Any]] = []
    for g in groups:
        # 单词长度限制
        g["variants"] = [v for v in g["variants"] if len(v) <= 20 and v.strip()]
        # 移除空字符串
        g["variants"] = [v for v in g["variants"] if v]
        if not g["variants"]:
            continue
        # 拆组(超过 10)
        if len(g["variants"]) > 10:
            for i in range(0, len(g["variants"]), 10):
                chunk = g["variants"][i:i+10]
                if len(chunk) >= 2:
                    sub = dict(g)
                    sub["variants"] = chunk
                    out.append(sub)
        elif len(g["variants"]) >= 2:
            out.append(g)
    return out


def dedup_groups(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 variants 集合去重,合并 source"""
    by_key: Dict[frozenset, Dict[str, Any]] = {}
    for g in groups:
        key = frozenset(g["variants"])
        if key in by_key:
            existing = by_key[key]
            existing["source"] = list(set(existing["source"] + g["source"]))
            existing["confidence"] = max(existing["confidence"], g["confidence"])
        else:
            by_key[key] = g
    return list(by_key.values())


# ── 7. Solr 格式输出(FR-005) ──────────────────────────────────────
def write_solr(groups: List[Dict[str, Any]], path: Path) -> None:
    """1 行 1 组,逗号+空格分隔,头部注释,末尾 \n"""
    lines: List[str] = []
    lines.append(f"# 同义词词表 (synonyms_v1)")
    lines.append(f"# Generated at: {datetime.utcnow().isoformat()}Z")
    src_dist = Counter()
    for g in groups:
        for s in g.get("source", []):
            src_dist[s] += 1
    total = sum(src_dist.values()) or 1
    src_str = "; ".join(
        f"{k}={v/total:.0%}" for k, v in src_dist.most_common()
    )
    lines.append(f"# Source distribution: {src_str}")
    lines.append(f"# Total groups: {len(groups)}")
    lines.append(f"# Embedding model: char_ngram(threshold=0.7)")
    for g in groups:
        lines.append(", ".join(g["variants"]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── 主入口 ────────────────────────────────────────────────────────
def generate_synonyms(
    brand_dict_path: Path,
    category_dict_path: Path,
    output_dir: Path,
    n_items: int = 100,
    seed: int = 42,
) -> Dict[str, Any]:
    """主入口:从 3 源生成同义词词表"""
    # 1. 加载品牌 + 品类字典
    brand_data = load_yaml(brand_dict_path)
    brand_dict: Dict[str, List[str]] = {
        b["canonical"]: b.get("variants", [])
        for b in brand_data.get("brands", [])
    }
    cat_data = load_yaml(category_dict_path)
    cat_dict: Dict[str, List[str]] = {
        c["canonical"]: c.get("variants", [])
        for c in cat_data.get("categories", [])
    }

    # 2. 合成门店名(用品牌 + 品类字典里的 token)
    import random
    rng = random.Random(seed)
    shop_names: List[str] = []
    for i in range(n_items):
        canon = rng.choice(list(brand_dict.keys()))
        variant = rng.choice(brand_dict[canon])
        city = rng.choice(["北京", "上海", "广州", "深圳", "杭州"])
        shop_names.append(f"{city} {variant} 门店")

    # 3. mock-llm 抽取
    client = MockLLMClient()

    # 4. 3 源生成
    print(f"[1/5] 品牌源: {len(brand_dict)} 品牌", file=sys.stderr)
    g_brand = groups_from_brand_dict(brand_dict_path)
    print(f"  → {len(g_brand)} 组", file=sys.stderr)

    print(f"[2/5] 品类源: {len(cat_dict)} 品类", file=sys.stderr)
    g_cat = groups_from_category_dict(category_dict_path)
    print(f"  → {len(g_cat)} 组", file=sys.stderr)

    print(f"[3/5] LLM 抽取源: {n_items} 门店", file=sys.stderr)
    g_llm = groups_from_llm(shop_names, client, brand_dict, cat_dict)
    print(f"  → {len(g_llm)} 组", file=sys.stderr)

    print(f"[4/5] 字符 n-gram 聚类源", file=sys.stderr)
    # 收集所有 token 用于聚类
    all_tokens: List[str] = []
    for d in (brand_dict, cat_dict):
        for canonical, variants in d.items():
            all_tokens.append(canonical)
            all_tokens.extend(variants)
    g_ngram = groups_from_ngram(all_tokens, threshold=0.7)
    print(f"  → {len(g_ngram)} 组", file=sys.stderr)

    # 5. 合并 4 源
    all_groups = g_brand + g_cat + g_llm + g_ngram
    print(f"[5/5] 4 源合并 + 反义词过滤 + 长度限制", file=sys.stderr)
    print(f"  合并前: {len(all_groups)} 组", file=sys.stderr)

    # 长度限制
    all_groups = length_filter(all_groups)
    # 去重(多源标记)
    all_groups = dedup_groups(all_groups)
    print(f"  长度限制 + 去重后: {len(all_groups)} 组", file=sys.stderr)

    # 反义词过滤
    kept, rejected = filter_antonyms(all_groups)
    print(f"  反义词拒收: {len(rejected)} 组", file=sys.stderr)

    # 6. 输出
    output_dir.mkdir(parents=True, exist_ok=True)
    solr_path = output_dir / "synonyms_solr.txt"
    write_solr(kept, solr_path)
    print(f"  → {solr_path}", file=sys.stderr)

    # meta
    meta = {
        "_format_version": "synonyms_v1",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source_distribution": {
            src: sum(1 for g in kept if src in g.get("source", []))
            for src in {"rule_brand", "rule_category", "llm", "ngram"}
        },
        "total_groups": len(kept),
        "total_tokens": sum(len(g["variants"]) for g in kept),
        "antonym_rejected_count": len(rejected),
        "embedding_model": "char_ngram(threshold=0.7)",
    }
    (output_dir / "synonyms_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # stats
    cat_coverage = Counter(g.get("category") for g in kept if g.get("category"))
    src_overlap = Counter()
    for g in kept:
        srcs = sorted(g.get("source", []))
        for i in range(len(srcs)):
            for j in range(i+1, len(srcs)):
                src_overlap[f"{srcs[i]}_{srcs[j]}"] += 1
    all_tokens_in_groups = []
    for g in kept:
        all_tokens_in_groups.extend(g["variants"])
    top10 = Counter(all_tokens_in_groups).most_common(10)
    stats = {
        "total_groups": len(kept),
        "avg_group_size": round(
            sum(len(g["variants"]) for g in kept) / max(len(kept), 1), 2
        ),
        "category_coverage": dict(cat_coverage),
        "antonym_rejected_count": len(rejected),
        "source_overlap": dict(src_overlap),
        "top_10_canonical": [t[0] for t in top10],
    }
    (output_dir / "synonyms_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # rejections
    with open(output_dir / "synonym_rejections.jsonl", "w", encoding="utf-8") as f:
        for r in rejected:
            f.write(json.dumps(
                {"group_id": r["group_id"], "canonical": r["canonical"],
                 "variants": r["variants"], "reason": r.get("_rejection")},
                ensure_ascii=False,
            ) + "\n")

    return {
        "total_groups": len(kept),
        "antonym_rejected": len(rejected),
        "source_distribution": meta["source_distribution"],
    }


# ── CLI ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="同义词词表生成")
    parser.add_argument("--brand-dict", required=True, help="品牌词典 yaml")
    parser.add_argument("--category-dict", required=True, help="品类词典 yaml")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    parser.add_argument("--n-items", type=int, default=100, help="门店数(LLM 抽取触发)")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    result = generate_synonyms(
        brand_dict_path=Path(args.brand_dict),
        category_dict_path=Path(args.category_dict),
        output_dir=Path(args.output_dir),
        n_items=args.n_items,
        seed=args.seed,
    )
    print("\n=== Result ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
