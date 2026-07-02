# OER MCP — Claude Code context

## What this is

FastMCP server exposing open-licensed K–12 math content (OpenStax textbooks + Khan Academy transcripts + Illustrative Mathematics) as five MCP tools for Claude Desktop. Content is chunked by concept, embedded, and aligned to CCSS standards at build time. Companion to StandardGraph: StandardGraph knows *what students must learn*; OER MCP knows *what content teaches it*.

## Architecture

```
packages/
  shared/           → oer-shared: config, DB helpers, Pydantic models, schema.sql
  ingestion/        → oer-ingestion: adapters + 7-stage pipeline
  server/           → oer-server: FastMCP stdio server (6 tools)

Three-database layout:
  oer_core.db   CC BY content (OpenStax 1e, Illustrative Mathematics, Smarter Balanced, NAEP, PARCC)
  oer_ncsa.db   CC BY-NC-SA content (Khan transcripts, OpenStax 2e, OpenMiddle)
  oer_ap.db     AP free-response items (College Board copyright, educational use — partitioned separately)

data/oer_core.db          → dev/pipeline DB
data/oer_ncsa.db          → dev/pipeline DB
data/oer_ap.db            → dev/pipeline DB
~/.oer-mcp/oer_core.db   → installed user DB (default)
~/.oer-mcp/oer_ncsa.db   → installed user DB (optional add-on, --with-khan)
~/.oer-mcp/oer_ap.db     → installed user DB (optional add-on, --with-ap)

Server attaches ncsa and ap at runtime if present; all queries transparently
span whichever databases are attached via attached_schemas().

scripts/
  overnight_run.sh            → full ingestion pipeline
  verify_loop.sh / annotate_loop.sh → sharded gemma pipelines (both DBs)
  mini_supervisor.sh          → cascade verify→annotate on Mac Minis
  eval/e2e_benchmark.py       → LLM-judge benchmark (bench.json)
```

## Key facts

- **Core DB (CC BY):** OpenStax statistics (1e) + Illustrative Mathematics 6–8 + any CC BY expansions
- **NC-SA DB (CC BY-NC-SA):** OpenStax 2e math books + Khan Academy transcripts
- **Chunks:** ~12,000 total (8,761 OpenStax + ~3,322 Khan) — IM being added
- **CCSS coverage:** 327/343 standards (95%) K–12
- **Alignments:** 20,250 across 262 distinct CCSS standards (OpenStax alone); confidence hierarchy: `human` > `publisher_guide` > `llm_verified` > `embedding`
- **IM adapter:** First source with real `publisher_guide` alignments (CCSS "Addressing" tags per lesson); no LLM verify needed for those
- **HuggingFace dataset:** `swoopeagle/oer-mcp` (files: `oer_core.db`, `oer_ncsa.db`)

## Tailscale devices

Same fleet as StandardGraph:

| Device | Chip | RAM | IP | SSH user | Role |
|---|---|---|---|---|---|
| MacBook Pro | — | — | 100.118.151.10 | `ianwang` | dev machine |
| Mac Studio | M1 Max | 64 GB | 100.77.63.73 | `ianwangm1max` | Ollama host (gemma4:31b) |
| Mac mini 2 | M4 Pro | 24 GB | 100.101.100.96 | `devos` | pipeline runner (verify/annotate) |
| Mac mini 3 | M4 | 16 GB | 100.123.114.101 | `devos` | pipeline runner (verify/annotate) |

Model roster:
- **Mac Studio (64 GB):** `gemma4:31b-it-q8_0`, `nomic-embed-text` — annotate/verify heavy lifter
- **Mac mini 2 (24 GB):** `gemma4:26b` or `qwen2.5:14b`, `nomic-embed-text` — sharded verify/annotate
- **Mac mini 3 (16 GB):** `qwen2.5:14b`, `nomic-embed-text` — lighter shard only

## DB paths (build vs runtime)

```bash
# Build-time (ingestion, verify, annotate):
data/oer_core.db          # CC BY content
data/oer_ncsa.db          # CC BY-NC-SA content

# Runtime (MCP server / end-user):
~/.oer-mcp/oer_core.db
~/.oer-mcp/oer_ncsa.db
```

## Ingestion pipeline (7 stages)

