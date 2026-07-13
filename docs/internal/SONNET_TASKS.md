# Sonnet Task Backlog — planned by Opus, 2026-06-30

> **Goal:** make OER MCP the best curriculum MCP available — faster, more
> comprehensive, and easier for both machines and humans to use. Three threads:
> **A** (speed), **B** (prerequisite-aware learning paths — the differentiator),
> **C** (machine-friendly API contract). Tasks are beefier than the Haiku round;
> each is a coherent unit of work with a clean commit boundary.

**Baseline at planning time:** `uv run pytest` → **110 passed**. Branch `main`,
clean, ahead of origin by 3 commits (the Round-2 Haiku work). DB at
`data/oer_core.db`. StandardGraph DB present at `~/.standardgraph/common_core.db`
(1.9 GB, read-only — needed by Thread B at runtime; tests use a seeded temp SG).

## Global rules (same as prior rounds)
- Run `uv run pytest -q` before AND after every change; both must be green.
- One task = one commit. Use the message given per task. End every commit with:
  `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`
- **No Anthropic API and no Ollama** are needed. The StandardGraph DB is a *local
  read-only SQLite file* — reading it is fine and expected (Thread B). Never write
  to it.
- Never run `DELETE`/`DROP`, HuggingFace upload, or force-push.
- Make the exact edits specified. If a string to replace isn't found verbatim, or
  reality contradicts a "verified fact" below, **STOP and report** rather than guess.
- Tests must pass against REAL behavior. If you believe source is buggy, capture
  actual behavior in the test and flag with a `# NOTE:` — only the tasks that
  explicitly say "change source" may change source.

## Verified facts (don't re-derive — Opus confirmed these against the live code/DBs)

**Serving path:**
- `packages/server/src/oer_server/queries.py` — pure functions over an open conn;
  span attached DBs via `oer_shared.db.attached_schemas(conn)` → `['main']`,
  `['main','ncsa']`, or all three.
- `server.py` wrappers are plain callables (fastmcp 3.4.2); `server.get_conn()`
  caches a module global `_conn` and is monkeypatchable. Each wrapper wraps the
  query in `try/except Exception → {"error": type(exc).__name__, "detail": str}`.
- `oer_shared.db.connect(core, addon, ap, *, create=False)` opens core as `main`,
  ATTACHes ncsa/ap if the files exist. Sets `foreign_keys=ON`, `busy_timeout`,
  and (only when `create=True`) `journal_mode=WAL` + schema init. **It sets no
  read-side performance PRAGMAs** (mmap/cache_size/query_only) — that's the gap S1B fixes.

**Embeddings (S1A):**
- Table `chunk_embeddings(chunk_id PK, model, vector BLOB, dimensions, created_at)`.
- Vectors are **numpy float32, 768-dim, stored UNNORMALIZED** (`vec.tobytes()`).
- Core DB currently has **1,031** embedded chunks (model `nomic-embed-text`). Small
  matrix (~3 MB) — caching the normalized matrix in memory is trivially safe.
- `queries._semantic_hits` currently re-reads + re-parses + re-normalizes the FULL
  embedding set on **every** call (queries.py ~105). It applies the same SQL filters
  the keyword path uses, then cosine-sorts, returns top-50 ids for RRF fusion.

**StandardGraph schema (S2 — learning paths):**
- `standards(id, system, domain, cluster, standard_text, ...)`. `check_coverage`
  already reads `domain`/`cluster`/`standard_text` from here.
- `standard_relationships(id, source_id, target_id, relationship, system, created_at)`
  with `relationship ∈ {'prerequisite','successor'}`, `UNIQUE(source_id,target_id,relationship)`,
  indexes on both `source_id` and `target_id`.
- **Edge semantics (critical):** a row `(source_id=X, target_id=Y, relationship='prerequisite')`
  means **Y is a prerequisite of X**. So the prerequisites *of* a standard X are:
  `SELECT target_id FROM standard_relationships WHERE source_id=X AND relationship='prerequisite' AND system='ccss'`.
  Verified: prereqs of `CCSS.MATH.7.RP.1` → `6.RP.1`, `6.RP.2`, `6.RP.3`. There are
  938 ccss-math prerequisite edges.

