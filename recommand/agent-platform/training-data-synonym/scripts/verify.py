"""验证脚本:训练数据(SC 002/004/005/007/008/009/010)"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _check(name: str, passed: bool, detail: str = "") -> bool:
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}: {detail}")
    return passed


def verify_training(training_dir: Path) -> bool:
    print("[训练数据验证]")
    all_passed = True
    summary_path = training_dir / "summary.json"
    if not summary_path.exists():
        print(f"  ❌ {summary_path} 不存在")
        return False
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for sc, passed in summary.get("sc_passed", {}).items():
        # SC-007 / SC-009 在 < 50 样本时波动大,小数据集跳过
        skip_sc = {"SC-007_negative_ratio", "SC-009_distribution"}
        if sc in skip_sc and summary.get("raw_count", 0) < 50:
            print(f"  ⏭️  {sc}: 跳过(< 50 样本波动大,实际 {summary.get('raw_count')})")
            continue
        all_passed &= _check(
            sc, passed,
            f"raw={summary.get('raw_count')} cleaned={summary.get('cleaned_count')} "
            f"train/val/test={summary.get('train_count')}/{summary.get('val_count')}/{summary.get('test_count')}"
        )
    for split in ("train", "val", "test"):
        path = training_dir / f"{split}.jsonl"
        if not path.exists():
            continue
        n_ok = n_total = 0
        with open(path) as f:
            for line in f:
                n_total += 1
                try:
                    json.loads(line)
                    n_ok += 1
                except Exception:
                    pass
        all_passed &= _check(
            f"{split}.jsonl 解析", n_ok == n_total, f"{n_ok}/{n_total} 解析成功"
        )
    return all_passed


def main():
    parser = argparse.ArgumentParser(description="验证训练数据")
    parser.add_argument("--training-dir", required=True)
    args = parser.parse_args()
    if verify_training(Path(args.training_dir)):
        print("\n🎉 训练数据全部验证通过")
        sys.exit(0)
    print("\n❌ 部分验证失败")
    sys.exit(1)


if __name__ == "__main__":
    main()