```bash
# Stage 1–3: fetch → snapshot → chunk → load (no Ollama needed)
uv run python -m oer_ingestion.pipeline openstax --book all --db data/oer_core.db
uv run python -m oer_ingestion.pipeline im --db data/oer_core.db
uv run python -m oer_ingestion.pipeline khan --db data/oer_ncsa.db --channel-db <kolibri.sqlite3>

# Stage 4–5: embed + align (needs Ollama + SG DB)
uv run python -m oer_ingestion.pipeline embed-align \
    --db data/oer_core.db --sg-db ~/.standardgraph/common_core.db

# Stage 6b: gemma-verify moderate→light embedding alignments (needs Ollama + SG DB)
uv run python -m oer_ingestion.pipeline verify \
    --db data/oer_core.db --sg-db ~/.standardgraph/common_core.db

# Stage 6: gemma coverage-note annotation for verified rows
uv run python -m oer_ingestion.pipeline annotate \
    --db data/oer_core.db --sg-db ~/.standardgraph/common_core.db

# Stage 7: acceptance validation (no Ollama)
uv run python -m oer_ingestion.pipeline validate --db data/oer_core.db
```

## Run server locally

```bash
OER_CORE_DB_PATH=data/oer_core.db uv run oer-mcp
# With NC-SA add-on:
OER_CORE_DB_PATH=data/oer_core.db OER_ADDON_DB_PATH=data/oer_ncsa.db uv run oer-mcp
```

## Tests

```bash
uv run pytest          # ~50 tests across all packages
uv run pytest packages/ingestion/tests/test_align_helpers.py  # alignment calibration
uv run pytest packages/server/tests/                           # server tool tests
```

## Check DB stats

```bash
sqlite3 data/oer_core.db "SELECT COUNT(*) FROM chunks;"
sqlite3 data/oer_core.db "SELECT source_id, COUNT(*) FROM chunks GROUP BY source_id;"
sqlite3 data/oer_core.db "SELECT alignment_source, COUNT(*) FROM standard_alignments GROUP BY alignment_source;"
sqlite3 data/oer_core.db "SELECT COUNT(DISTINCT standard_id) FROM standard_alignments;"
```

## MCP tools

| Tool | What it does |
|---|---|
| `fetch_for_standard` | OER content for a standard ID, ranked by alignment confidence; returns `{standard_id, count, results}` envelope |
| `search_content` | Hybrid semantic + FTS5 keyword search; degrades gracefully without Ollama |
| `get_chunk` | Retrieve a specific chunk by ID, with neighbours and alignments |
| `check_coverage` | Coverage bands (strong/moderate/light/none) and gaps for a standard/cluster |
| `list_sources` | Live inventory of sources, books, chunks, and attached databases |
| `map_to_assessments` | Map a standard to high-stakes exams (SAT/ACT/AP/state/NAEP) — crosswalk domains + available items per exam; surfaces gaps. Returns `items_status`: `ready` (item store queryable) or `no_item_store` (legacy DB without assessment columns) |
| `get_learning_path` | **Prerequisite-aware path**: BFS over StandardGraph prereqs → OER content per rung, bottom-up; surfaces `prerequisite_gaps` |
| `get_capabilities` | Self-describing manifest: sources, standard systems, exam series, grade bands, and available tools |

## Alignment confidence bands (source-aware, D18)

```
embedding:      strong ≥ 0.78 | moderate 0.70–0.78 | light 0.65–0.70
publisher_guide / llm_verified / human: always "strong" (score not compared to thresholds)
```

`check_coverage` uses these bands per `oer_shared.coverage`. Annotate stage targets `score ≥ 0.78` embedding rows (the "strong" embedding band, D20).

## Assessment content types and databases

> **Status (2026-07):** the assessment *plumbing* is complete — schema columns,
> `exam_crosswalks` table, adapters (`naep`, `smarter_balanced`, `ap_frq`), and the
> `map_to_assessments` tool are all in place.
> - **Crosswalk: LOADED.** `data/oer_core.db` carries 70 crosswalk rows across 15
>   exam series (SAT/ACT/AP/NAEP/Smarter Balanced) from the seed file. Load/refresh
>   with `uv run python -m oer_ingestion.crosswalk --db data/oer_core.db` (idempotent
>   upsert). `map_to_assessments` matches a leaf standard against its own id **and
>   every ancestor prefix**, so `8.EE.1` picks up the `8.EE` cluster rows and the
>   grade-8 row.
> - **Items: NOT loaded yet.** 0 assessment chunks — the item adapters fetch from
>   live external sites (NAEP NQT, SBAC sample-item API, College Board PDFs) and
>   have unverified endpoints (`# TODO: confirm params`), so they're fleet work, not
>   dev-machine work. Every exam in the crosswalk therefore shows up in `gaps`.
> - DBs built before the assessment columns landed are healed automatically by
>   `migrate_schema` on the next `connect(create=True)`; `map_to_assessments` reports
>   `items_status="no_item_store"` on any DB still missing them rather than erroring.

