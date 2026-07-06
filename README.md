# OER MCP

**A curriculum content + assessment retrieval layer for LLMs.** Open-licensed K–12 math content (OpenStax textbooks, Khan Academy transcripts, Illustrative Mathematics) *and* real released exam items (Smarter Balanced, NAEP, NY Regents, MCAS, AP free-response) — chunked by concept, aligned to curriculum standards, and queryable by standard ID. So an LLM tutoring, lesson-planning, or assessment-writing task is grounded in *what students actually read and are tested on*, not a plausible approximation from training data.

Companion to [StandardGraph](https://github.com/swoopeagle/standardgraph): StandardGraph knows *what students must learn* (the standards); OER MCP knows *what content teaches it and how it's assessed*.

> **Status:** Live, K–12 math. **23,726 content + assessment chunks** across four license-partitioned databases, **67,671 standard alignments** (486 distinct CCSS standards in the core DB), served through **8 MCP tools**. Real released items from **6 assessment programs**. Retrieval degrades gracefully with no embedder present (FTS5 keyword fallback).

## Install

```bash
# Core content (OpenStax + Illustrative Mathematics + Smarter Balanced + NAEP, CC BY / public domain)
curl -fsSL https://raw.githubusercontent.com/swoopeagle/oer-mcp/main/install.sh | bash

# Add optional databases (any combination):
#   --with-khan    K-12 Khan Academy transcripts + OpenMiddle problems   (CC BY-NC-SA)
#   --with-state   NY Regents + MCAS released exam items                 (state copyright, educational use)
#   --with-ap      AP free-response questions                           (© College Board, educational use)
#   --all          core + every add-on
curl -fsSL https://raw.githubusercontent.com/swoopeagle/oer-mcp/main/install.sh | bash -s -- --with-khan --with-state
```

Then restart Claude Desktop. Try:
- *"Find content that teaches CCSS.MATH.6.NS.1"*
- *"Explain dividing fractions using the actual textbook examples"*
- *"How completely does the indexed content cover CCSS 6.RP?"*
- *"Which exams assess CCSS.MATH.7.EE.4, and show me real released items"*
- *"Build a prerequisite-aware learning path for CCSS.MATH.8.EE.1"*

## Tools

| Tool | What it does |
|---|---|
| `fetch_for_standard` | OER content that teaches a given standard ID, ranked by alignment confidence; returns `{standard_id, count, results}` |
| `search_content` | Natural-language concept search (hybrid semantic + FTS5 keyword; degrades to keyword if no embedder) |
| `get_chunk` | Retrieve a specific section by ID, with neighbours and alignments |
| `check_coverage` | How completely the corpus covers a standard/cluster — strong/moderate/light/none bands + gaps |
| `list_sources` | Live inventory of indexed sources, books, chunks, and attached databases |
| `map_to_assessments` | Map a standard to high-stakes exams (SAT/ACT/AP/state/NAEP) — skill domains + available released items + gaps |
| `get_learning_path` | **Prerequisite-aware path**: walks StandardGraph prereqs → OER content per rung, bottom-up; surfaces `prerequisite_gaps` |
| `get_capabilities` | Self-describing manifest: sources, standard systems, exam series, grade bands, coverage stats, and all 8 tools |

Every content response carries an **attribution string** to preserve downstream.

## What's indexed

| Source | Content | License | DB |
|---|---|---|---|
| OpenStax | 13 math textbooks (14,065 chunks) | CC BY | core |
| Illustrative Mathematics | K-12 lessons (1,796 chunks, publisher CCSS tags) | CC BY | core |
| Smarter Balanced | 525 released items (grades 3-8 + HS) | CC BY | core |
| NAEP | 1,269 items (grades 4/8/12, 1990-2024) | public domain | core |
| Khan Academy | 3,322 video-transcript chunks | CC BY-NC-SA | ncsa |
| OpenMiddle | 597 DOK-3 constructed-response problems | CC BY-NC-SA | ncsa |
| NY Regents | 1,672 released exam questions (Algebra I/Geometry/Algebra II) | state copyright, educational use | state |
| MCAS | 366 released items (grades 3-8, 10) | state copyright, educational use | state |
| AP free-response | 85 FRQs (Calc AB/BC, Stats, Precalc, 2023-2026) | © College Board, educational use | ap |
| SAT/ACT-style | Claude-authored style items with answer keys | not verbatim; MIT | core |

Assessment items carry `item_type`, `dok_level`, `answer_key`, `exam_series`, `exam_year`, and `difficulty` where the source provides them.

## How it works

```
Claude Desktop
  ├── StandardGraph MCP   "what must students learn"     (standards, prereqs, crosswalk)
  └── OER MCP             "what teaches it / how it's assessed"
        oer_core.db    CC BY / public domain  (OpenStax, IM, SBAC, NAEP)   ← default
        oer_ncsa.db    CC BY-NC-SA            (Khan, OpenMiddle)            ← --with-khan
        oer_state.db   state copyright        (NY Regents, MCAS)           ← --with-state
        oer_ap.db      College Board          (AP free-response)           ← --with-ap
```

Content is ingested, chunked into typed units (`exposition` / `worked_example` / `exercise_set` / `summary` / `assessment`), embedded (`nomic-embed-text`), and aligned to CCSS at **build time** — by publisher CCSS tags where available, otherwise by cosine similarity against StandardGraph's standard embeddings with a grade-distance penalty and source-aware confidence bands. High-confidence embedding matches are **LLM-verified** (promoted to the `llm_verified` tier once a model confirms the content actually teaches the standard).

At query time the server does pure SQLite + vector lookups across whichever databases are attached; no live StandardGraph call, and semantic search degrades gracefully to FTS5 keyword search when no embedder is reachable.

Confidence hierarchy: `human` > `publisher_guide` > `llm_verified` > `embedding`.

## Licensing

Code is **MIT**. **Content is licensed by its publishers** and partitioned by license across four databases — see [NOTICE](NOTICE):

- **`oer_core.db`** — CC BY / public domain. Commercial-friendly with attribution.
- **`oer_ncsa.db`** — CC BY-NC-SA. Non-commercial, ShareAlike.
- **`oer_state.db`** — state copyright (NYSED, MA DESE) reproduced under each state's educational-reproduction permission. **Not CC**; partitioned so deployments can exclude it.
- **`oer_ap.db`** — © College Board, included under an educational-use rationale. **Not CC**; partitioned so deployments can exclude it.

Attribution is non-nullable and surfaced in every response.

## Development

```bash
uv sync
uv run pytest                                   # full test suite

# Build the databases (needs Ollama; build-time only)
uv run python -m oer_ingestion.pipeline openstax --book all --db data/oer_core.db --sg-db <standardgraph.db>
uv run python -m oer_ingestion.pipeline im --db data/oer_core.db
uv run python -m oer_ingestion.pipeline embed-align --db data/oer_core.db --sg-db <standardgraph.db>
uv run python -m oer_ingestion.pipeline verify      --db data/oer_core.db --sg-db <standardgraph.db>
uv run python -m oer_ingestion.pipeline annotate    --db data/oer_core.db --sg-db <standardgraph.db>
uv run python -m oer_ingestion.pipeline validate    --db data/oer_core.db

uv run python -m oer_ingestion.pipeline khan --db data/oer_ncsa.db --channel-db <kolibri-khan.sqlite3>

OER_CORE_DB_PATH=data/oer_core.db uv run oer-mcp     # run the stdio server
```

Layout: `packages/shared` (config, schema, models, db), `packages/ingestion` (adapters + 7-stage pipeline), `packages/server` (FastMCP stdio server). Source adapters implement a common `SourceAdapter` interface.

## Acknowledgements

Content from [OpenStax](https://openstax.org) (Rice University), [Khan Academy](https://www.khanacademy.org) via [Learning Equality](https://learningequality.org)'s Kolibri, [Illustrative Mathematics](https://illustrativemathematics.org), [Smarter Balanced](https://smarterbalanced.org), [NAEP](https://nationsreportcard.gov), [OpenMiddle](https://openmiddle.com), NYSED, Massachusetts DESE, and the College Board. Built on [FastMCP](https://github.com/jlowin/fastmcp).
