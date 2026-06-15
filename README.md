# OER MCP

**A curriculum content retrieval layer for LLMs.** Open-licensed math content (OpenStax textbooks + Khan Academy video transcripts), chunked by concept, aligned to curriculum standards, and queryable by standard ID — so an LLM tutoring or lesson-planning task is grounded in *what students actually read*, not a plausible approximation from training data.

Companion to [StandardGraph](https://github.com/swoopeagle/standardgraph): StandardGraph knows *what students must learn* (the standards); OER MCP knows *what content teaches it*.

> **Status:** Phase 1 — OpenStax + Khan layer complete. ~12,000 content chunks, **327 of 343 CCSS standards covered (95%)**, K-12. See [PRD](../PRD.md) and [BUILD_PLAN](../BUILD_PLAN.md).

## Install

```bash
# Core content (OpenStax, CC BY) → Claude Desktop
curl -fsSL https://raw.githubusercontent.com/swoopeagle/oer-mcp/main/install.sh | bash

# Also add the K-12 Khan Academy transcript layer (CC BY-NC-SA)
curl -fsSL https://raw.githubusercontent.com/swoopeagle/oer-mcp/main/install.sh | bash -s -- --with-khan
```

Then restart Claude Desktop. Try: *"Find content that teaches CCSS.MATH.6.NS.1"* · *"Explain dividing fractions using the actual textbook examples"* · *"How completely does the indexed content cover CCSS 6.RP?"*

## Tools

| Tool | What it does |
|---|---|
| `fetch_for_standard` | OER content that teaches a given standard ID, ranked by alignment confidence |
| `search_content` | Natural-language concept search (hybrid semantic + keyword; degrades to keyword if no embedder) |
| `get_chunk` | Retrieve a specific section by ID, with neighbours and alignments |
| `check_coverage` | How completely the corpus covers a standard/cluster — surfaces gaps |
| `list_sources` | Live inventory of indexed sources, books, chunks, and attached databases |

Every content response carries an **attribution string** to preserve downstream.

## How it works

```
Claude Desktop
  ├── StandardGraph MCP   "what must students learn"   (standards, crosswalk)
  └── OER MCP             "what content teaches it"
        oer_core.db   CC BY content (OpenStax)              ← default
        oer_ncsa.db   CC BY-NC-SA content (Khan, +OpenStax 2e)  ← optional add-on
```

Content is ingested, chunked into typed units (exposition / worked_example / exercise_set / summary), embedded (`nomic-embed-text`), and aligned to CCSS at **build time** by cosine similarity against StandardGraph's standard embeddings, with a grade-distance penalty and source-aware confidence bands. High-confidence alignments are **gemma-verified** (`llm_verified` tier) — the LLM confirms the content actually teaches the standard. At query time the server does pure SQLite + vector lookups across both attached databases; no live StandardGraph call, and semantic search degrades gracefully to FTS5 keyword search when no embedder is reachable.

Confidence hierarchy: `human` > `publisher_guide` > `llm_verified` > `embedding`.

## Licensing

Code is MIT. **Content is licensed by its publishers** and partitioned by license across the two databases — see [NOTICE](NOTICE). The core DB is CC BY (commercial-friendly with attribution); the Khan add-on and OpenStax 2e titles are CC BY-NC-SA (non-commercial). Attribution is non-nullable and surfaced in every response.

## Development

```bash
uv sync
uv run pytest                                   # 50 tests

# Build the databases (needs Ollama; build-time only)
uv run python -m oer_ingestion.pipeline openstax --book all --db data/oer_core.db --sg-db <standardgraph.db>
uv run python -m oer_ingestion.pipeline embed-align --db data/oer_core.db --sg-db <standardgraph.db>
uv run python -m oer_ingestion.pipeline verify      --db data/oer_core.db --sg-db <standardgraph.db>
uv run python -m oer_ingestion.pipeline annotate    --db data/oer_core.db --sg-db <standardgraph.db>
uv run python -m oer_ingestion.pipeline validate    --db data/oer_core.db

uv run python -m oer_ingestion.pipeline khan --db data/oer_ncsa.db --channel-db <kolibri-khan.sqlite3>

OER_CORE_DB_PATH=data/oer_core.db uv run oer-mcp     # run the stdio server
```

Layout: `packages/shared` (config, schema, models, db), `packages/ingestion` (adapters + 7-stage pipeline), `packages/server` (FastMCP stdio server). Source adapters implement a common `SourceAdapter` interface; spike findings are in `docs/spikes/`.

## Acknowledgements

Content from [OpenStax](https://openstax.org) (Rice University) and [Khan Academy](https://www.khanacademy.org), the latter via [Learning Equality](https://learningequality.org)'s Kolibri. Built on [FastMCP](https://github.com/jlowin/fastmcp).
