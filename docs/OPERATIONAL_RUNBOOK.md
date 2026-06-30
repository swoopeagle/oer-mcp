# OER MCP Operational Runbook

## Quick Start

### Running the MCP Server
```bash
# With core DB only
OER_CORE_DB_PATH=data/oer_core.db uv run oer-mcp

# With optional Khan Academy add-on
OER_CORE_DB_PATH=data/oer_core.db OER_ADDON_DB_PATH=data/oer_ncsa.db uv run oer-mcp
```

### Running Local Verification & Annotation
```bash
# Verify 1,269 moderate-band embeddings (no API calls)
uv run python scripts/local_verify_alignments.py --db data/oer_core.db --sg-db ~/.standardgraph/common_core.db

# Annotate high-confidence alignments with coverage notes (no API calls)
uv run python scripts/local_annotate_alignments.py --db data/oer_core.db --sg-db ~/.standardgraph/common_core.db

# Dry-run first to see what would happen
uv run python scripts/local_verify_alignments.py --dry-run
uv run python scripts/local_annotate_alignments.py --dry-run
```

## Data Pipeline

### 7-Stage Ingestion Pipeline

**Stage 1-3: Fetch → Snapshot → Chunk → Load** (No Ollama needed)
```bash
# OpenStax (CC BY) → core DB
uv run python -m oer_ingestion.pipeline openstax --book all --db data/oer_core.db

# Illustrative Mathematics (CC BY) → core DB
uv run python -m oer_ingestion.pipeline im --db data/oer_core.db

# Khan Academy (CC BY-NC-SA) → ncsa DB
uv run python -m oer_ingestion.pipeline khan --db data/oer_ncsa.db --channel-db <kolibri.sqlite3>
```

**Stage 4: Embed & Align** (Requires Ollama + StandardGraph)
```bash
uv run python -m oer_ingestion.pipeline embed-align \
    --db data/oer_core.db --sg-db ~/.standardgraph/common_core.db
```

**Stage 5: Verify Embeddings** (Local heuristics, no Ollama)
```bash
uv run python scripts/local_verify_alignments.py --db data/oer_core.db --sg-db ~/.standardgraph/common_core.db
```

**Stage 6: Annotate Coverage** (Local heuristics, no Ollama)
```bash
uv run python scripts/local_annotate_alignments.py --db data/oer_core.db --sg-db ~/.standardgraph/common_core.db
```

**Stage 7: Validate** (No Ollama)
```bash
uv run python -m oer_ingestion.pipeline validate --db data/oer_core.db
```

## Monitoring & Quality

### Run Tests
```bash
# Full suite
uv run pytest

# Specific module
uv run pytest packages/server/tests/test_fetch_for_standard.py

# With coverage
uv run pytest --cov=oer_server --cov=oer_ingestion
```

### Quality Audit
```bash
# Deep alignment quality analysis
uv run python scripts/audit_alignment_quality.py --db data/oer_core.db --sg-db ~/.standardgraph/common_core.db
```

### Benchmark (Measure OER Impact)
```bash
# Run full benchmark with fixed judge
.venv/bin/python scripts/eval/e2e_benchmark.py

# Verbose mode with tool calls
.venv/bin/python scripts/eval/e2e_benchmark.py --verbose
```

## Database Operations

### Check DB Stats
```bash
sqlite3 data/oer_core.db << 'EOF'
.mode column
.headers on

SELECT COUNT(*) as chunks FROM chunks WHERE stale = 0;
SELECT alignment_source, COUNT(*) FROM standard_alignments WHERE stale = 0 GROUP BY alignment_source;
SELECT COUNT(DISTINCT standard_id) FROM standard_alignments WHERE stale = 0;
EOF
```

### Backup/Restore
```bash
# Backup
sqlite3 data/oer_core.db ".backup /tmp/oer_core.backup"

# Restore
sqlite3 data/oer_core.db ".restore /tmp/oer_core.backup"
```

### Sync from Mini 2
```bash
# Pull from devos@100.101.100.96
scp "devos@100.101.100.96:/Users/devos/projects/open education resources/oer-mcp/data/oer_core.db" data/

# Or if already synced, pull updates
rsync -avz "devos@100.101.100.96:/Users/devos/projects/open education resources/oer-mcp/data/" data/
```

## Troubleshooting

### "no such table: chunks_fts"
The FTS5 index wasn't created. Recreate:
```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5(id, title, content, content='chunks', content_rowid='rowid');
-- Rebuild the index from existing chunks
INSERT INTO chunks_fts SELECT rowid, id, title, content FROM chunks;
```

### "ATTACH DATABASE failed"
Check file paths and permissions:
```bash
ls -la data/oer_ncsa.db
ls -la ~/.standardgraph/common_core.db
```

### High memory usage during embed-align
Batch size is too large. Use `--batch-size 100` flag (default: 1000).

### Query timeouts during search_content
Ollama embed timeout (default 3s). Set environment variable:
```bash
OER_EMBED_TIMEOUT=10 uv run oer-mcp
```

## Performance Tuning

### Index Status
```bash
sqlite3 data/oer_core.db "SELECT * FROM pragma_index_list('chunks');"
```

### Query Plans
```bash
sqlite3 data/oer_core.db "EXPLAIN QUERY PLAN SELECT * FROM chunks WHERE source_id='openstax' AND stale=0 LIMIT 10;"
```

### Measure Query Performance
```bash
sqlite3 data/oer_core.db ".timer ON"
SELECT * FROM chunks WHERE source_id='openstax' AND stale=0 LIMIT 100;
```

## Key Design Decisions

- **Three-database layout (D11):** CC BY → core.db, CC BY-NC-SA → ncsa.db, AP items → ap.db
- **Confidence hierarchy (D20):** human > publisher_guide > llm_verified > embedding
- **Grade penalty (D18):** 0.02 per grade-year away from standard level
- **Generic exercise exclusion (D18):** Skip "Writing Exercises", "Self-Check" etc.
- **FTS5 fallback (D13):** Keyword search if Ollama embed times out

## Contacts

- **StandardGraph DB:** ~/.standardgraph/common_core.db
- **Mini 2 (pipeline runner):** devos@100.101.100.96
- **Ollama host:** ianwangm1max@100.77.63.73 (gemma4:31b, nomic-embed-text)

---

**Last updated:** June 30, 2026