---
---

# THREAD A — Speed

## S1 — Embedding cache + read-side connection tuning

**Why:** `_semantic_hits` is brute-force and uncached — it pulls every embedding
BLOB from disk, `np.frombuffer`s each, `np.vstack`s, and renormalizes, on *every*
`search_content` call. The server is read-only after boot, so this matrix never
changes. Cache it once. Separately, the server connection sets no read-side PRAGMAs.
Two sub-parts, **one commit**.

### S1A — In-memory normalized embedding cache

**New file:** `packages/server/src/oer_server/embed_cache.py`
- Module-level dict keyed by `id(conn)` **and** schema, e.g.
  `_CACHE: dict[tuple[int, str], tuple[list[str], np.ndarray]]`.
- `get_matrix(conn, schema) -> tuple[list[str], np.ndarray]`: on miss, run
  `SELECT chunk_id, vector FROM {schema}.chunk_embeddings` (note: order is stable
  per load), build `ids` list + a single float32 matrix, **L2-normalize once**, cache,
  return. On hit, return cached. Use `id(conn)` in the key so a new connection (tests)
  doesn't read another conn's cache.
- `clear() -> None`: empties the cache (tests + safety).
- Also expose the chunk-id→row-index map (return it, or build a dict in the caller).

**Edit `queries._semantic_hits`** to use the cache:
- Keep the existing **filter semantics** exactly. Today the function applies the
  `filters`/`params` (source / grade_band / content_type / standard_id EXISTS) inside
  the SQL that pulls vectors. With the cache you must reproduce that filtering as a
  post-mask: run a *vectors-free* `SELECT c.id FROM {schema}.chunk_embeddings e
  JOIN {schema}.chunks c ON c.id=e.chunk_id WHERE c.stale=0 AND {filters}` to get the
  **allowed id set**, then restrict the cached matrix to those rows (boolean mask via
  the id→index map) before the cosine sort. Return the same top-50 id list as before.
- Result ordering and the `1e-9` norm-epsilon must match current behavior so existing
  search tests still pass.

**Hard correctness rule:** the *set and order* of ids returned for a given query+filters
must be identical to the pre-cache implementation. Add a regression test
(`packages/server/tests/test_embed_cache.py`) that:
1. seeds a temp core DB with a handful of chunks + hand-built unit vectors,
2. calls `search_content(...)` (with `embed_query` returning a fixed vector) twice,
3. asserts identical results both times, and
4. asserts the cache is populated after the first call and that a second call does
   **not** re-issue the `SELECT ... vector ...` bulk read (monkeypatch/counter on the
   conn, or assert `embed_cache._CACHE` has the entry and bump a load counter).
5. `clear()` empties it.

### S1B — Read-side PRAGMAs in `db.connect`

**Edit `packages/shared/src/oer_shared/db.py` `connect(...)`:** after the existing
`busy_timeout` line, add performance PRAGMAs that are safe for both build and serve:
```python
conn.execute("PRAGMA temp_store = MEMORY")
conn.execute("PRAGMA mmap_size = 268435456")   # 256 MB memory-map
conn.execute("PRAGMA cache_size = -65536")      # 64 MB page cache (negative = KiB)
```
And **only on the server path** (i.e. `if not create:`) add:
```python
conn.execute("PRAGMA query_only = ON")
```
> Rationale: `query_only=ON` hardens the server against accidental writes and lets
> SQLite skip some bookkeeping; ingestion/tests pass `create=True` and must stay writable.
> Apply mmap/cache/temp_store to BOTH paths.

**Caveat to handle:** `query_only` must be set **after** any ATTACH? No — ATTACH is not
a write to the main schema; set the PRAGMAs where specified (before ATTACH is fine).
But if ATTACH fails under `query_only`, move the `query_only=ON` to the very end of
`connect()` (after ATTACHes) and note that in the commit body. Verify both code paths.

