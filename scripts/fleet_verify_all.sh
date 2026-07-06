#!/usr/bin/env bash
# Fleet-wide gemma/qwen verify of the noisy embedding alignment bands (0.65–0.78)
# across all three content DBs (core / ncsa / state).
#
# Runs FROM the dev MacBook against the LOCAL data/oer_*.db files (freshest build);
# only LLM inference fans out over Tailscale to four Ollama endpoints. WAL +
# busy_timeout=30000 (set in oer_shared.db.connect) make the four concurrent
# writers safe. verify is non-destructive: a YES promotes the row to
# alignment_source='llm_verified' (score 0.90); a NO just clears its
# flagged_for_review bit (row stays 'embedding' at its original low score);
# an empty/unclear answer leaves it flagged for a stronger endpoint's pass.
#
# Two passes per DB:
#   1. parallel — 4 endpoints, shard i/4 each, best model per host
#   2. mop-up   — the strongest endpoint (Studio) sweeps every row the weak
#                 endpoints skipped, looping until the flagged count stops falling
set -uo pipefail
cd "$(dirname "$0")/.."

SG="${SG_DB:-$HOME/.standardgraph/common_core.db}"
DBS=("data/oer_core.db" "data/oer_ncsa.db" "data/oer_state.db")

# endpoint|model  — index 0 is the strongest (used for the mop-up sweep)
WORKERS=(
  "http://100.77.63.73:11434|gemma4:31b-it-q8_0"   # Mac Studio 64GB
  "http://100.101.100.96:11434|gemma4:26b"         # Mac mini 2 24GB
  "http://100.106.61.114:11434|gemma4:12b"         # Mac mini 4
  "http://100.70.170.62:11434|qwen2.5:14b"         # Windows iwpc
)
M=${#WORKERS[@]}

flagged() { sqlite3 "$1" "SELECT COUNT(*) FROM standard_alignments WHERE flagged_for_review=1 AND alignment_source='embedding';"; }

flag_band() {  # flag the un-verified light+moderate embedding band
  sqlite3 "$1" "UPDATE standard_alignments SET flagged_for_review=1
    WHERE alignment_source='embedding' AND alignment_score>=0.65 AND alignment_score<0.78;"
}

# loop verify (optionally on a shard) on one endpoint until its work stops shrinking
verify_loop() {  # db  base_url  model  [shard]
  local db="$1" url="$2" model="$3" shard="${4:-}"
  local shard_args=(); [ -n "$shard" ] && shard_args=(--shard "$shard")
  local prev=-1 rem
  while true; do
    if [ -n "$shard" ]; then
      local n="${shard%/*}" m="${shard#*/}"
      rem=$(sqlite3 "$db" "SELECT COUNT(*) FROM standard_alignments WHERE flagged_for_review=1 AND alignment_source='embedding' AND id % $m = $n;")
    else
      rem=$(flagged "$db")
    fi
    echo "[$(basename "$db") ${shard:-mop} $model] flagged=$rem $(date +%H:%M:%S)"
    [ "${rem:-0}" -eq 0 ] 2>/dev/null && break
    [ "$rem" = "$prev" ] && { echo "[$(basename "$db") ${shard:-mop} $model] no progress ($rem left)"; break; }
    prev=$rem
    OLLAMA_BASE_URL="$url" OER_ANNOTATE_MODEL="$model" OER_OLLAMA_API=generate \
      PYTHONUNBUFFERED=1 uv run python -u -m oer_ingestion.pipeline verify \
        --db "$db" --sg-db "$SG" "${shard_args[@]}" 2>&1 | grep -viE "futurewarning|warnings.warn" || true
    sleep 2
  done
}

for DB in "${DBS[@]}"; do
  [ -f "$DB" ] || { echo "[skip] $DB missing"; continue; }
  echo "===== $(basename "$DB"): flagging band 0.65–0.78 ====="
  flag_band "$DB"
  echo "===== $(basename "$DB"): $(flagged "$DB") flagged — parallel pass across $M endpoints ====="
  pids=()
  for i in "${!WORKERS[@]}"; do
    IFS='|' read -r url model <<<"${WORKERS[$i]}"
    verify_loop "$DB" "$url" "$model" "$i/$M" &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  echo "===== $(basename "$DB"): mop-up on Studio over $(flagged "$DB") remaining ====="
  IFS='|' read -r url model <<<"${WORKERS[0]}"
  verify_loop "$DB" "$url" "$model"
  echo "===== $(basename "$DB") DONE — verified now: $(sqlite3 "$DB" "SELECT COUNT(*) FROM standard_alignments WHERE alignment_source='llm_verified';") ====="
done
echo "[fleet-verify] ALL DBS COMPLETE $(date)"
