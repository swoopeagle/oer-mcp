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
content). The full embed run is currently capacity-blocked on the Mac Studio
(competing job: ~6 min/batch, timeouts) — only 100/1248 chunks embedded so far;
embed is idempotent and resumes.