**Acceptance check:**
- `uv run pytest packages/server/tests/test_embed_cache.py -v` → green.
- `uv run pytest -q` → green, total **> 110**.
- `uv run python -c "from oer_shared.db import connect; c=connect('data/oer_core.db'); print(c.execute('PRAGMA query_only').fetchone()[0], c.execute('PRAGMA mmap_size').fetchone()[0])"`
  prints `1 268435456` (query_only on, mmap set) for the server path.
- Sanity timing (optional, paste it): a tiny script that runs `search_content` 20×
  and prints total wall time before/after — should drop noticeably. Don't gate on a
  number; just show it.

**Commit:** `perf: cache normalized embeddings in-memory + add read-side PRAGMAs`

▶ **Paste-to-Sonnet (S1):**
> Implement task S1 from SONNET_TASKS.md (both S1A embedding cache and S1B connection
> PRAGMAs) as ONE commit. Read queries.py `_semantic_hits` and db.py `connect` first.
> The cached path MUST return the identical id set+order as today for any query+filter —
> add the regression test described in S1A. Handle the `query_only`/ATTACH ordering caveat.
> Run the S1 acceptance checks, paste output, commit with the S1 message.

---
---

# THREAD B — Prerequisite-aware learning paths (the differentiator)

This is the feature that makes "StandardGraph + OER" worth more than either alone, and
the most plausible fix for the benchmark's `target_met: false`: it surfaces content for a
standard **and its prerequisites**, which a definition-only baseline can't reproduce.

## S2 — `get_learning_path` query function + prereq walk

**Why:** No tool today bridges OER content to StandardGraph's prerequisite graph.
`fetch_for_standard` answers "what teaches X"; this answers "what's the *grounded path*
to mastering X", bottom-up through prerequisites.

**Edit `packages/server/src/oer_server/queries.py`** — add a pure function:
```python
def get_learning_path(
    conn, standard_id, *, sg_db_path=None, depth=1,
    content_per_standard=2, include_content=False,
) -> dict:
```
Behavior:
1. **Resolve prerequisites from StandardGraph** (read-only, same `file:...?mode=ro`
   pattern as `check_coverage`). BFS from `standard_id` over
   `WHERE source_id=? AND relationship='prerequisite' AND system='ccss'` → `target_id`,
   up to `depth` levels (depth=1 → direct prereqs only). Track a `visited` set to kill
   cycles. Record each standard's BFS distance from the target (target = depth 0).
2. **Order the path bottom-up:** deepest prerequisites first, the requested standard
   last (teach foundations → target). Stable tie-break by standard id.
3. **Pull standard_text** for every standard in the path from SG `standards`.
4. **Attach OER content** per standard: reuse the existing ranking. Cleanest is to call
   the internal `_best_alignment` + a small content fetch, or factor the core of
   `fetch_for_standard` so both share it — but **do not change `fetch_for_standard`'s
   public behavior**. Return up to `content_per_standard` chunks per standard, ranked by
   the confidence hierarchy (`_SOURCE_RANK`) then score; honor `include_content`.
