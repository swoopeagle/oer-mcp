#!/usr/bin/env bash
# Overnight orchestrator (hands-free): finish IM verify → annotate core →
# authoritative D9 benchmark → validate. Resilient to Studio's recurring Ollama
# wedge: polls Studio for recovery, judges on IWPC (never on Studio — co-loading
# the 31b judge with the 72b agent is what wedged it), falls back to IWPC's 14b.
# Log: /tmp/oer_overnight_YYYYMMDD_HHMMSS.log    Monitor: tail -f that file.
set -uo pipefail

PROJECT="/Users/devos/projects/open education resources/oer-mcp"
SG_ROOT="/Users/devos/projects/intl-math-standards-mcp"
SG_DB="$SG_ROOT/data/common_core.db"
CORE_DB="$PROJECT/data/oer_core.db"
NCSA_DB="$PROJECT/data/oer_ncsa.db"
VENV="$PROJECT/.venv/bin/python"
LOG="/tmp/oer_overnight_$(date +%Y%m%d_%H%M%S).log"

STUDIO="http://169.254.1.1:11434"
MINI="http://localhost:11434"
IWPC="http://100.70.170.62:11434"

cd "$PROJECT"
exec >> "$LOG" 2>&1
ts() { date "+%H:%M:%S"; }
echo "$(ts) ═══ overnight run started ═══  log=$LOG"

# generate-test a model on a host (returns 0 if it actually produces output)
alive() {  # $1=baseurl $2=model
  local out
  out=$(curl -s --max-time 45 "$1/api/generate" \
        -d "{\"model\":\"$2\",\"prompt\":\"hi\",\"stream\":false,\"options\":{\"num_predict\":2}}" \
        2>/dev/null | "$VENV" -c "import sys,json;print(json.load(sys.stdin).get('response','') or '')" 2>/dev/null)
  [ -n "$out" ]
}

# ── Phase 1: wait for any in-flight verify ────────────────────────────────
for pid in $(pgrep -f "oer_ingestion.pipeline verify" 2>/dev/null); do
  echo "$(ts) [1] waiting for verify pid $pid"
  while kill -0 "$pid" 2>/dev/null; do sleep 20; done
done
echo "$(ts) [1] verify idle"

# ── Phase 2: annotate core + ncsa (Mini gemma4:26b — reliable) ────────────
echo "$(ts) [2] annotate"
for DB in "$CORE_DB" "$NCSA_DB"; do
  OLLAMA_BASE_URL="$MINI" OER_ANNOTATE_MODEL="gemma4:26b" OER_OLLAMA_API="generate" \
    "$VENV" -u -m oer_ingestion.pipeline annotate --db "$DB" --sg-db "$SG_DB" || true
done
echo "$(ts) [2] annotate done"

# ── Phase 3: authoritative D9 benchmark ───────────────────────────────────
# Prefer Studio 72b agent; poll up to ~3h for it to un-wedge. Judge on IWPC.
echo "$(ts) [3] benchmark — polling Studio 72b (judge=IWPC gemma4:12b)"
AGENT_URL="" AGENT_MODEL=""
for i in $(seq 1 36); do            # 36 × 5min ≈ 3h
  if alive "$STUDIO" "qwen2.5:72b"; then
    AGENT_URL="$STUDIO"; AGENT_MODEL="qwen2.5:72b"
    echo "$(ts) [3] Studio 72b is alive — using it as agent"; break
  fi
  echo "$(ts) [3] Studio still wedged (try $i/36); sleeping 5m"
  sleep 300
done
if [ -z "$AGENT_URL" ]; then
  echo "$(ts) [3] Studio never recovered — FALLBACK to IWPC qwen2.5:14b agent"
  AGENT_URL="$IWPC"; AGENT_MODEL="qwen2.5:14b"
fi

OER_AGENT_URL="$AGENT_URL" OER_AGENT_MODEL="$AGENT_MODEL" \
OER_JUDGE_URL="$IWPC" OER_JUDGE_MODEL="gemma4:12b" \
OER_AGENT_TIMEOUT="300" OER_MAX_TURNS="12" \
STANDARDGRAPH_ROOT="$SG_ROOT" \
  "$VENV" -u scripts/eval/e2e_benchmark.py --verbose || true
echo "$(ts) [3] benchmark done (agent=$AGENT_MODEL @ $AGENT_URL)"

# ── Phase 4: validate ─────────────────────────────────────────────────────
echo "$(ts) [4] validate"
"$VENV" -u -m oer_ingestion.pipeline validate --db "$CORE_DB" || true
"$VENV" -u -m oer_ingestion.pipeline validate --db "$NCSA_DB" || true

echo "$(ts) ═══ overnight run finished ═══"
