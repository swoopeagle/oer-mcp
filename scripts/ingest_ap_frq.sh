#!/usr/bin/env bash
# Ingest AP free-response questions into oer_ap.db.
# Requires: uv add pypdf --group dev (PDF parsing)
# Run from the repo root.
#
# Usage:
#   bash scripts/ingest_ap_frq.sh [--ap-db PATH] [--years 2020,2021,2022]
set -euo pipefail

AP_DB="${OER_AP_DB_PATH:-data/oer_ap.db}"
SNAPSHOTS="data/raw/snapshots"

for arg in "$@"; do
  case "$arg" in
    --ap-db=*) AP_DB="${arg#*=}" ;;
  esac
done

echo "=== AP FRQ Ingestion ==="
echo "AP DB: $AP_DB"
echo "Subjects: AP Calculus AB, AP Calculus BC, AP Statistics, AP Precalculus"
echo

# Check pypdf is available
if ! uv run python -c "import pypdf" 2>/dev/null; then
  echo "Installing pypdf..."
  uv add pypdf --group dev
fi

# Migrate schema on the AP DB
echo "[migrate] applying assessment schema to AP DB..."
uv run python -m oer_ingestion.pipeline migrate --db "$AP_DB"

# Ingest FRQs
echo "[ap-frq] fetching and parsing FRQ PDFs..."
uv run python -m oer_ingestion.pipeline ap-frq \
  --db "$AP_DB" \
  --snapshots "$SNAPSHOTS"

echo
echo "=== AP FRQ ingestion complete ==="
sqlite3 "$AP_DB" \
  "SELECT exam_series, COUNT(*) FROM chunks WHERE stale=0 AND content_type='assessment' GROUP BY exam_series;"
