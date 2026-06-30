#!/usr/bin/env bash
# Ingest open-licensed assessment content into oer_core.db.
# Run when compute is free (no Ollama needed; pure fetch+parse+load).
#
# Usage:
#   bash scripts/ingest_assessments.sh [--core-db PATH] [--skip-sbac] [--skip-naep]
#
# Defaults to data/oer_core.db. Run from the repo root.
set -euo pipefail

CORE_DB="${OER_CORE_DB_PATH:-data/oer_core.db}"
SNAPSHOTS="data/raw/snapshots"
SKIP_SBAC=0
SKIP_NAEP=0

for arg in "$@"; do
  case "$arg" in
    --core-db=*) CORE_DB="${arg#*=}" ;;
    --skip-sbac) SKIP_SBAC=1 ;;
    --skip-naep) SKIP_NAEP=1 ;;
  esac
done

echo "=== OER MCP Assessment Ingestion ==="
echo "Core DB: $CORE_DB"
echo

# Step 0: run any pending schema migrations
echo "[migrate] applying assessment schema..."
uv run python -m oer_ingestion.pipeline migrate --db "$CORE_DB"

# Step 1: load exam crosswalks (reference data, fast)
echo
echo "[crosswalks] loading SAT/ACT/AP/NAEP/SBAC crosswalk seed..."
uv run python -m oer_ingestion.pipeline crosswalks --db "$CORE_DB"

# Step 2: Smarter Balanced (CC BY — largest open item bank)
if [ "$SKIP_SBAC" = "0" ]; then
  echo
  echo "[smarter-balanced] fetching SBAC sample items (grades 3-8, 11)..."
  echo "NOTE: verify SBAC API endpoint before large runs (see adapter TODO)"
  uv run python -m oer_ingestion.pipeline smarter-balanced \
    --db "$CORE_DB" \
    --snapshots "$SNAPSHOTS"
fi

# Step 3: NAEP (public domain, grades 4/8/12)
if [ "$SKIP_NAEP" = "0" ]; then
  echo
  echo "[naep] fetching NAEP released items (grades 4, 8, 12)..."
  echo "NOTE: verify NAEP API endpoint before large runs (see adapter TODO)"
  uv run python -m oer_ingestion.pipeline naep \
    --db "$CORE_DB" \
    --snapshots "$SNAPSHOTS"
fi

echo
echo "=== Assessment ingestion complete ==="
echo "Next steps:"
echo "  1. Run embed-align to generate embeddings + CCSS alignment"
echo "  2. Run validate to check DB health"
sqlite3 "$CORE_DB" "SELECT content_type, COUNT(*) FROM chunks WHERE stale=0 GROUP BY content_type;"
