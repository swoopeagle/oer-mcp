#!/usr/bin/env bash
# Single-worker keepalive + completion signal for the annotate mop-up. Keeps one
# unsharded Mini worker alive until every flagged alignment has a coverage note,
# then exits with a completion marker (used to auto-trigger M3). Checks remaining
# BEFORE relaunching, so it exits cleanly at zero instead of thrash-relaunching.
set -uo pipefail
cd "$(dirname "$0")/.."

DB="data/oer_core.db"
SG="/Users/devos/projects/intl-math-standards-mcp/data/common_core.db"
REM_SQL="SELECT COUNT(*) FROM standard_alignments WHERE flagged_for_review=1 AND coverage_notes IS NULL AND alignment_source='embedding';"

while true; do
  rem=$(sqlite3 "$DB" "$REM_SQL")
  done_n=$(sqlite3 "$DB" "SELECT COUNT(*) FROM standard_alignments WHERE coverage_notes IS NOT NULL;")
  echo "[finish] done=$done_n remaining=$rem $(date +%H:%M:%S)"
  if [ "${rem:-1}" -eq 0 ] 2>/dev/null; then
    echo "[finish] ANNOTATE COMPLETE — all flagged alignments annotated"
    break
  fi
  if ! pgrep -f "annotate_loop.sh $DB $SG\$" >/dev/null && ! pgrep -f "annotate_loop.sh $DB $SG " >/dev/null; then
    OLLAMA_BASE_URL="http://localhost:11434" OER_ANNOTATE_MODEL="gemma4:26b" \
      nohup bash scripts/annotate_loop.sh "$DB" "$SG" >> /tmp/oer_annotate_mini_all.log 2>&1 &
    disown
    echo "[finish] (re)launched Mini worker $(date +%H:%M:%S)"
  fi
  sleep 90
done
