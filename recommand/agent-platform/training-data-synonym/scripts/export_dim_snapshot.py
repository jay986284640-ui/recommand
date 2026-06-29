"""Export Stage 1 dim values → configs/dim_dictionary_snapshot.yaml.

Merges actual Stage 1 output values (from item_tags.jsonl) with the
authoritative dim_dictionary.yaml, placing actual values first.

Usage: python scripts/export_dim_snapshot.py /tmp/out_hive/item_tags.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

FIELDS = ["category", "consumable_type", "merchant", "avg_prc", "distance", "age", "occasion", "taste"]


def main() -> None:
    in_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "item_tags.jsonl"

    # Count actual values
    counters = {f: Counter() for f in FIELDS}
    for line in in_path.open(encoding="utf-8"):
        r = json.loads(line)
        t = r["tags"]
        for f in FIELDS:
            v = t.get(f)
            if v is None:
                continue
            if isinstance(v, list):
                for x in v:
                    counters[f][x] += 1
            else:
                counters[f][v] += 1

    # Load authoritative dict
    full_dict = yaml.safe_load(
        (ROOT / "configs" / "dim_dictionary.yaml").read_text(encoding="utf-8")
    )

    def build_snapshot(field: str) -> list[str]:
        counter = counters[field]
        actual = [k for k, _ in counter.most_common()]
        dict_vals = full_dict.get(field, {}).get("values", []) or []
        remaining = [v for v in dict_vals if v not in actual]
        return actual + remaining

    snapshot = {
        "_meta": {
            "version": "2.5-stage1-snapshot",
            "source": str(in_path),
            "items": sum(1 for _ in in_path.open(encoding="utf-8")),
            "merged_with": "configs/dim_dictionary.yaml",
        },
    }
    for f in FIELDS:
        snapshot[f] = {
            "desc": full_dict.get(f, {}).get("desc", ""),
            "op": full_dict.get(f, {}).get("op", "in"),
            "values": build_snapshot(f),
        }

    out_path = ROOT / "configs" / "dim_dictionary_snapshot.yaml"
    out_path.write_text(
        yaml.dump(snapshot, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    print(f"Wrote {out_path}")
    for f in FIELDS:
        n_actual = len(counters[f])
        n_total = len(snapshot[f]["values"])
        print(f"  {f}: {n_actual} from Stage1 + dict = {n_total} total")


if __name__ == "__main__":
    main()