# Haiku Task Backlog — planned by Opus, 2026-06-30

**How to use this file:** Each task below is self-contained. Hand Haiku ONE task at a
time by pasting the **▶ Paste-to-Haiku** block. Do them in order — later tasks assume
earlier ones are committed. Every task ends with an **Acceptance check** Haiku must run
and report before it claims done. No Anthropic API calls and no Ollama are needed for
any task here; everything runs locally against `data/oer_core.db` and the test suite.

**Baseline at planning time:** `uv run pytest` → **77 passed**. DB present at
`data/oer_core.db` (73 MB). Branch `main`. Untracked: 3 new (green) test files, 6
investigation docs, several `scripts/*.py`, and modified `benchmark.py`.

**Global rules for Haiku**
- Run `uv run pytest -q` before AND after every code change; both must be green.
- Never run `DELETE`/`DROP` or HuggingFace uploads — none of these tasks need them.
- Make the exact edits specified. If a string to replace isn't found verbatim, STOP and
  report rather than guessing.
- One task = one commit (message given per task). End every commit message with the
  Co-Authored-By trailer already used in this repo.

---

## T1 — Fix the benchmark judge-prompt leak (correctness blocker)

**Why:** `run_benchmark()` already randomizes which condition lands in slot A vs B
(`benchmark.py` ~line 224), but `JUDGE_PROMPT` still hard-labels the slots as "A =
definition only" and "B = definition + materials," and tells the judge "Segment B should
align with these." That leaks the answer and contradicts the randomization, so the judge
is biased toward B regardless of content. Neutralize the labels; keep the reference
materials visible so grounding is still rewarded.

**File:** `packages/ingestion/src/oer_ingestion/benchmark.py`

**Edit — replace the entire `JUDGE_PROMPT` (currently lines ~73–93) with:**
```python
JUDGE_PROMPT = """Two teaching segments (A and B) cover the same math topic.

Evaluate which segment is more grounded in actual curriculum practice — concrete and
correct worked examples, standard teaching methods and notation, grade-appropriate —
and, where reference materials are provided below, which segment better reflects the
specific methods, notation, and examples in those materials.

Topic: {topic}
Standard {standard_id}: {standard_text}

--- Reference materials (real curriculum excerpts for this standard) ---
{reference_materials}

--- Segment A ---
{a}

--- Segment B ---
{b}

Reply with exactly one token: A, B, or TIE."""
```

**Do NOT touch** `GEN_PROMPT`, `run_benchmark()`, the randomization logic, or the
`.format(...)` call — the keyword args (`reference_materials`, `a`, `b`, `topic`,
`standard_id`, `standard_text`) are unchanged, so the format call still works.

**Acceptance check:**
- `grep -n "definition only\|should align with these\|definition + reference" packages/ingestion/src/oer_ingestion/benchmark.py` returns **nothing**.
- `uv run python -c "from oer_ingestion.benchmark import JUDGE_PROMPT; print(JUDGE_PROMPT.format(topic='t', standard_id='s', standard_text='x', reference_materials='r', a='aa', b='bb'))"` runs with no KeyError.
- `uv run pytest -q` → all green.

**Commit:** `benchmark: de-bias judge prompt — drop slot labels that leaked the condition`

▶ **Paste-to-Haiku (T1):**
> In `packages/ingestion/src/oer_ingestion/benchmark.py`, replace the entire `JUDGE_PROMPT`
> string with the version specified in HAIKU_TASKS.md task T1. Change nothing else. Then run
> the three acceptance checks listed under T1 and paste their output. If all pass, commit with
> the T1 commit message. If the old `JUDGE_PROMPT` text doesn't match verbatim, stop and show me
> what's there.

---

## T2 — Add the three stale/perf indexes + apply to the live DB

**Why:** `SCHEMA_OPTIMIZATION_AUDIT.md` identifies missing composite indexes that force
table scans on source/grade-filtered queries. Pure mechanical win, ~2 MB disk.

