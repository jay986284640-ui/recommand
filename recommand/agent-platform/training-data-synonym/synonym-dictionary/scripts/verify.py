"""验证脚本:同义词词表(SC 003/004/005)"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple


ANTONYM_PAIRS: List[Tuple[str, str]] = [
    ("大", "小"), ("高", "低"), ("热", "冷"), ("甜", "咸"),
    ("好", "坏"), ("新", "旧"), ("快", "慢"), ("浓", "淡"),
    ("有", "无"), ("前", "后"),
]


def _check(name: str, passed: bool, detail: str = "") -> bool:
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}: {detail}")
    return passed


def verify_synonyms(synonyms_dir: Path) -> bool:
    print("[同义词验证]")
    all_passed = True
    solr_path = synonyms_dir / "synonyms_solr.txt"
    if not solr_path.exists():
        print(f"  ❌ {solr_path} 不存在")
        return False
    lines = solr_path.read_text(encoding="utf-8").splitlines()
    has_empty = any(line.strip() == "" for line in lines)
    all_passed &= _check("无空行", not has_empty)
    bad_comment = [l for l in lines if l.startswith("#") and "," in l]
    all_passed &= _check(
        "注释行无逗号", not bad_comment,
        f"{len(bad_comment)} 个坏注释" if bad_comment else "",
    )
    group_lines = [l for l in lines if l.strip() and not l.startswith("#")]
    n_groups = len(group_lines)
    all_passed &= _check("1 行 1 组", n_groups > 0, f"{n_groups} 组")
    bad_long = []
    for line in group_lines:
        for tok in line.split(","):
            if len(tok.strip()) > 20:
                bad_long.append(tok)
    all_passed &= _check(
        "单词 ≤ 20 字符", not bad_long,
        f"{len(bad_long)} 个超长" if bad_long else "",
    )
    all_passed &= _check(
        "总组数 ≤ 10000 (SC-005)", n_groups <= 10000, f"{n_groups} 组"
    )
    antonym_violations = 0
    for line in group_lines:
        tokens = {t.strip().lower() for t in line.split(",")}
        for a, b in ANTONYM_PAIRS:
            if a in tokens and b in tokens:
                antonym_violations += 1
                break
    all_passed &= _check(
        "反义词不合并 (SC-004)", antonym_violations == 0,
        f"{antonym_violations} 个违反" if antonym_violations else "",
    )
    meta = json.loads((synonyms_dir / "synonyms_meta.json").read_text(encoding="utf-8"))
    all_passed &= _check(
        "meta._format_version", meta.get("_format_version") == "synonyms_v1"
    )
    return all_passed


def main():
    parser = argparse.ArgumentParser(description="验证同义词词表")
    parser.add_argument("--synonyms-dir", required=True)
    args = parser.parse_args()
    if verify_synonyms(Path(args.synonyms_dir)):
        print("\n🎉 同义词全部验证通过")
        sys.exit(0)
    print("\n❌ 部分验证失败")
    sys.exit(1)


if __name__ == "__main__":
    main()
