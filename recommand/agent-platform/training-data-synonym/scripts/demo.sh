#!/usr/bin/env bash
# 一键 demo:训练数据生成(走新 CLI)
#
# 跑 10 门店/类型 × 4 样本/商品,~ 30s 完成 enrich → sft → split → verify。
# Mock Hive fixtures + Mock LLM,不依赖真实 Hive / 真实 LLM endpoint。
#
# 覆盖:
#   set -uo pipefail (no -e: mock LLM coverage 不达 SC-003 时仍跑完整链路)
#   TABLES_CONFIG: 可覆盖默认 configs/tables.yaml
#   FIXTURE_DIR:   可覆盖默认 tests/fixtures/hive
#   DEMO_OUT:      可覆盖默认 /tmp/training_data_demo
set -uo pipefail
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"

OUT="${DEMO_OUT:-/tmp/training_data_demo}"
TABLES_CONFIG="${TABLES_CONFIG:-$ROOT_DIR/configs/tables.yaml}"
FIXTURE_DIR="${FIXTURE_DIR:-$ROOT_DIR/tests/fixtures/hive}"

mkdir -p "$OUT"

echo "=== Stage 1: enrich (Hive → item_tags.jsonl) ==="
python -m training_data_synonym.cli enrich \
    --tables-config "$TABLES_CONFIG" \
    --source mock --fixture-dir "$FIXTURE_DIR" \
    --output-dir "$OUT" --n-items-per-type 10 || true

echo ""
echo "=== Stage 2: sft (item_tags.jsonl → sft_corpus.jsonl) ==="
python -m training_data_synonym.cli sft \
    --input "$OUT/item_tags.jsonl" \
    --output-dir "$OUT" --count-per-item 4 || true

echo ""
echo "=== Stage 3: split (sft_corpus.jsonl → train/val/test) ==="
python -m training_data_synonym.cli split \
    --input "$OUT/sft_corpus.jsonl" \
    --output-dir "$OUT" || true

echo ""
echo "=== Stage 4: verify (SC self-check) ==="
python -m training_data_synonym.cli verify \
    --output-dir "$OUT" || true

echo ""
echo "=== Demo complete ==="
echo "Artifacts:"
ls -la "$OUT" | sed 's/^/    /'
