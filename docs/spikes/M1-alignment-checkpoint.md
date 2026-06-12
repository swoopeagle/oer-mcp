# M1 alignment-quality checkpoint
**Date:** 2026-06-10 · **Verdict: directionally sound, calibration work needed before M2**

Embedding-only alignment is all OpenStax has (S3), so per BUILD_PLAN standing
risk #1 we eyeball quality on one book before scaling. Run on the first 100
embedded Prealgebra 2e chunks (chapters 1–2: whole numbers) → 436 alignments.

## What's good
The embedding space works **directionally**. Top matches are topically right:
- "Introduction to Whole Numbers: Identify the Place Value" → `4.NBT.A.1`, `5.NBT.A.1` (place value / NBT) ✅
- "Divide Whole Numbers: Model Division" → `5.NBT.B.6` (divide whole numbers) ✅
- "Subtract Whole Numbers" → `1.OA` subtraction cluster ✅ (topic right)

So nomic-embed-text places OER content near the right standards. The core premise holds.

## Three calibration problems (fix before M2)

### 1. Scores compress below the PRD thresholds
Observed range across 436 alignments: **min 0.65, max 0.827, mean 0.721**. **Nothing reached 0.85.**
The PRD §8/§9 bands (`strong ≥0.85`, annotate `≥0.85`) were written assuming
publisher-guide-style scores. With short standard text vs long chunk text,
embedding cosine tops out ~0.83. As written, `check_coverage` would report
*everything* as "moderate" at best and the annotate stage would never fire.
**Action:** recalibrate bands for embedding alignment — e.g. strong ≥0.78,
moderate 0.70–0.78, light 0.65–0.70 — or normalize scores. Decision needed
(touches PRD §8 coverage levels). Once CK-12 publisher-guide alignments exist
(D17), keep the two scales separate by `alignment_source`.

### 2. Generic "Writing Exercises" chunks over-match
"Subtract Whole Numbers — Writing Exercises" ranks top against *many* standards.
These are reflective prompts ("Explain in your own words…") — semantically
generic, so they match broadly. exercise_set chunks of this kind are alignment
noise. **Action:** either exclude `writing`/`self-check` exercise groups from
alignment, or down-weight exercise_set chunks vs exposition when ranking.
Cheap fix; do it in the splitter (tag the group) or align stage.

### 3. No grade awareness → cross-grade mismatches
"Subtract Whole Numbers" (a grade 6–8 remediation section) aligns to `K.OA.A.1`,
`1.OA.B.3` (Kindergarten/1st). Topic right, grade wrong — embeddings ignore grade.
**Action:** down-weight or filter alignments where the standard's grade is far
from the chunk's `grade_band`. StandardGraph exposes each standard's grade, so
a grade-distance penalty at align time is straightforward. Decision: penalty
(soft) vs hard filter.

## Recommendation
Hold M2 (full OpenStax + scale) until (1)–(3) are addressed — they're cheap and
all live in the align stage / splitter. Re-run this checkpoint after fixes on a
ratios/fractions chapter (so probes like `6.RP.A.3`, `6.NS.A.1` have real
content).

## Resolution — fixes applied 2026-06-10 (D18)
All three implemented and re-validated on the same 100 chunks:
- **(1) Source-aware bands** in `oer_shared.coverage`; embedding annotate flag at 0.78.
- **(2) Generic exercise exclusion** (`align._is_generic_exercise`) — 8 Writing/Self-Check chunks skipped.
- **(3) Grade penalty** (`oer_ingestion.grades`, 0.02/grade-year) at align time.

Re-run result: 100 chunks → 330 alignments (was 436), 7 reach the new strong band
(was 0 at 0.85), 8 generic chunks skipped. **Top matches are now grade-appropriate**
(8.EE.3, 5.NBT.B.6, 7.NS.1, 4.NBT.A.1 — grades 4–8 for a 6–8 book); the
Kindergarten/1st-grade matches that polluted the top are gone. Covered by tests in
`test_grades.py`, `test_coverage.py`, `test_align_helpers.py`.

## Final verdict — PASS (full embed, 2026-06-10)
All 1248 chunks embedded → 3834 alignments across 175 CCSS standards. Topic
probes (corrected to SG's no-cluster-letter IDs — see below) are clearly on-topic:
- `6.NS.1` (divide fractions) → "Multiply and Divide Fractions: **Divide Fractions**" (0.804)
- `6.NS.5` (integers/number line) → "Introduction to Integers: **Locate … on the number line**" (0.860)
- `6.RP.3` (ratios) → "**Ratios and Rate**", "**Solve Proportions**" (0.726)
- `6.EE.1` (exponents) → "Multiplication **Properties of Exponents**" (0.751)

Embedding alignment finds the right content for the right standards; the D18
recalibration (strong ≥0.78) is vindicated — only 3/3834 reach the old 0.85 bar,
so 0.85 bands would have reported almost everything as "moderate". **OK to proceed
to M2 scale-up.**

### ID-format note (important)
StandardGraph CCSS IDs **omit cluster letters** — `CCSS.MATH.6.RP.3`, not
`CCSS.MATH.6.RP.A.3` (and the format is inconsistent: `6.NS.1` but `1.OA.B.3`).
align pulls IDs straight from SG, so OER alignment IDs == SG IDs. Probes/tools
must use SG's form; `check_coverage` tolerates both via exact-then-prefix match.

All five MCP tools smoke-tested live against the populated DB. `search_content`
returned `keyword_fallback` (Ollama busy with gemma → 2s query-embed timed out
→ FTS5) and still surfaced the right fraction content — D13 degradation working
in the wild.
