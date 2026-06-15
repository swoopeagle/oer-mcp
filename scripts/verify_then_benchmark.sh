#!/usr/bin/env bash
# Wait for the D20 verify run to finish (both DBs, 0 flagged embedding rows
# left), keeping a verify worker alive meanwhile, then run the D9 benchmark and
# write bench.json. Detached so it survives session boundaries.
set -uo pipefail
cd "$(dirname "$0")/.."

SG="/Users/devos/projects/intl-math-standards-mcp/data/common_core.db"
CORE="data/oer_core.db"; NCSA="data/oer_ncsa.db"
FLAG="SELECT COUNT(*) FROM standard_alignments WHERE flagged_for_review=1 AND alignment_source='embedding';"

flagged() { local n=0 c
  for db in "$CORE" "$NCSA"; do [ -f "$db" ] && { c=$(sqlite3 "$db" "$FLAG"); n=$((n + ${c:-0})); }; done
  echo "$n"; }

while true; do
  rem=$(flagged)
  echo "[chain] verify flagged remaining=$rem $(date +%H:%M:%S)"
  [ "${rem:-1}" -eq 0 ] 2>/dev/null && { echo "[chain] VERIFY COMPLETE"; break; }
  if ! pgrep -f "verify_loop.sh" >/dev/null; then
    OLLAMA_BASE_URL=http://localhost:11434 OER_ANNOTATE_MODEL=gemma4:26b \
      nohup bash scripts/verify_loop.sh >> /tmp/oer_verify2.log 2>&1 & disown
    echo "[chain] (re)launched verify worker"
  fi
  sleep 120
done

echo "[chain] starting D9 benchmark $(date +%H:%M:%S)"
OLLAMA_BASE_URL=http://localhost:11434 OER_ANNOTATE_MODEL=gemma4:26b \
PYTHONUNBUFFERED=1 uv run python -u -m oer_ingestion.benchmark \
  --db "$CORE" --addon-db "$NCSA" --sg-db "$SG" \
  --gen-model gemma4:26b --judge-model gemma4:26b --out bench.json 2>&1 | grep -vi futurewarning
echo "[chain] BENCHMARK COMPLETE — bench.json written"