**File 1 — `packages/shared/src/oer_shared/schema.sql`.** After the existing
`idx_chunks_type` line (currently line 72), add:
```sql
CREATE INDEX IF NOT EXISTS idx_chunks_source_stale ON chunks(source_id, stale);
CREATE INDEX IF NOT EXISTS idx_chunks_grade_stale  ON chunks(grade_band, stale);
```
And after the `pipeline_runs` table definition (it ends before line ~172), add:
```sql
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_date ON pipeline_runs(run_date DESC);
```
> Note: if `pipeline_runs` has no `run_date` column, check its actual columns with
> `sqlite3 data/oer_core.db ".schema pipeline_runs"` and use the real timestamp column
> name; if there is none, SKIP only the pipeline_runs index and report that.

**Apply to the live DB** (idempotent, safe — `CREATE INDEX IF NOT EXISTS` only):
```bash
sqlite3 data/oer_core.db < packages/shared/src/oer_shared/schema.sql
```

**Acceptance check:**
- `sqlite3 data/oer_core.db ".indices chunks"` lists `idx_chunks_source_stale` and `idx_chunks_grade_stale`.
- `sqlite3 data/oer_core.db "EXPLAIN QUERY PLAN SELECT * FROM chunks WHERE source_id='openstax' AND stale=0;"` shows `USING INDEX idx_chunks_source_stale` (or `idx_chunks_source`-prefixed).
- `uv run pytest -q` → all green.

**Commit:** `schema: add stale/grade/source composite indexes for filtered queries`

▶ **Paste-to-Haiku (T2):**
> Implement task T2 from HAIKU_TASKS.md: add the three indexes to
> `packages/shared/src/oer_shared/schema.sql` at the specified locations, then apply the schema
> to `data/oer_core.db` with the given sqlite3 command. Run the T2 acceptance checks and paste
> output. Handle the pipeline_runs column-name caveat as written. Commit with the T2 message.

---

## T3 — Close the two genuinely-missing test gaps

**Why:** Haiku's earlier sprint already covered 8 of the 10 `TEST_COVERAGE_AUDIT.md` gaps
(those tests now pass). Two remain genuinely untested:
1. **Grade penalty (D18):** `align.py` defines `GRADE_PENALTY = 0.02` and uses
   `grade_distance(...)`, but no test exercises it.
2. **`get_chunk` adjacency + `map_to_assessments`** MCP tools have no direct test.

**Task 3a — grade penalty test.** Add `packages/ingestion/tests/test_grade_penalty.py`.
First read `packages/ingestion/src/oer_ingestion/align.py` (the scoring section around
`GRADE_PENALTY` and `grade_distance`) and `packages/ingestion/src/oer_ingestion/grades.py`
to see the real function signatures. Then write tests that assert:
- a 0-grade-distance match has **no** penalty applied,
- an N-grade-distance match is reduced by exactly `N * GRADE_PENALTY`,
- penalty boundary: 1 grade-year and 5+ grade-years behave monotonically (more distance →
  lower score).
Use the existing tests in `test_align_helpers.py` as the fixture/style template. Do not
invent function names — call the ones that actually exist in `align.py`/`grades.py`.

**Task 3b — server tool test.** Add `packages/server/tests/test_get_chunk_and_assessments.py`
covering the two untested `@mcp.tool()` wrappers in
`packages/server/src/oer_server/server.py`. Read `server.py` and the existing
`packages/server/tests/test_fetch_for_standard.py` to copy its in-memory DB fixture
pattern. Assert:
- `get_chunk(chunk_id, include_adjacent=True)` returns the chunk plus prev/next, and
  handles first/last-chunk boundaries (no crash, neighbours may be null),
- `get_chunk` on an unknown id returns a structured "not found" result (match whatever the
  code actually returns — read it first),
- `map_to_assessments(standard_id=...)` returns the crosswalk/items shape for a standard
  that has a crosswalk row, and a graceful empty/gap shape for one that doesn't.

**Hard rule:** tests must pass against the REAL current behavior. If behavior looks buggy,
do NOT change source code — write the test to capture actual behavior and add a `# NOTE:`
comment flagging the suspected bug for me to review. This task only adds tests.

**Acceptance check:**
- `uv run pytest -q` → green, and total count is **higher than 77** (new tests ran).
- `uv run pytest packages/ingestion/tests/test_grade_penalty.py packages/server/tests/test_get_chunk_and_assessments.py -v` shows the new tests passing.

**Commit:** `tests: cover grade-penalty scoring (D18) and get_chunk/map_to_assessments tools`