**content_type = 'assessment'** — new fifth value alongside exposition/worked_example/exercise_set/summary. Assessment-only columns (all NULL for other types):
- `item_type`: "multiple_choice" | "constructed_response" | "performance_task"
- `dok_level`: Webb's DOK 1–4
- `answer_key`: correct answer / scoring guidance. Style-generated items always carry one (gemma-authored); released items carry one when source provides it.
- `exam_series`: "AP Calculus BC" | "SAT" | "NAEP Grade 8" | "Smarter Balanced Gr 6" etc.
- `exam_year`: year of release; NULL for style-generated
- `difficulty`: 0–1 normalized (NAEP % correct nationally; SAT difficulty band)
- `item_generation`: "released" | "style_generated"

**Item source tiers:**
| Tier | Sources | DB | Rationale |
|---|---|---|---|
| Open (ingest verbatim) | Smarter Balanced (CC BY), NAEP (public domain), PARCC (public domain), IM assessments (CC BY), OpenMiddle (CC BY-NC-SA) | core or ncsa | Clean license; standard adapter pattern |
| Gray zone (verbatim) | AP free-response questions | **ap** | College Board copyright; educational use argument strong; partitioned so deployments can exclude |
| Style-generated | SAT-style, ACT-style | core | Not CB's items; gemma-generated from style reference; `item_generation='style_generated'`; always carries answer key |

**exam_crosswalks table** — standard → exam skill domain mapping, populated from College Board / ACT alignment documents. Lives in core DB. Powers the `map_to_assessments` tool's crosswalk response independent of whether items exist.

## Key design decisions

- **Two-DB layout (D11):** license split at ingestion time. CC BY → `oer_core.db`; CC BY-NC-SA → `oer_ncsa.db`. Server ATTACHes the add-on at runtime; queries span both via `attached_schemas()`.
- **Grade penalty (D18):** 0.02/grade-year penalty at align time; eliminates K/1st-grade matches in 6–8 content.
- **Generic exercise exclusion (D18):** `align._is_generic_exercise` skips "Writing Exercises" / "Self-Check" chunks that over-match broadly.
- **FTS5 fallback (D13):** `search_content` returns `search_mode="keyword_fallback"` if Ollama query-embed times out (3s default). Works in the wild.
- **CCSS ID format:** StandardGraph omits cluster letters inconsistently — `CCSS.MATH.6.RP.3` not `CCSS.MATH.6.RP.A.3`, but `CCSS.MATH.1.OA.B.3` keeps the letter. Alignment IDs come straight from SG. `check_coverage` tolerates both via exact-then-prefix match.
- **IM publisher alignments:** Illustrative Mathematics lessons ship "Addressing" CCSS tags → loaded as `publisher_guide` rows directly (first real publisher-seed data in corpus; no LLM verify needed).

## Benchmark

Combined-MCP benchmark: 20 math topics K–12, each generated three ways
(`none` / `standardgraph` / `both`) with the generator held constant, then judged
**pairwise** (`oer_ingestion.benchmark`). Headline: how often `both` is preferred
over `standardgraph`; target ≥60% of decisive comparisons.

The design was rebuilt from an absolute 1–5 rubric (which saturated at 5.0 — a weak
local judge scored ~everything 5/5, so no lift was measurable) to pairwise
preference on a grounding-stressing task. The judge scores both segments against one
**fixed ground-truth reference** (the standard's real OER excerpts), identical across
every pair, so the yardstick never depends on which condition randomly landed in
slot B.

> **`bench.json` is a stale artifact** from the old absolute-rubric run (schema:
> `means`/`content_accuracy`/`target_met`). It does **not** reflect the current
> pairwise design and should be regenerated on a fleet machine with Ollama:
> `uv run python -m oer_ingestion.benchmark --db data/oer_core.db --sg-db ~/.standardgraph/common_core.db --out bench.json`.
> Regeneration needs Ollama + the full DB, so it can't run on the dev MacBook.

## Batch execution workflow

Same conventions as StandardGraph. Plan table before multi-step runs:

| # | Job | Device | Deps | Est. time | Risk |
|---|---|---|---|---|---|
| 1 | example | Mini 2 | — | 20 min | low |

Risk flags: `token` · `destructive` · `irreversible`

### Pre-authorized (no per-step approval needed)

- SSH to `devos@100.101.100.96`, `devos@100.123.114.101`, `ianwangm1max@100.77.63.73`
- `git add`, `git commit`, `git push` to `origin main`
- File edits anywhere in this repo
- Starting pipeline jobs on the minis (embed, align, verify, annotate)
- Running pytest or eval scripts
- Pulling DB from Mini 2 to MacBook via `sqlite3 .backup`

### Always prompt separately (never batch)

- HuggingFace upload (`huggingface-cli upload`) — needs token, remind to rotate after use
- `DELETE` or `DROP` SQL against any DB
- Force push or branch deletion

## Security reminder

Tokens shared in chat — always remind to rotate immediately after use.
