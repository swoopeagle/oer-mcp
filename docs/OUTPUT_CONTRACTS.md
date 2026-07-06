# OER MCP — tool output contracts

Machine-facing reference for the 8 MCP tools' response envelopes. Every tool
returns a JSON object. This documents the success shape per tool and the uniform
failure shape shared by all.

## Success / failure discriminator

**Any tool response containing a top-level `error` key is a failure; otherwise it
succeeded.** On failure the tool returns exactly:

```json
{ "error": { "code": "internal_error", "type": "<ExceptionClassName>", "message": "<str>" } }
```

No success response carries an `error` key, so `"error" in response` is a reliable
test. Success responses never raise; validation problems surface as a normal
success envelope with an empty/`unknown_*` result field (see per-tool notes).

## Conventions

- **Input echo** — every tool echoes its primary input key (`standard_id`,
  `chunk_id`, or `query`) so a response is self-describing out of context.
- **`count`** — tools returning a `results` list also return `count` (=
  `len(results)`).
- **`results[]` items** are `ChunkResult` objects (see below), uniform across
  `fetch_for_standard` and `search_content`.
- **Attribution** — every content-bearing item carries a non-null `attribution`
  string that must be preserved downstream.

## Per-tool success envelopes

### `fetch_for_standard`
```
{ standard_id: str, count: int, results: ChunkResult[] }
```
Results ranked by alignment confidence then content usefulness. `count == 0` (empty
`results`) means no aligned content — not an error.

### `search_content`
```
{ query: str, search_mode: "hybrid" | "keyword_fallback", count: int, results: ChunkResult[] }
```
`search_mode == "keyword_fallback"` signals the query embedder was unreachable and
results came from FTS5 keyword search only.

### `get_chunk`
```
{ chunk_id, title, content, content_type, source, source_url, attribution,
  chapter, section, grade_band, alignment_score, alignment_source, alignments[],
  coverage_notes,
  # assessment-only fields (null for non-assessment chunks):
  item_type, dok_level, answer_key, exam_series, exam_year, difficulty, item_generation }
```
A **flat** chunk object (not wrapped in an envelope) — this is a single-item GET.
`alignments[]` lists every standard the chunk aligns to. A missing chunk returns
`{ chunk_id, result: "not_found" }`.

### `check_coverage`
```
{ standard_id, standards_checked: str[], sources_checked: str[],
  overall_coverage: "strong" | "moderate" | "light" | "none",
  sub_standards: [ { standard_id, coverage, counts... } ],
  gaps: str[], gap_detection: {...} }
```
Accepts a leaf standard or a cluster; `sub_standards` expands a cluster.

### `list_sources`
```
{ databases_attached: str[], sources: SourceInfo[],
  total_chunks: int, total_standards_aligned: int }
```

### `map_to_assessments`
```
{ standard_id, crosswalk: [...], crosswalk_coverage: {...},
  items_by_exam: { <exam_series>: [...] }, items_status: "ready" | "no_item_store",
  gaps: str[] }
```
`items_status == "no_item_store"` means the DB predates the assessment columns
(healed on next `connect(create=True)`); the crosswalk is still returned.

### `get_learning_path`
```
{ standard_id, depth: int, sg_available: bool, path: [...], prerequisite_gaps: str[] }
```
`sg_available == false` means StandardGraph wasn't reachable → `path` contains only
the target standard's content. An unknown target returns
`{ standard_id, result: "unknown_standard" }`.

### `get_capabilities`
```
{ databases_attached: str[], sources: [...], standard_systems: str[],
  content_types: str[], exam_series: str[], grade_bands: str[],
  alignment_sources: str[], alignment_confidence_bands: {...},
  tools: str[], total_chunks: int, total_alignments: int,
  coverage: {
    distinct_standards_covered: int,
    distinct_standards_by_database: { <db>: int },
    alignments_by_confidence: { <source>: int },
    assessment_items_by_exam: { <exam_series>: int },
    assessment_item_count: int,
    grade_bands_covered: str[],
    prerequisite_graph_available: bool
  } }
```
The discovery call — invoke first to self-configure without probing.

## `ChunkResult` shape (shared by `results[]`)
```
{ chunk_id, source, title, content_type, grade_band,
  content: str | null,          # null unless include_content=true (saves tokens)
  source_url, attribution,
  # assessment-only (null otherwise):
  item_type, dok_level, answer_key, exam_series, exam_year, difficulty, item_generation }
```

## Known non-uniformities (intentional)

- `get_chunk` is a flat object, not an `{...envelope, results}` — it's a single-item
  GET, so the chunk *is* the payload.
- `get_chunk` / `get_learning_path` use a `result: "<reason>"` sentinel for
  not-found / unknown inputs rather than the `error` envelope, because these are
  expected empty states, not failures.
