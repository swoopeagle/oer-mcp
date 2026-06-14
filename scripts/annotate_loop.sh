#!/usr/bin/env bash
# Self-resuming Stage 6 annotate (D18 / task #12). annotate is idempotent and
# skip-resilient, so each pass mops up the previous pass's timeouts. The loop
# re-runs until no flagged alignment is left without a coverage note, surviving
# individual annotate exits/crashes. Whole-loop kills (session boundaries) just
# need a relaunch — progress is committed per item.
#
# Usage: bash scripts/annotate_loop.sh [DB] [SG_DB]
set -uo pipefail
cd "$(dirname "$0")/.."

DB="${1:-data/oer_core.db}"
SG="${2:-/Users/devos/projects/intl-math-standards-mcp/data/common_core.db}"
REMAINING_SQL="SELECT COUNT(*) FROM standard_alignments WHERE flagged_for_review=1 AND coverage_notes IS NULL AND alignment_source='embedding';"

pass=0
while true; do
  remaining=$(sqlite3 "$DB" "$REMAINING_SQL")
  echo "[loop] pass=$pass remaining=$remaining $(date +%H:%M:%S)"
  if [ "${remaining:-1}" -eq 0 ] 2>/dev/null; then
    echo "[loop] ALL DONE"
    break
  fi
  pass=$((pass + 1))
  PYTHONUNBUFFERED=1 uv run python -u -m oer_ingestion.pipeline annotate \
    --db "$DB" --sg-db "$SG" 2>&1 | grep -vi futurewarning
  sleep 3
done
