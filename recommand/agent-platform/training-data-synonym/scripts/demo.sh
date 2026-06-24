#!/usr/bin/env bash
# 一键 demo:训练数据生成
# 跑 10 门店 × 8 样本,~ 30s
set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
SQL_PATH="${SQL_PATH:-/opt/recommand/recommand/tabale_structer.sql}"
DEMO_OUT="${DEMO_OUT:-/tmp/training_data_demo}"

mkdir -p "$DEMO_OUT"
echo "=== 训练数据生成 (10 门店 × 8 样本) ==="
python "$SCRIPT_DIR/generate_training_data.py" \
    --sql "$SQL_PATH" \
    --dim-dict "$ROOT_DIR/configs/dim_dictionary.yaml" \
    --brand-dict "$ROOT_DIR/configs/brand_dictionary.yaml" \
    --output-dir "$DEMO_OUT" \
    --n-items 10 --count-per-item 8

echo ""
echo "=== 验证 ==="
python "$SCRIPT_DIR/verify.py" --training-dir "$DEMO_OUT"

echo ""
echo "=== Demo 完成 ==="
echo "产物: $DEMO_OUT/{train,val,test,cleaned,distribution_report}.jsonl"
