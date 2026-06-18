#!/usr/bin/env bash
# Keep the compute arsenal productively busy with VALUABLE work: gemma-verify
# (then annotate) the lower-confidence alignment bands, where embedding alignment
# is noisiest and LLM confirmation adds the most precision. Strong band (>=0.78)
# was done in Phase 1; this cascades through moderate then light.
#
# Idempotent & self-resuming (state = flagged_for_review / alignment_source /
# coverage_notes). Optional shard "N/M" (first arg) splits work across machines
# with no overlap — run one per Ollama endpoint, each pointed at a different host
# via OLLAMA_BASE_URL / OER_ANNOTATE_MODEL. All workers run here (DBs are local);
# only the gemma inference fans out. WAL + busy_timeout handle concurrent writers.
#
# Launch (two machines):
#   OLLAMA_BASE_URL=http://localhost:11434      OER_ANNOTATE_MODEL=gemma4:26b \
#     nohup bash scripts/mini_supervisor.sh 0/2 > /tmp/oer_sup_mini.log 2>&1 & disown
#   OLLAMA_BASE_URL=http://100.70.170.62:11434  OER_ANNOTATE_MODEL=gemma4:12b \
#     nohup bash scripts/mini_supervisor.sh 1/2 > /tmp/oer_sup_win.log  2>&1 & disown
set -uo pipefail
cd "$(dirname "$0")/.."

SG="/Users/devos/projects/intl-math-standards-mcp/data/common_core.db"
PY=".venv/bin/python"
DBS=(data/oer_core.db data/oer_ncsa.db)
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}" OER_ANNOTATE_MODEL="${OER_ANNOTATE_MODEL:-gemma4:26b}"

SHARD="${1:-}"
SHARD_SQL=""; SHARD_ARGS=()
if [ -n "$SHARD" ]; then
  N="${SHARD%/*}"; M="${SHARD#*/}"
  SHARD_SQL="AND id % $M = $N"
  SHARD_ARGS=(--shard "$SHARD")
fi
TAG="${SHARD:+[$SHARD] }"

log(){ echo "[sup ${TAG}$(date '+%m-%d %H:%M:%S')] $*"; }

log "starting on $OLLAMA_BASE_URL ($OER_ANNOTATE_MODEL); waiting out any benchmark..."
while pgrep -f "oer_ingestion.benchmark" >/dev/null; do sleep 60; done
log "clear to run"

flag_band(){  # lo hi — flag unverified, un-annotated embedding alignments in the band
  for db in "${DBS[@]}"; do
    [ -f "$db" ] && sqlite3 "$db" "UPDATE standard_alignments SET flagged_for_review=1 \
      WHERE alignment_source='embedding' AND coverage_notes IS NULL \
      AND alignment_score>=$1 AND alignment_score<$2;"
  done
}

verify_all(){
  for db in "${DBS[@]}"; do
    [ -f "$db" ] || continue
    local prev=-1 rem
    while true; do
      rem=$(sqlite3 "$db" "SELECT COUNT(*) FROM standard_alignments WHERE flagged_for_review=1 AND alignment_source='embedding' $SHARD_SQL;")
      log "verify $(basename "$db") flagged_remaining=$rem"
      [ "${rem:-0}" -eq 0 ] 2>/dev/null && break
      [ "$rem" = "$prev" ] && { log "verify $(basename "$db") no progress ($rem unverifiable) — moving on"; break; }
      prev=$rem
      $PY -u -m oer_ingestion.pipeline verify --db "$db" --sg-db "$SG" ${SHARD_ARGS[@]+"${SHARD_ARGS[@]}"} 2>&1 | grep -vi futurewarning || true
      sleep 2
    done
  done
}

annotate_all(){
  for db in "${DBS[@]}"; do
    [ -f "$db" ] || continue
    log "annotate $(basename "$db")"
    $PY -u -m oer_ingestion.pipeline annotate --db "$db" --sg-db "$SG" ${SHARD_ARGS[@]+"${SHARD_ARGS[@]}"} 2>&1 | grep -vi futurewarning || true
  done
}

for band in "0.70 0.78" "0.65 0.70"; do
  set -- $band
  log "===== BAND $1–$2 : flag → verify → annotate ====="
  flag_band "$1" "$2"
  verify_all
  annotate_all
  log "===== BAND $1–$2 COMPLETE ====="
done

log "ALL BANDS DONE for this shard."
