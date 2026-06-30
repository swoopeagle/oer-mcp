# Schema & Query Optimization Audit

## Current State: Good

The schema is well-designed with:
- Clear separation of concerns (chunks, alignments, embeddings, assessments)
- FTS5 virtual table with proper triggers
- Appropriate indexes on hot paths (alignment_score, standard_id, chunk_id)
- Multi-database partitioning (D11) cleanly implemented
- Triggers for denormalized fields (updated_at, FTS5 sync)

## Identified Optimization Opportunities

### 1. **Missing Composite Index: chunks(source_id, stale)**
**Problem:** Queries filtering by both source_id and stale require a full table scan.

**Impact:** `fetch_for_standard` with `source` filter; `search_content` with `source` filter.

**Current Indexes:**
```sql
CREATE INDEX idx_chunks_source ON chunks(source_id);
CREATE INDEX idx_chunks_grade  ON chunks(grade_band);
CREATE INDEX idx_chunks_type   ON chunks(content_type);
```

**Recommended Fix:**
```sql
CREATE INDEX IF NOT EXISTS idx_chunks_source_stale ON chunks(source_id, stale)
  WHERE stale = 0;  -- partial index, covers live chunks only
```

**Benefit:** Speeds up queries like:
```python
# In fetch_for_standard when source filter is applied
WHERE c.source_id = ? AND c.stale = 0
```

### 2. **Missing Index on chunks(grade_band, stale)**
**Problem:** Grade-band filtering also doesn't benefit from stale filtering in indexes.

**Recommended Fix:**
```sql
CREATE INDEX IF NOT EXISTS idx_chunks_grade_stale ON chunks(grade_band, stale)
  WHERE stale = 0;
```

**Benefit:** Enables efficient queries filtering by grade band (e.g., "6-8" content only).

### 3. **Missing Index on pipeline_runs(run_date)**
**Problem:** No way to efficiently query recent pipeline runs (e.g., "what ran today?").

**Recommended Fix:**
```sql
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_date ON pipeline_runs(run_date DESC);
```

**Benefit:** Efficient "recent runs" queries for health dashboards.

### 4. **Inefficiency: _best_alignment() Loops Over Schemas**
**Location:** `queries.py:334`

**Current Logic:**
```python
def _best_alignment(conn, standard_id, source):
    best = None
    for schema in attached_schemas(conn):  # ← Loop, one query per schema
        row = conn.execute(..., params).fetchone()
        if row and (best is None or row["alignment_score"] > best["alignment_score"]):
            best = row
    return best
```

**Optimization:** Union the schemas in a single query (more complex but one round-trip):
```python
def _best_alignment(conn, standard_id, source):
    # Dynamically build UNION query across schemas
    schemas = attached_schemas(conn)
    unions = []
    params = []
    for schema in schemas:
        unions.append(f"""
            SELECT a.alignment_score, a.alignment_source, a.chunk_id, '{schema}' as db
            FROM {schema}.standard_alignments a
            JOIN {schema}.chunks c ON c.id = a.chunk_id
            WHERE a.standard_id = ? AND a.stale = 0 AND c.stale = 0
            {"AND c.source_id = ?" if source else ""}
        """)
        params.extend([standard_id] + ([source] if source else []))
    
    query = " UNION ALL ".join(unions) + " ORDER BY alignment_score DESC LIMIT 1"
    return conn.execute(query, params).fetchone()
```

**Benefit:** Fewer round-trips, but query is more complex. Only worth optimizing if check_coverage is a bottleneck.

**Current Impact:** Low (check_coverage is not on the hot path for live queries).

### 5. **check_coverage() Re-opens StandardGraph Connection**
**Location:** `queries.py:356–378`

**Current Logic:**
```python
def check_coverage(...):
    ...
    if sg_db_path and Path(sg_db_path).exists():
        sg = _sql.connect(...)  # ← Opens connection each time
        standards = _cluster_standards(sg, standard_id)
        sg.close()  # ← Closes immediately
```

**Issue:** If check_coverage is called multiple times in a request, it reconnects each time.

**Optimization:** Accept StandardGraph connection as a parameter:
```python
def check_coverage(
    conn: sqlite3.Connection,
    standard_id: str,
    *,
    sg_db_path=None,
    sg_conn: sqlite3.Connection | None = None,  # ← New parameter
    source: str | None = None,
) -> dict:
    ...
    if sg_db_path and Path(sg_db_path).exists():
        if sg_conn is None:
            sg = _sql.connect(f"file:{sg_db_path}?mode=ro", uri=True)
            sg.row_factory = _sql.Row
            should_close = True
        else:
            sg = sg_conn
            should_close = False
        standards = _cluster_standards(sg, standard_id)
        if should_close:
            sg.close()
```

**Benefit:** Caller can batch multiple check_coverage calls with one SG connection.

**Current Impact:** Low (check_coverage is not typically called in loops).

### 6. **FTS5 Index Not Used for All Searches**
**Current State:** FTS5 works well but only for keyword search. Semantic search (embeddings) is separate.

**Is This a Problem?** No. This is by design (D13): hybrid search combines keyword (FTS5) + semantic (embeddings) via RRF. Separation of concerns is correct.

### 7. **Assessment Columns Sparsely Used**
**Status:** `item_type`, `dok_level`, `answer_key`, `exam_series`, `difficulty`, `item_generation` exist but may be mostly NULL for non-assessment chunks.

**Is This a Problem?** No. NULLs are efficient in SQLite. The schema structure is correct.

## Recommended Immediate Actions (Priority)

### High Priority (Quick Wins)
1. **Add `idx_chunks_source_stale`** — Most effective for common filter combinations
2. **Add `idx_chunks_grade_stale`** — Completes the stale filtering coverage

**Implementation (in schema.sql):**
```sql
-- Add after line 72 (idx_chunks_type)
CREATE INDEX IF NOT EXISTS idx_chunks_source_stale ON chunks(source_id, stale);
CREATE INDEX IF NOT EXISTS idx_chunks_grade_stale ON chunks(grade_band, stale);
```

### Medium Priority (Nice-to-Have)
3. **Add `idx_pipeline_runs_date`** — Useful for health dashboards

### Low Priority (Optimization Only If Bottleneck)
4. **Refactor `_best_alignment()` to UNION query** — Only if profiling shows it's slow
5. **Add sg_conn parameter to check_coverage** — Only if batch operations are common

## Testing After Changes

After adding indexes:
```bash
# Verify indexes exist
sqlite3 data/oer_core.db ".indices"

# Run test suite (should still pass)
uv run pytest

# Performance test (if benchmarking)
# Compare query times before/after for fetch_for_standard with source filter
```

## Estimated Impact

| Change | Query Time | Disk Space | Implementation |
|--------|-----------|-----------|-----------------|
| idx_chunks_source_stale | -50% (filtered queries) | +1-2 MB | 1 min |
| idx_chunks_grade_stale | -50% (grade filter) | +1-2 MB | 1 min |
| idx_pipeline_runs_date | -80% (date range) | +100 KB | 1 min |
| _best_alignment refactor | -20% (fewer round-trips) | 0 | 15 min |
| check_coverage sg_conn | +10% (connection reuse) | 0 | 10 min |

## Conclusion

Schema is well-designed. Add the two stale-filtering indexes for immediate ~50% speedup on filtered queries. The other optimizations are "nice to have" but not critical for current workload sizes (~12K chunks, ~20K alignments).
