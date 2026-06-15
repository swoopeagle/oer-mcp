#!/usr/bin/env bash
# Keep the two sharded annotate workers (Studio + Mini) alive until every
# flagged alignment has a coverage note, then exit with a completion marker.
# Restarts a shard worker if it dies (session-boundary kills, crashes).
# Run via run_in_background so its exit notifies the agent → start M3.
set -uo pipefail
cd "$(dirname "$0")/.."

DB="data/oer_core.db"
SG="/Users/devos/projects/intl-math-standards-mcp/data/common_core.db"
REM_SQL="SELECT COUNT(*) FROM standard_alignments WHERE flagged_for_review=1 AND coverage_notes IS NULL AND alignment_source='embedding';"

ensure() {  # shard url model logname
  if ! pgrep -f "annotate_loop.sh $DB $SG $1" >/dev/null; then
    OLLAMA_BASE_URL="$2" OER_ANNOTATE_MODEL="$3" \
      nohup bash scripts/annotate_loop.sh "$DB" "$SG" "$1" >> "/tmp/oer_annotate_$4.log" 2>&1 &
    disown
    echo "[watchdog] (re)launched $4 worker shard $1 $(date +%H:%M:%S)"
  fi
}

while true; do
  rem=$(sqlite3 "$DB" "$REM_SQL")
  done_n=$(sqlite3 "$DB" "SELECT COUNT(*) FROM standard_alignments WHERE coverage_notes IS NOT NULL;")
  echo "[watchdog] done=$done_n remaining=$rem $(date +%H:%M:%S)"
  if [ "${rem:-1}" -eq 0 ] 2>/dev/null; then
    echo "[watchdog] ANNOTATE COMPLETE — all flagged alignments annotated"
    break
  fi
  ensure 0/2 http://169.254.1.1:11434 gemma4:31b-it-q8_0 studio
  ensure 1/2 http://localhost:11434 gemma4:26b mini
  sleep 120
done
