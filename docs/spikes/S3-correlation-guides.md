# Spike S3 — OpenStax CCSS correlation guides
**Date:** 2026-06-09 · **Verdict: NOT AVAILABLE — fall back to embedding-only alignment for OpenStax**

## What was checked
- The PRD's `openstax.org/books/{slug}/pages/correlation-guide` URL pattern: no such pages found for math titles.
- GitHub code search across `osbooks-algebra-1` (the most likely candidate — it's built on Illustrative Mathematics, a standards-aligned curriculum): zero occurrences of `CCSS` or `HSA-` standard IDs in the book source.
- Web search for published OpenStax CCSS correlation documents: none machine-readable found. (State DOEs publish their own correlation PDFs for other curricula; not usable here.)

## Consequence (this was the planned fallback)
- Stage 5 Pass 1 (`publisher_guide`, score 0.92–0.95) applies only to sources whose content carries standards metadata: Khan Academy (pending S2 gate) and CK-12 (FlexBooks carry CCSS tags).
- All OpenStax alignment comes from Stage 5 Pass 2 (embedding similarity vs StandardGraph CCSS embeddings, threshold 0.65) — making the **M1 alignment-quality checkpoint mandatory before scaling** (BUILD_PLAN standing risk #1).
- Consider a gemma4:31b verification pass over high-traffic OpenStax alignments as a cheap confidence booster (build-time only) if the M1 eyeball check is marginal.
- Alignment count targets in PRD §15 assumed publisher-guide seeds for OpenStax; expect the `publisher_guide` row counts to shift toward Khan/CK-12.
