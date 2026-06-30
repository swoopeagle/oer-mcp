#!/usr/bin/env bash
# Generate SAT/ACT-style items for all CCSS standards not yet covered.
# Needs Ollama + StandardGraph DB. Runs on Mac Studio (gemma4:31b).
# Can shard across two minis for parallel generation.
#
# Usage (single machine):
#   bash scripts/style_gen_loop.sh sat
#   bash scripts/style_gen_loop.sh act
#
# Usage (sharded, two minis):
#   # on mini 2:
#   SHARD=0/2 bash scripts/style_gen_loop.sh sat
#   # on mini 3:
#   SHARD=1/2 bash scripts/style_gen_loop.sh sat
set -euo pipefail

STYLE="${1:-sat}"
CORE_DB="${OER_CORE_DB_PATH:-data/oer_core.db}"
SG_DB="${STANDARDGRAPH_DB_PATH:-$HOME/.standardgraph/common_core.db}"
SHARD="${SHARD:-}"
BATCH=50

if [ ! -f "$SG_DB" ]; then
  echo "StandardGraph DB not found at $SG_DB. Set STANDARDGRAPH_DB_PATH."
  exit 1
fi

echo "=== Style Generation: $STYLE ==="
echo "Core DB:  $CORE_DB"
echo "SG DB:    $SG_DB"
echo "Shard:    ${SHARD:-none}"
echo

SHARD_ARG=""
if [ -n "$SHARD" ]; then
  SHARD_ARG="--shard $SHARD"
fi

uv run python -m oer_ingestion.pipeline style-gen \
  --db "$CORE_DB" \
  --sg-db "$SG_DB" \
  --style "$STYLE" \
  --limit "$BATCH" \
  $SHARD_ARG

echo
echo "=== Style gen pass complete ==="
sqlite3 "$CORE_DB" \
  "SELECT exam_series, COUNT(*) FROM chunks WHERE stale=0 AND item_generation='style_generated' GROUP BY exam_series;"
