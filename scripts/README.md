# Scripts Inventory

⚠️ **Runtime & Cost Classification:**
- 🟢 **Local-only** — safe to run anytime, no network calls
- 🟡 **Needs Ollama** — requires local gemma/nomic fleet (see CLAUDE.md for fleet setup)
- 🔴 **Spends Anthropic API** — incurs cost; rotate `ANTHROPIC_API_KEY` after use

## Quick Reference

| Runtime | Scripts |
|---------|---------|
| 🟢 Local-only | `audit_alignment_quality.py`, `benchmark_performance.py`, `generate_coverage_analysis.py`, `local_verify_alignments.py`, `local_annotate_alignments.py`, `m1_checkpoint.py`, `resplit_by_license.py` |
| 🔴 API cost | `claude_verify_alignments.py`, `claude_annotate_alignments.py` |

---

## Scripts

### 🟢 audit_alignment_quality.py
**What it does:** Deep data quality audit: alignment distribution, outliers, coverage gaps, source quality.

Analyzes:
1. Alignment distribution by grade level
2. Coverage by standard (which standards are well/poorly covered)
3. Outliers and suspicious alignments
4. Quality comparison by source
5. Gap analysis (zero/weak coverage standards)

**Key args:** `--db` (path to oer_core.db), `--sg-db` (StandardGraph DB path)

**Example:**
```bash
uv run python scripts/audit_alignment_quality.py \
    --db data/oer_core.db \
    --sg-db ~/.standardgraph/common_core.db
```

---

### 🟢 benchmark_performance.py
**What it does:** Performance benchmarking: measure query speed (ideally before/after index optimization).

Runs a suite of representative queries and reports timing in ms. Use to verify schema optimization impact.

**Key args:** `--db` (path to oer_core.db)

**Example:**
```bash
uv run python scripts/benchmark_performance.py --db data/oer_core.db
```

---

### 🔴 claude_verify_alignments.py
**COST WARNING:** This script spends Anthropic API credits. Rotate `ANTHROPIC_API_KEY` after use.

**What it does:** Claude-based alignment verification — re-score embedding alignments in the moderate band (0.70–0.78) using Claude Opus/Sonnet for higher-quality verification.

Processes embeddings with score 0.70–0.78 and updates `standard_alignments.alignment_score`.

**Key args:** 
- `--db` (path to oer_core.db)
- `--sg-db` (StandardGraph DB path)
- `--model` (claude-opus-4-8, claude-sonnet-4-6, etc.)
- `--batch-size` (default 10)
- `--dry-run` (preview without modifying DB)

**Prerequisites:** `ANTHROPIC_API_KEY` set in environment

**Example:**
```bash
export ANTHROPIC_API_KEY=sk-...
uv run python scripts/claude_verify_alignments.py \
    --db data/oer_core.db \
    --sg-db ~/.standardgraph/common_core.db \
    --model claude-opus-4-8 \
    --batch-size 10 \
    --dry-run
```

---

### 🔴 claude_annotate_alignments.py
**COST WARNING:** This script spends Anthropic API credits. Rotate `ANTHROPIC_API_KEY` after use.

**What it does:** Claude-based coverage note annotation — generate substantive coverage notes for verified alignments explaining how each chunk teaches/addresses a standard.

Targets alignments with:
- `alignment_source = 'publisher_guide'` or `'human'` (high confidence, always)
- `alignment_source = 'llm_verified'` (already verified)
- `alignment_score >= 0.78` (embedding strong band, verified)

**Key args:**
- `--db` (path to oer_core.db)
- `--sg-db` (StandardGraph DB path)
- `--model` (claude-opus-4-8, claude-sonnet-4-6, etc.)
- `--batch-size` (default 10)
- `--dry-run` (preview without modifying DB)

**Prerequisites:** `ANTHROPIC_API_KEY` set in environment

**Example:**
```bash
export ANTHROPIC_API_KEY=sk-...
uv run python scripts/claude_annotate_alignments.py \
    --db data/oer_core.db \
    --sg-db ~/.standardgraph/common_core.db \
    --model claude-opus-4-8 \
    --dry-run
```

---

### 🟢 generate_coverage_analysis.py
**What it does:** Coverage analysis — generate CSV reports and gap analysis suitable for visualization in Excel/Sheets.

Generates three CSVs:
1. `coverage_by_grade.csv` — Grade-level × domain heatmap
2. `standards_gaps.csv` — All 343 CCSS Math standards with gap classifications
3. `source_quality.csv` — Per-source quality metrics