5. **Degraded modes:** if `sg_db_path` missing/not present → return just the target
   standard's content with `"sg_available": false` and `"path"` containing only the
   target (don't crash). If the standard is unknown to SG → `{"standard_id", "result":
   "unknown_standard"}` (match `check_coverage`'s convention). If a prereq has no OER
   content, include it with an empty `content: []` (it's a real gap worth surfacing).

**Return shape (keep it stable + documented):**
```python
{
  "standard_id": "...",
  "sg_available": True,
  "depth": 1,
  "path": [
    {"standard_id": "...", "text": "...", "distance": 1, "is_target": False,
     "content": [ <ChunkResult dicts> ], "coverage": "strong|moderate|light|none"},
    ...
    {"standard_id": "<target>", ..., "is_target": True, ...},
  ],
  "prerequisite_gaps": ["<ids in path with coverage == 'none'>"],
}
```
Use `oer_shared.coverage.coverage_band` (as `check_coverage` does) to set each rung's
`coverage`. `prerequisite_gaps` is the high-value signal: "you can't ground these
prereqs from the corpus yet."

**Tests:** `packages/server/tests/test_learning_path.py`. Build a **seeded temp SG DB**
(in-memory or tmp file) with a tiny `standards` table and `standard_relationships` table
mirroring the real schema (columns above), plus a temp core DB with chunks/alignments
(reuse the `_source/_book/_chunk/_align` helpers from
`test_get_chunk_and_assessments.py`). Cover:
- direct prereqs returned bottom-up, target last;
- `depth=2` walks two levels and dedupes via `visited`;
- a cycle in the seed (A→B→A) terminates;
- `sg_available: false` when sg path absent;
- `unknown_standard` for an id not in SG;
- a prereq with no content shows `content: []` and appears in `prerequisite_gaps`;
- `include_content` toggles full text on/off.

**Acceptance check:**
- `uv run pytest packages/server/tests/test_learning_path.py -v` → green.
- `uv run pytest -q` → green, total **> S1's total**.

**Commit:** `feat: get_learning_path — prerequisite-aware content path via StandardGraph`

▶ **Paste-to-Sonnet (S2):**
> Implement task S2 from SONNET_TASKS.md: add `get_learning_path` to queries.py per the
> spec (BFS over StandardGraph `standard_relationships` with the verified edge semantics —
> prereqs of X are `target_id WHERE source_id=X AND relationship='prerequisite'`). Read
> `check_coverage` and `fetch_for_standard` first to reuse their SG-read and ranking patterns;
> do NOT change their public behavior. Write `test_learning_path.py` with a seeded temp SG DB
> covering all listed cases. Run the S2 acceptance checks, paste output, commit with the S2 message.

## S3 — Expose `get_learning_path` as an MCP tool + docs

**Why:** S2 added the query; this surfaces it as the 7th MCP tool with a strong
description, the structured-error path, and user/agent-facing docs.

**Edit `packages/server/src/oer_server/server.py`:** add a `@mcp.tool()` wrapper
`get_learning_path(standard_id, depth=1, content_per_standard=2, include_content=False)`
following the EXACT pattern of the other six wrappers (delegate to
`queries.get_learning_path(get_conn(), ..., sg_db_path=config.STANDARDGRAPH_DB_PATH)`,
same `except Exception → {"error", "detail"}`). Write a tool docstring in the same voice
as the others: explain it returns the prerequisite chain bottom-up with grounded OER
content per rung and surfaces `prerequisite_gaps`; give a usage example ("what should a
student master before CCSS.MATH.7.RP.1, and what content teaches each step?").

**Docs:**
- Add a row to the MCP tools table in **`CLAUDE.md`** and in **`README.md`** (both have a
  tool catalog — keep them in sync).
- Update `docs/DOCUMENTATION_INDEX.md` if it enumerates tools.

**Tests:** extend `packages/server/tests/test_server_tools.py` (the wrapper-layer suite):
add a success-delegation case (monkeypatch `get_conn` + point `config.STANDARDGRAPH_DB_PATH`
at a seeded temp SG, or monkeypatch `queries.get_learning_path`) and a structured-error
case (broken `get_conn` → `{"error": "RuntimeError", "detail": "boom"}`). Keep the autouse
`server._conn = None` reset.

**Acceptance check:**
- `uv run pytest packages/server/tests/test_server_tools.py -v` → green incl. the 2 new cases.
- `uv run pytest -q` → green, total **> S2's total**.
- `grep -c "get_learning_path" CLAUDE.md README.md` → ≥ 1 in each.

**Commit:** `feat: expose get_learning_path MCP tool + document it (7th tool)`

▶ **Paste-to-Sonnet (S3):**
> Implement task S3 from SONNET_TASKS.md: add the `get_learning_path` `@mcp.tool()` wrapper to
> server.py (same delegation + structured-error pattern as the other six), document the new tool
> in CLAUDE.md and README.md tool tables, and add success + error cases to test_server_tools.py.
> Run the S3 acceptance checks, paste output, commit with the S3 message. Depends on S2.

---
---

# THREAD C — Machine-friendly API contract

## S4 — Stable error codes + consistent `fetch_for_standard` envelope

**Why:** Two rough edges for typed/automated clients. (1) Errors leak the Python
exception class name (`{"error": "RuntimeError", ...}`) — not a stable contract.
(2) `fetch_for_standard` returns a **list** on success but a **dict** on no-content —
clients must type-switch. Fix both with a small, documented contract. **This task is
allowed to change source** (it's an intentional contract change) and MUST update the
affected tests.

**4a — Stable error codes.** In `server.py`, replace the six identical handlers'
payload with a stable shape. Add a tiny mapper (module-level in server.py):
```python
_ERROR_CODES = {
    "FileNotFoundError": "database_unavailable",
    "OperationalError": "database_error",
}
def _error(exc):
    code = _ERROR_CODES.get(type(exc).__name__, "internal_error")
    return {"error": {"code": code, "type": type(exc).__name__, "message": str(exc)}}