▶ **Paste-to-Haiku (T3):**
> Implement task T3 from HAIKU_TASKS.md (two new test files: grade penalty, and
> get_chunk/map_to_assessments). Read the source files named in the task FIRST to get real
> signatures and behavior — do not invent names. Tests must pass against current behavior; flag
> suspected bugs with `# NOTE:` comments instead of editing source. Run the acceptance checks,
> paste output, commit with the T3 message.

---

## T4 — Repo hygiene: file the loose docs/scripts/tests, then commit

**Why:** Ten markdown reports and several scripts/tests are untracked and cluttering the
repo root. Organize and commit so the tree is clean.

**Steps:**
1. Create `docs/` if absent. Move these investigation reports into `docs/` (use
   `git mv` after `git add` if needed, or plain `mv` then `git add`):
   `BENCHMARK_ANALYSIS.md`, `COMPREHENSIVE_SPRINT_SUMMARY.md`, `DOCUMENTATION_INDEX.md`,
   `LOCAL_EXECUTION_SUMMARY.md`, `OPERATIONAL_RUNBOOK.md`, `SCHEMA_OPTIMIZATION_AUDIT.md`,
   `TEST_COVERAGE_AUDIT.md`, `WORK_SUMMARY.md`.
   **Leave at root:** `README.md`, `CLAUDE.md`, and `HAIKU_TASKS.md` (this file).
2. If any moved doc is referenced by a relative path in `README.md` or `CLAUDE.md`, update
   the link (`grep -rn "WORK_SUMMARY\|BENCHMARK_ANALYSIS\|OPERATIONAL_RUNBOOK" README.md CLAUDE.md`).
3. The three CSVs (`coverage_by_grade.csv`, `source_quality.csv`, `standards_gaps.csv`) are
   generated analysis outputs — move them to `docs/analysis/` and add a one-line note at
   the top of `DOCUMENTATION_INDEX.md` saying they're generated by
   `scripts/generate_coverage_analysis.py`.
4. Stage the new scripts (`scripts/audit_alignment_quality.py`,
   `scripts/benchmark_performance.py`, `scripts/generate_coverage_analysis.py`,
   `scripts/local_verify_alignments.py`, `scripts/local_annotate_alignments.py`,
   `scripts/claude_verify_alignments.py`, `scripts/claude_annotate_alignments.py`) and the
   3 already-green test files.
5. Sanity: `uv run pytest -q` still green; `git status` shows nothing untracked except
   intended files.

**Note:** Do this as **two commits** for a clean history —
(a) `docs: organize investigation reports and analysis CSVs under docs/`
(b) `scripts+tests: add analysis/verify/annotate scripts and edge-case test suites`

**Acceptance check:**
- `git status --porcelain` is empty (clean tree) after both commits.
- `ls docs/` shows the 8 moved reports; `ls docs/analysis/` shows the 3 CSVs.
- `uv run pytest -q` → green.

▶ **Paste-to-Haiku (T4):**
> Implement task T4 from HAIKU_TASKS.md: move the 8 listed reports into `docs/`, the 3 CSVs into
> `docs/analysis/`, leave README/CLAUDE/HAIKU_TASKS at root, fix any broken relative links, then
> stage the new scripts and the 3 test files. Make the TWO commits specified. Run the acceptance
> checks and paste `git status --porcelain` (should be empty) plus the pytest summary.

---

## Suggested order & dependencies

| # | Task | Depends on | Risk | Local-only |
|---|------|-----------|------|-----------|
| T1 | Benchmark judge de-bias | — | low | yes |
| T2 | Schema indexes | — | low | yes |
| T3 | Test gaps (penalty + tools) | — | low | yes |
| T4 | Repo hygiene + commits | T1–T3 done | low | yes |

T1/T2/T3 are independent and can be done in any order; **T4 last** because it commits the
work the others produce. After T4, `git log --oneline -6` should show ~5 clean commits and
`git status` should be empty.

## Explicitly OUT of scope (do NOT let Haiku do these)
- Running `claude_verify_alignments.py` / `claude_annotate_alignments.py` (Anthropic API spend).
- Running the e2e benchmark or any Ollama/gemma pipeline.
- HuggingFace upload, force-push, any `DELETE`/`DROP`.
- Editing source behavior to make a test pass (T3 is tests-only).