**Key args:**
- `--db` (path to oer_core.db)
- `--sg-db` (StandardGraph DB path, defaults to `~/.standardgraph/common_core.db`)
- `--output-dir` (where to write CSVs, defaults to current directory)

**Example:**
```bash
uv run python scripts/generate_coverage_analysis.py \
    --db data/oer_core.db \
    --output-dir docs/analysis
```

---

### 🟢 local_verify_alignments.py
**What it does:** Local verification of alignment embeddings using heuristics (no API calls).

Applies deterministic rules:
1. Grade level compatibility
2. Standard validity
3. Content type relevance
4. Consistency checking

Fast and free alternative to Claude-based verification for initial filtering.

**Key args:**
- `--db` (path to oer_core.db)
- `--sg-db` (StandardGraph DB path)
- `--batch-size` (default 100)
- `--dry-run` (preview without modifying DB)

**Example:**
```bash
uv run python scripts/local_verify_alignments.py \
    --db data/oer_core.db \
    --sg-db ~/.standardgraph/common_core.db
```

---

### 🟢 local_annotate_alignments.py
**What it does:** Local annotation of alignment coverage notes using heuristics (no API calls).

Generates substantive coverage notes by:
1. Extracting standard definition
2. Analyzing chunk content type and title
3. Applying templates + heuristics
4. Writing results directly to DB

Fast and free alternative to Claude-based annotation for initial coverage notes.

**Key args:**
- `--db` (path to oer_core.db)
- `--sg-db` (StandardGraph DB path)
- `--batch-size` (default 100)
- `--dry-run` (preview without modifying DB)

**Example:**
```bash
uv run python scripts/local_annotate_alignments.py \
    --db data/oer_core.db \
    --sg-db ~/.standardgraph/common_core.db
```

---

### 🟢 m1_checkpoint.py
**What it does:** M1 alignment-quality checkpoint — eyeball whether the top chunks for known standards are actually on-topic. Run after embed-align stage.

Prints, for a handful of CCSS standards, the top aligned chunks with scores and acts as a sanity check.

**Key args:** Optional positional arg for DB path (defaults to config.CORE_DB_PATH)

**Example:**
```bash
uv run python scripts/m1_checkpoint.py data/oer_core.db
```

---

### 🟢 resplit_by_license.py
**What it does:** One-shot migration — move CC-BY-NC-SA OpenStax books from core → ncsa DB so the default core DB is truly CC-BY-only.

Idempotent-ish: only moves books still present in core whose license contains 'NC'. Used during initial ingestion to honor D11 (license split).

**Key args:** None; operates on hardcoded paths `data/oer_core.db` and `data/oer_ncsa.db`

**Example:**
```bash
uv run python scripts/resplit_by_license.py
```

---

## Runtime Dependencies

### 🟢 Local-only scripts (safe anytime)
All rely only on Python stdlib, sqlite3, and project dependencies:
- `audit_alignment_quality.py`
- `benchmark_performance.py`
- `generate_coverage_analysis.py`
- `local_verify_alignments.py`
- `local_annotate_alignments.py`
- `m1_checkpoint.py`
- `resplit_by_license.py`

### 🔴 API scripts (require credentials, incur cost)
- `claude_verify_alignments.py` — Requires `ANTHROPIC_API_KEY`
- `claude_annotate_alignments.py` — Requires `ANTHROPIC_API_KEY`

**After running either API script, rotate your `ANTHROPIC_API_KEY` immediately:**
```bash
# In Claude dashboard: https://console.anthropic.com/account/keys
# Delete the old key, create a new one, update your environment
```

---

## Common Patterns

### Preview before running (dry-run)
Most scripts support `--dry-run` to see what would be processed without modifying the DB:
```bash
uv run python scripts/claude_verify_alignments.py --db data/oer_core.db --dry-run
```

### StandardGraph DB requirement
Scripts that do standard definitions or gap analysis need:
```bash
--sg-db ~/.standardgraph/common_core.db
```
Defaults to this path if omitted.

### Batch processing
For API scripts, control batch size to balance speed vs. API quota:
```bash
--batch-size 10  # smaller = slower but safer
--batch-size 50  # larger = faster but uses more tokens
```

---

## See Also

- **CLAUDE.md** — Fleet setup (Ollama, Tailscale devices)
- **OPERATIONAL_RUNBOOK.md** — How to run ingestion pipelines
- **docs/DOCUMENTATION_INDEX.md** — All documentation index
