# Session Summary — July 1, 2026

Continuation after the S1–S5 backlog. Goal: finish the four remaining threads
(speed / prerequisite paths / contract were already shipped) — **full-corpus
embed+align, assessment population, benchmark, and cleanup** — plus a policy shift
toward doing LLM work as Claude rather than the local gemma/qwen fleet.

**Headline:** the corpus went from 7% embedded to fully embedded and aligned, the
assessment feature returns real questions, seven latent bugs were fixed, and a new
Claude-driven verification stage replaced the gemma one. Tests **149 → 156**, all
green. All code + seeds pushed to `origin/main` (commits `cce930d`…`3c6ed6b`).

## Corpus metrics (data/oer_core.db)

| Metric | Before | After |
|---|---|---|
| Chunks embedded | 1,031 | **14,488** (100%) |
| Alignments | 3,961 | **32,906** |
| Distinct standards aligned | 204 | **275** |
| Exam crosswalk rows | 0 | **70** (15 exam series) |
| Style-generated assessment items | 0 | **14** (SAT + ACT, 10 standards) |
| Tests passing | 149 | **156** |

## Threads completed

### T1 — Full-corpus embed + align (fleet)
Embedded the ~13,500 un-embedded chunks on the Mac Studio (`nomic-embed-text`,
~5 min) and re-aligned: 32,906 alignments across 275 standards, 909 flagged
≥0.78, 399 generic-exercise chunks correctly skipped. Semantic search now covers
the whole corpus instead of 7% of it.

### T2 — Assessment population (Claude-authored)
- **Crosswalk loaded** (70 rows) — the seed had never parsed (see bugs).
- **14 Claude-authored SAT/ACT-style items** (`data/style_items.json` +
  `oer_ingestion.style_items`), version-controlled and reproducible, targeting
  StandardGraph-canonical leaf ids. `map_to_assessments('CCSS.MATH.8.EE.1')` now
  returns a real SAT item and a real ACT item with answer keys, DOK, difficulty.
- NAEP/SBAC/AP *released* items remain unfetched — those adapters hit live
  external endpoints with unverified params (genuine fleet/investigation work).

### T3 — Benchmark (fleet, in progress at session end)
Re-ran the pairwise content-grounding benchmark on the enriched corpus to refresh
`bench.json` (retiring the stale absolute-rubric artifact). Runs on gemma as the
generator by design — a *weak* generator best exposes OER lift.

**Outcome: run failed as a measurement, not committed.** The full 20-topic run
completed (~50 min) but every one of the 60 pairwise judgments was unparseable
(`unparsed=20` per comparison). Root cause: `gemma4:31b-it-q8_0` on the Studio
returns an **empty string** on short calls via *both* `/api/generate` and
`/api/chat` (confirmed directly), so the judge (num_predict=8) produced no verdict.
The garbage `bench.json` was discarded (committed version restored).
**Follow-up:** use a judge model that actually responds (try `qwen2.5:72b` or a
different gemma quant), or — better per the Claude-first policy — use Claude as the
judge while keeping a weak local generator. The benchmark *code* (fixed
ground-truth reference) is sound; only the judge model was the problem.

### T4 — Dev cleanup
Cross-referenced the two confusingly-named "D9" benchmarks
(`scripts/eval/e2e_benchmark.py` = integration/tool-calling;
`oer_ingestion.benchmark` = pairwise content-grounding).

### NEW — Claude-driven verification stage (`verify_seed`)
Reproducible, version-controlled replacement for gemma-verify on curated
high-value standards (`data/verified_alignments.json`). First batch: verified
7.EE.4, 8.F.1, 6.RP.3 as `llm_verified` with real coverage notes, and **rejected
a false positive** — an 8.EE.1 match scoring 0.81 that only evaluates x² (a
grade-6 notation skill, not the integer-exponent *properties* 8.EE.1 requires).

## Bugs fixed (each committed with tests)

1. `map_to_assessments` crashed on legacy DBs missing assessment columns →
   `migrate_schema` + graceful `items_status` degradation.
2. Benchmark slot-B reference leak → judge now scores against a fixed ground-truth
   reference.
3. Crosswalk seed never parsed (`//` comments broke `json.loads`) → JSONC loader.
4. Crosswalk leaf-standard match went the wrong direction (matched descendants,
   not ancestors) → ancestor-prefix matching.
5. Pipeline CLI fully broken at import (dead `OllamaClient` import) → lazy-load.
6. `.gitignore` too broad — package seed files (`exam_crosswalks.json`,
   `style_items.json`) were never tracked; a fresh clone would break both loaders.
7. Assessment CHECK migration was disabled by the column migration **and** dropped
   the FTS triggers without recreating them → CHECK-aware guard + trigger restore.

## Policy shift: Claude-first, fleet only when required

The fleet's role is now reduced to exactly two things: **(a) embeddings** (a chat
model can't emit vectors) and **(b) the benchmark generator** (a weak model best
measures OER lift). All judgment/authoring work — verify, annotate, item
generation — is done as Claude, at higher quality than gemma. The only limit is
scale (no API key → inline), so bulk-volume grinding stays on the fleet; curated
high-value work is Claude's.

## Not yet persisted / follow-ups

- **`bench.json` refresh** — pending the running benchmark; commit when it lands.
- **HuggingFace upload of `data/oer_core.db`** — the populated DB (embeddings,
  crosswalk, items, verifications) is git-ignored and lives only on the dev
  machine. Distributing it needs a HuggingFace upload (`swoopeagle/oer-mcp`),
  which requires a token — rotate after use.
- **NAEP/SBAC/AP released-item ingestion** — fleet + endpoint verification.
- The ~20k "light-band" (0.65–0.70) embedding alignments are likely cosine noise;
  recommend trusting the confidence tiers rather than mass-verifying them.
