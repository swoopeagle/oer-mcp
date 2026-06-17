#!/usr/bin/env bash
# Keep the Mac Mini productively busy with VALUABLE compute: gemma-verify (and
# then annotate) the lower-confidence alignment bands, which is where embedding
# alignment is noisiest and LLM confirmation adds the most precision. Strong
# band (>=0.78) was done in Phase 1; this cascades through moderate then light.
#
# Idempotent & self-resuming: re-running picks up wherever it left off (state
# lives in flagged_for_review / alignment_source / coverage_notes). Each band:
# flag → verify-loop (with no-progress guard) → annotate.
#
# Launch:  nohup bash scripts/mini_supervisor.sh > /tmp/oer_mini_sup.log 2>&1 & disown
set -uo pipefail
cd "$(dirname "$0")/.."

SG="/Users/devos/projects/intl-math-standards-mcp/data/common_core.db"
PY=".venv/bin/python"
DBS=(data/oer_core.db data/oer_ncsa.db)
export OLLAMA_BASE_URL="http://localhost:11434" OER_ANNOTATE_MODEL="gemma4:26b"

log(){ echo "[mini-sup $(date '+%m-%d %H:%M:%S')] $*"; }

# Don't compete with a running benchmark for the single local gemma.
log "starting; waiting for any running benchmark to finish..."
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
      rem=$(sqlite3 "$db" "SELECT COUNT(*) FROM standard_alignments WHERE flagged_for_review=1 AND alignment_source='embedding';")
      log "verify $(basename "$db") flagged_remaining=$rem"
      [ "${rem:-0}" -eq 0 ] 2>/dev/null && break
      [ "$rem" = "$prev" ] && { log "verify $(basename "$db") no progress ($rem unverifiable) — moving on"; break; }
      prev=$rem
      $PY -u -m oer_ingestion.pipeline verify --db "$db" --sg-db "$SG" 2>&1 | grep -vi futurewarning || true
      sleep 2
    done
  done
}

annotate_all(){
  for db in "${DBS[@]}"; do
    [ -f "$db" ] || continue
    log "annotate $(basename "$db")"
    $PY -u -m oer_ingestion.pipeline annotate --db "$db" --sg-db "$SG" 2>&1 | grep -vi futurewarning || true
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

log "ALL BANDS DONE — corpus verified+annotated down to 0.65. Nothing left to chew."
