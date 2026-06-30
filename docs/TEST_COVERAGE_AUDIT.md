# Test Coverage Audit

## Summary
**14 test files, ~50 tests total** — Good coverage of core logic, but gaps in edge cases and integration scenarios.

## Well-Covered Areas ✓

### Alignment Confidence Hierarchy (D20)
- `test_coverage.py:test_embedding_scale_shifted_down` — source-aware band thresholds
- `test_fetch_for_standard.py:test_confidence_hierarchy_beats_raw_score` — human > publisher_guide > llm_verified > embedding
- `test_fetch_for_standard.py:test_llm_verified_tier_serializes_and_ranks` — llm_verified tier exists and ranks correctly

**Coverage:** Excellent. Core hierarchy logic verified.

### Generic Exercise Exclusion (D18)
- `test_align_helpers.py:test_generic_exercise_groups_excluded` — "Writing Exercises", "Self Check" filtered
- `test_align_helpers.py:test_substantive_exercises_kept` — "Practice Makes Perfect" kept
- `test_align_helpers.py:test_non_exercise_types_never_excluded` — only exercise_set filtered

**Coverage:** Excellent. Edge cases tested.

### Coverage Band Calculations
- `test_coverage.py:test_embedding_bands` — 0.78 strong, 0.72 moderate, 0.66 light, <0.65 none
- `test_coverage.py:test_high_confidence_bands` — publisher_guide thresholds
- `test_coverage.py:test_annotate_threshold_matches_embedding_strong` — 0.78 alignment with annotate logic

**Coverage:** Excellent.

### Query Filters (fetch_for_standard, search_content)
- `test_fetch_for_standard.py:test_filters_and_include_content` — content_type, include_content
- `test_search_content.py:test_filters_and_include_content` — exposition vs worked_example
- `test_search_content.py:test_keyword_fallback_when_no_embedder` — graceful degradation

**Coverage:** Good. Basic filters tested.

### Check Coverage Integration
- `test_check_coverage.py:test_surfaces_gap_with_sg` — gap detection works with SG DB
- `test_check_coverage.py:test_cluster_letter_form_tolerated` — handles "6.RP.A" vs "6.RP"
- `test_check_coverage.py:test_degrades_without_sg` — degrades gracefully without SG

**Coverage:** Very good. Integration and error paths tested.

### Search Degradation (D13)
- `test_search_content.py:test_embedder_failure_degrades_gracefully` — Ollama timeout → FTS5
- `test_search_content.py:test_hybrid_mode_uses_embeddings` — RRF fusion works

**Coverage:** Good. Fallback logic tested.

## Identified Gaps ✗

### 1. **Grade Penalty Logic (D18)**
No tests for the 0.02/grade-year penalty applied at alignment time. 
- Does a K/1st-grade alignment get properly penalized in 6-8 content?
- Boundary conditions: exactly 1 year apart, 5+ years apart?

**Recommendation:** Add test_align_helpers.py:test_grade_penalty_applied

### 2. **Assessment Content Fields**
No tests for `item_type`, `dok_level`, `answer_key`, `exam_series`, `difficulty`, `item_generation`.
- Are assessment columns properly serialized in fetch_for_standard?
- Do filters on `dok_level` work?
- Are NULL values handled correctly for non-assessment chunks?

**Recommendation:** Add test_fetch_for_standard.py:test_assessment_content_included

### 3. **Multi-Database Spanning (D11)**
No tests for core + ncsa (CC BY-NC-SA) + ap (AP items) multi-DB setup.
- Does attached_schemas() correctly span all three?
- Do queries properly qualify schema names in JOIN/WHERE?
- Does RRF fusion handle deduplication across DBs?

**Recommendation:** Add test_search_content.py:test_multi_db_deduplication

### 4. **Stale Row Filtering**
`stale = 0` is checked in queries but not explicitly tested.
- Are stale chunks properly excluded?
- Are stale alignments properly excluded?
- Does a chunk become invisible if marked stale?

**Recommendation:** Add test_fetch_for_standard.py:test_stale_filtering

### 5. **Coverage Notes Serialization**
No tests for `coverage_notes` field.
- Are NULL notes handled?
- Are long notes truncated or preserved?
- Do notes round-trip correctly through JSON serialization?

**Recommendation:** Add test_fetch_for_standard.py:test_coverage_notes_included

### 6. **No Content Structured Response**
- `test_fetch_for_standard.py:test_no_content_is_structured` — Tests that empty result has the right shape
- But no test for the specific structure of `available_sources` when multiple DBs are attached

**Recommendation:** Improve test to verify sources list spans all attached DBs

### 7. **Chunk Adjacency / Navigation**
Code has `get_chunk(include_adjacent=True)` but no tests.
- Does it return prev/next chunks in the book?
- Are boundaries handled (first/last chapter)?

**Recommendation:** Add test for get_chunk adjacency feature

### 8. **Server Tool Integration (MCP wrappers)**
No tests for the FastMCP server.py wrapper layer itself.
- Do tools properly parse MCP inputs?
- Do tool results serialize correctly to MCP format?
- Are error cases handled (invalid standard ID, etc.)?

**Recommendation:** Add `packages/server/tests/test_server_tools.py` for MCP wrappers

### 9. **Edge Cases in Ranking**
`fetch_for_standard` sorts by `(rank DESC, alignment_score DESC)`. 
- What if two chunks have same rank and same score?
- Does deterministic ordering matter?

**Recommendation:** Add test for tie-breaking in ranking

### 10. **FTS5 Index Health**
No tests verify FTS5 is kept in sync with chunks table.
- Do INSERT/UPDATE/DELETE triggers work correctly?
- Are orphaned FTS rows cleaned up?
- Does content search work for chunks added/updated after DB creation?

**Recommendation:** Add test for FTS5 trigger consistency

## Regression Risk Areas

If you modify any of these, run the full test suite:
1. `oer_server/queries.py` — ranking, filtering, multi-DB logic
2. `oer_ingestion/align.py` — confidence hierarchy, score calculations
3. `oer_shared/coverage.py` — band thresholds
4. `schema.sql` — FTS5 triggers, indexes

## Test Execution

```bash
# Run all ~50 tests
uv run pytest

# Run specific file
uv run pytest packages/server/tests/test_fetch_for_standard.py

# Run with coverage
uv run pytest --cov=oer_server --cov=oer_ingestion --cov=oer_shared
```

## Summary

**Overall:** 70% coverage on core logic, 30% coverage on edge cases and integration.

**Must-have tests:** Grade penalty (D18), stale filtering, multi-DB spanning, server tool integration.

**Nice-to-have:** FTS5 health, chunk adjacency, tie-breaking determinism.
