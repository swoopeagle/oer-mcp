#!/usr/bin/env bash
# Self-resuming Stage 6 annotate (D18 / task #12). annotate is idempotent and
# skip-resilient, so each pass mops up the previous pass's timeouts. The loop
# re-runs until no flagged alignment is left without a coverage note, surviving
# individual annotate exits/crashes. Whole-loop kills (session boundaries) just
# need a relaunch — progress is committed per item.
#
# Usage: bash scripts/annotate_loop.sh [DB] [SG_DB] [SHARD]
#   SHARD is optional "N/M" — this worker handles rows where id % M == N.
#   Endpoint/model come from env: OLLAMA_BASE_URL, OER_ANNOTATE_MODEL.
# Two-worker example (Studio + Mini in parallel):
#   OLLAMA_BASE_URL=http://169.254.1.1:11434 OER_ANNOTATE_MODEL=gemma4:31b-it-q8_0 \
#     bash scripts/annotate_loop.sh data/oer_core.db "$SG" 0/2 &
#   OLLAMA_BASE_URL=http://localhost:11434   OER_ANNOTATE_MODEL=gemma4:26b \
#     bash scripts/annotate_loop.sh data/oer_core.db "$SG" 1/2 &
set -uo pipefail
cd "$(dirname "$0")/.."

DB="${1:-data/oer_core.db}"
SG="${2:-/Users/devos/projects/intl-math-standards-mcp/data/common_core.db}"
SHARD="${3:-}"

shard_clause=""
shard_args=()
if [ -n "$SHARD" ]; then
  n="${SHARD%/*}"; m="${SHARD#*/}"
  shard_clause="AND id % $m = $n"
  shard_args=(--shard "$SHARD")
fi
REMAINING_SQL="SELECT COUNT(*) FROM standard_alignments WHERE flagged_for_review=1 AND coverage_notes IS NULL AND alignment_source='embedding' $shard_clause;"

pass=0
while true; do
  remaining=$(sqlite3 "$DB" "$REMAINING_SQL")
  echo "[loop${SHARD:+ $SHARD}] pass=$pass remaining=$remaining $(date +%H:%M:%S)"
  if [ "${remaining:-1}" -eq 0 ] 2>/dev/null; then
    echo "[loop${SHARD:+ $SHARD}] ALL DONE"
    break
  fi
  pass=$((pass + 1))
  PYTHONUNBUFFERED=1 uv run python -u -m oer_ingestion.pipeline annotate \
    --db "$DB" --sg-db "$SG" ${shard_args[@]+"${shard_args[@]}"} 2>&1 | grep -vi futurewarning
  sleep 3
done
