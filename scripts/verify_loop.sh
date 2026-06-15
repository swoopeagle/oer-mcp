#!/usr/bin/env bash
# Self-resuming gemma-verified alignment upgrade (D20) across both databases.
# Loops `verify` over each DB until no flagged embedding alignment remains,
# surviving per-item timeouts/crashes. Endpoint/model from env
# (OLLAMA_BASE_URL, OER_ANNOTATE_MODEL). Exits with a completion marker.
set -uo pipefail
cd "$(dirname "$0")/.."

SG="/Users/devos/projects/intl-math-standards-mcp/data/common_core.db"
DBS=("data/oer_core.db" "data/oer_ncsa.db")
FLAGGED_SQL="SELECT COUNT(*) FROM standard_alignments WHERE flagged_for_review=1 AND alignment_source='embedding';"

for DB in "${DBS[@]}"; do
  [ -f "$DB" ] || continue
  pass=0
  while true; do
    rem=$(sqlite3 "$DB" "$FLAGGED_SQL")
    echo "[verify-loop $DB] pass=$pass flagged=$rem $(date +%H:%M:%S)"
    if [ "${rem:-1}" -eq 0 ] 2>/dev/null; then
      echo "[verify-loop $DB] DONE"
      break
    fi
    pass=$((pass + 1))
    PYTHONUNBUFFERED=1 uv run python -u -m oer_ingestion.pipeline verify \
      --db "$DB" --sg-db "$SG" 2>&1 | grep -vi futurewarning
    sleep 3
  done
done
echo "[verify-loop] ALL DBS VERIFIED"