```
Each wrapper's `except` becomes `return _error(exc)`. Keep `type` so debugging info
isn't lost; `code` is the stable enum clients branch on.
> Update `packages/server/tests/test_server_tools.py`: the error-path assertions change
> from `result["error"] == "RuntimeError"` to `result["error"]["code"] == "internal_error"`
> and `result["error"]["type"] == "RuntimeError"`. Update every error-path test (there are 6).

**4b — Consistent fetch_for_standard envelope.** Change `queries.fetch_for_standard` to
ALWAYS return a dict:
```python
{"standard_id": ..., "count": N, "results": [ <chunks> ]}     # success (N may be 0)
```
The no-content case keeps its helpful fields nested under the same envelope:
`{"standard_id", "count": 0, "results": [], "reason": "...", "available_sources": [...]}`.
> Update ALL callers and tests that assume a bare list: search the repo
> (`grep -rn "fetch_for_standard" packages`) — at minimum `test_fetch_for_standard.py`
> and the S-thread server tests. The MCP tool's return annotation in server.py changes
> from `list[dict] | dict` to `dict`; update the docstring to describe `results`.

**Hard rule:** make the contract change cleanly and fix every caller/test in the SAME
commit so the suite is green. Do not leave a half-migrated shape.

**Acceptance check:**
- `uv run pytest -q` → green, total unchanged-or-higher (no tests deleted, only updated).
- `grep -rn "result\[.error.\] == " packages/server/tests` returns nothing (old shape gone).
- `uv run python -c "from oer_server import queries; import inspect; print('results envelope OK')"`
  plus a seeded smoke check that `fetch_for_standard` returns a dict with `results` in both
  the hit and no-content cases.

**Commit:** `api: stable error codes + consistent fetch_for_standard envelope`

▶ **Paste-to-Sonnet (S4):**
> Implement task S4 from SONNET_TASKS.md: (a) replace the six wrappers' error payload with the
> stable `{"error":{"code","type","message"}}` shape via an `_error()` mapper, and (b) make
> `queries.fetch_for_standard` always return a `{"standard_id","count","results"}` dict. This task
> CHANGES SOURCE and MUST update every affected test (grep for callers first) in the same commit.
> Run the S4 acceptance checks, paste output, commit with the S4 message.

## S5 — `get_capabilities` discovery tool

**Why:** A machine client can't currently enumerate what this server *contains* without
trial-and-error — which sources, standard systems, exam series, grade bands, content
types, and which DBs are attached. One discovery tool makes the server self-describing.

**Edit `queries.py`** — add `get_capabilities(conn) -> dict` returning live counts/enums
read from the DB across attached schemas:
```python
{
  "databases_attached": ["core","ncsa",...],     # from attached_schemas + _SCHEMA_LABELS
  "sources": [ <list_sources summary: id, full_name, chunks, grade_bands, license> ],
  "standard_systems": ["ccss", ...],              # DISTINCT standard_system from alignments
  "content_types": ["exposition","worked_example","exercise_set","summary","assessment"],
  "exam_series": [ DISTINCT exam_series WHERE NOT NULL ],
  "grade_bands": [ DISTINCT grade_band across books ],
  "alignment_sources": ["human","publisher_guide","llm_verified","embedding"],
  "alignment_confidence_bands": { ...from oer_shared.coverage thresholds... },
  "tools": [ "fetch_for_standard","search_content","get_chunk","check_coverage",
             "list_sources","map_to_assessments","get_learning_path" ],
  "total_chunks": N, "total_alignments": M,
}
```
Pull enums from the DB where they're data (sources, exam_series, standard_systems,
grade_bands) and hard-list where they're code contracts (content_types, alignment_sources,
tools). Reuse `list_sources` for the sources block.

**Edit `server.py`** — add the `@mcp.tool() get_capabilities()` wrapper (same delegation +
`_error` path from S4). Docstring: "Self-describe: what content, standards systems, exams,
and tools this server exposes — call this first to discover the corpus before querying."

**Docs:** add the 8th tool to the CLAUDE.md + README.md tool tables.

**Tests:** `packages/server/tests/test_capabilities.py` — seed a temp core DB with two
sources, an assessment chunk with an `exam_series`, and alignments in two systems; assert
the capabilities dict has the right keys, lists both sources, surfaces the exam_series, and
lists all 8 tools. Add a wrapper success+error case to `test_server_tools.py`.

**Acceptance check:**
- `uv run pytest packages/server/tests/test_capabilities.py -v` → green.
- `uv run pytest -q` → green, total **> S4's total**.
- `grep -c "get_capabilities" CLAUDE.md README.md` → ≥ 1 in each.

**Commit:** `feat: get_capabilities discovery tool for machine self-configuration`

▶ **Paste-to-Sonnet (S5):**
> Implement task S5 from SONNET_TASKS.md: add `queries.get_capabilities(conn)` returning the
> live corpus manifest described, expose it as the 8th `@mcp.tool()` (reuse S4's `_error` path),
> document it in CLAUDE.md + README.md, and add `test_capabilities.py` plus wrapper cases. Run the
> S5 acceptance checks, paste output, commit with the S5 message. Depends on S4 (uses `_error`).

---
---

## Order & dependencies

| # | Task | Thread | Depends on | Risk | Notes |
|---|------|--------|-----------|------|-------|
| S1 | Embedding cache + PRAGMAs | A (speed) | — | low | pure perf; behavior-preserving |
| S2 | get_learning_path query | B (feature) | — | med | new SG read; seeded-SG tests |
| S3 | get_learning_path MCP tool | B (feature) | S2 | low | wrapper + docs |
| S4 | Error codes + fetch envelope | C (contract) | — | **med** | **changes contract**; updates tests |
| S5 | get_capabilities tool | C (contract) | S4 | low | reuses S4 `_error` |

**Recommended order:** S1 → S2 → S3 → S4 → S5. S1 and S2 are independent and could be
parallelized on separate branches, but S4 touches `test_server_tools.py` which S3 and S5
also extend — do S4 *after* S3 and *before* S5 to avoid three-way churn on that file, OR
do S4 first and have S3/S5 write the new error shape from the start. Either is fine; the
table's order (S4 after S3) minimizes rework if done sequentially.

## Out of scope (do NOT let Sonnet do these)
- Running `claude_*` scripts, the e2e benchmark, or any Ollama/gemma pipeline (no API/Ollama).
- Re-embedding content, writing to the StandardGraph DB, or any HuggingFace upload.
- `DELETE`/`DROP`, force-push, branch deletion.
- Swapping in a native vector index (sqlite-vec / faiss) — that's a separate, larger ADR;
  S1's in-memory cache is the right-sized win for a 1k-vector corpus. Revisit if the
  embedded-chunk count grows past ~100k.

## After all five
`git log --oneline -8` should show S1–S5 on top of the Haiku rounds; `uv run pytest -q`
green with a materially higher test count; the server exposes **8 tools** (was 6), semantic
search is cached, the API contract is machine-stable, and the headline feature —
prerequisite-aware learning paths grounded in real OER content — is live. That's the
package that makes this the best curriculum MCP available.
