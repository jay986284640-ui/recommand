#!/usr/bin/env bash
# 一键 demo:同义词词表生成
# 跑 10 门店,~ 5s
set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DEMO_OUT="${DEMO_OUT:-/tmp/synonym_demo}"

mkdir -p "$DEMO_OUT"
echo "=== 同义词词表生成 (4 源:品牌 + 品类 + LLM + n-gram) ==="
python "$SCRIPT_DIR/generate_synonyms.py" \
    --brand-dict "$ROOT_DIR/configs/brand_dictionary.yaml" \
    --category-dict "$ROOT_DIR/configs/category_dictionary.yaml" \
    --output-dir "$DEMO_OUT" \
    --n-items 10

echo ""
echo "=== 验证 ==="
python "$SCRIPT_DIR/verify.py" --synonyms-dir "$DEMO_OUT"

echo ""
echo "=== Demo 完成 ==="
echo "产物: $DEMO_OUT/synonyms_solr.txt"
