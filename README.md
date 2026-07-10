# OER MCP

**A curriculum content + assessment retrieval layer for LLMs.** Open-licensed K–12 content across **math, science, and social studies** (OpenStax textbooks, Khan Academy transcripts, Illustrative Mathematics) *and* real released exam items (Smarter Balanced, NAEP, NY Regents, MCAS, AP free-response) — chunked by concept, aligned to 300+ curriculum standards, and queryable by standard ID and subject. So an LLM tutoring, lesson-planning, or assessment-writing task is grounded in *what students actually read and are tested on*, not a plausible approximation from training data.

Companion to [StandardGraph](https://github.com/swoopeagle/standardgraph): StandardGraph knows *what students must learn* (standards across 7 subjects); OER MCP knows *what content teaches it and how it's assessed*.

> **Status:** Live, multi-subject (math, science, social studies). **~16,000 content chunks + ~1,000 assessment chunks** across four license-partitioned databases, **~55,000 standard alignments** across 12+ curriculum systems (CCSS, AP, state, C3 framework, etc.), served through **8 MCP tools**. Real released items from **6+ assessment programs**. Query-layer parametrized by subject/system — single tool invocation works across all curriculum frameworks.
>
> **Pre-built databases available on [🤗 HuggingFace](https://huggingface.co/datasets/swoopeagle/oer-mcp)** — download directly or use the installer script below.

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

**Mathematics (CCSS + AP + state standards):**
- *"Find content that teaches CCSS.MATH.6.NS.1"*
- *"Explain dividing fractions using the actual textbook examples"*
- *"How completely does the indexed content cover CCSS 6.RP?"*
- *"Which exams assess CCSS.MATH.7.EE.4, and show me real released items"*
- *"Build a prerequisite-aware learning path for CCSS.MATH.8.EE.1"*

**Science (AP Biology, Chemistry, Physics):**
- *"What OpenStax content teaches AP.AP_BIO.2.1.A?"*
- *"How does the corpus cover AP Chemistry's Big Idea 1?"*

**Social Studies (AP US Government, US History, Psychology, Economics, World History):**
- *"Find content aligned to AP.AP_US_GOV.2.A"*
- *"Coverage report for the C3 Framework's Inquiry Arc on civics"*

## Tools

All tools work across **any curriculum system** (CCSS, AP, state standards, C3 Framework, etc.) via an optional `system` parameter.

| Tool | What it does |
|---|---|
| `fetch_for_standard` | OER content that teaches a given standard ID, ranked by alignment confidence; system-aware (e.g., `AP.AP_BIO.2.1.A` or `CCSS.MATH.6.RP.3`); returns `{standard_id, count, results}` |
| `search_content` | Natural-language concept search (hybrid semantic + FTS5 keyword; degrades to keyword if no embedder); works across all subjects |
| `get_chunk` | Retrieve a specific section by ID, with neighbours and all standard alignments |
| `check_coverage` | How completely the corpus covers a standard/cluster (can target any system: CCSS, ap-bio, ap-us-gov, c3, etc.) — strong/moderate/light/none bands + gaps |
| `list_sources` | Live inventory of indexed sources, books, chunks, and attached databases |
| `map_to_assessments` | Map a standard to high-stakes exams (SAT/ACT/AP/state/NAEP) — skill domains + available released items + gaps |
| `get_learning_path` | **Prerequisite-aware path**: walks StandardGraph prereqs → OER content per rung, bottom-up; system-aware; surfaces `prerequisite_gaps` |
| `get_capabilities` | Self-describing manifest: sources, standard systems, exam series, grade bands, coverage stats, and all 8 tools |

Every content response carries an **attribution string** to preserve downstream licensing.

## What's indexed

### Mathematics (18 textbooks, 18,000+ chunks)

| Source | Content | License | DB |
|---|---|---|---|
| OpenStax | Math series (prealgebra → calculus, 14,065 chunks) | CC BY | core |
| Illustrative Mathematics | K-12 lessons (1,796 chunks, publisher CCSS tags) | CC BY | core |
| Khan Academy | 3,322 video-transcript chunks | CC BY-NC-SA | ncsa |
| OpenMiddle | 597 DOK-3 constructed-response problems | CC BY-NC-SA | ncsa |
| Smarter Balanced | 525 released items (grades 3-8 + HS) | CC BY | core |
| NAEP | 1,269 items (grades 4/8/12, 1990-2024) | public domain | core |
| NY Regents | 1,672 released exam questions (Algebra I/Geometry/Algebra II) | state copyright, educational use | state |
| MCAS | 366 released items (grades 3-8, 10) | state copyright, educational use | state |
| AP free-response | 85 FRQs (Calc AB/BC, Stats, Precalc, 2023-2026) | © College Board, educational use | ap |
| SAT/ACT-style | Gemma-authored style items with answer keys | not verbatim; MIT | core |

**Science (5 textbooks, ~4,600 chunks)**

| Source | Content | License | DB |
|---|---|---|---|
| OpenStax | Biology 2e (1,407 chunks) | CC BY-NC-SA | ncsa |
| OpenStax | Biology AP Courses (1,564 chunks) | CC BY-NC-SA | ncsa |
| OpenStax | Chemistry 2e (770 chunks) | CC BY-NC-SA | ncsa |
| OpenStax | College Physics 2e (1,571 chunks) | CC BY-NC-SA | ncsa |
| OpenStax | University Physics Vols 1–3 (1,695 chunks) | CC BY-NC-SA | ncsa |

**Social Studies (8 textbooks, ~5,200 chunks)**

| Source | Content | License | DB |
|---|---|---|---|
| OpenStax | US History (733 chunks) | CC BY-NC-SA | ncsa |
| OpenStax | American Government 4e (495 chunks) | CC BY-NC-SA | ncsa |
| OpenStax | Psychology 2e (636 chunks) | CC BY-NC-SA | ncsa |
| OpenStax | Macro/Microeconomics AP Courses (1,281 chunks) | CC BY-NC-SA | ncsa |
| OpenStax | Introduction to Sociology 3e (609 chunks) | CC BY-NC-SA | ncsa |
| OpenStax | World History Volumes 1–2 (980 chunks) | CC BY-NC-SA | ncsa |

Assessment items carry `item_type`, `dok_level`, `answer_key`, `exam_series`, `exam_year`, and `difficulty` where the source provides them.

## How it works

```
Claude Desktop
  ├── StandardGraph MCP   "what must students learn"     (300+ standards, prereqs, crosswalks)
  └── OER MCP             "what teaches it / how it's assessed"
        oer_core.db    CC BY / public domain  (OpenStax math, IM, SBAC, NAEP)  ← default
        oer_ncsa.db    CC BY-NC-SA            (Science, social studies, Khan, OpenMiddle)  ← --with-khan
        oer_state.db   state copyright        (NY Regents, MCAS)                ← --with-state
        oer_ap.db      College Board          (AP free-response)                ← --with-ap
```

**Build-time ingestion:**
1. Fetch → snapshot (raw) → chunk into typed units (`exposition`, `worked_example`, `exercise_set`, `summary`, `assessment`)
2. Embed all chunks with `nomic-embed-text` (or use embedding vectors if provided by source)
3. **Align to all available curriculum systems** — by publisher tags where available (e.g., Illustrative Math's CCSS tags, OpenStax's AP tags), otherwise by cosine similarity against StandardGraph's standard embeddings with grade-distance penalty and source-aware confidence bands
4. High-confidence embedding matches are **optionally LLM-verified** (promoted to `llm_verified` tier)
5. Query-layer is **system-parametrized**: a single tool invocation routes to the right curriculum system (CCSS, ap-bio, c3, state standards, etc.)

**At query time:**
- Pure SQLite + vector lookups across whichever databases are attached
- No live StandardGraph call (standards are baked at build time)
- Semantic search degrades gracefully to FTS5 keyword fallback when no embedder is reachable
- All queries respect the `system` parameter to target the right standard framework

**Confidence hierarchy:** `human` > `publisher_guide` > `llm_verified` > `embedding`. Affects ranking and coverage bands.

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
