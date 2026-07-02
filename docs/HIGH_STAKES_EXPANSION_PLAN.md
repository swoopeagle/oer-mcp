# High-Stakes Testing Expansion — Plan (2026-07-02)

Goal: broaden `map_to_assessments` coverage across the US high-stakes landscape
**without copyright infringement**. US-focused (no plan to expand far beyond the US).

## The one hard rule: license before content

The corpus is an *open* educational resource. We never ingest copyrighted exam
questions verbatim from third-party PDFs "floating around online." That would be
infringement and would poison the open-license guarantee the whole project rests on.
Every item falls into exactly one tier:

| Tier | What | How | DB |
|---|---|---|---|
| **Open (verbatim OK)** | NAEP (public domain), Smarter Balanced (CC BY), PARCC (public domain), IM assessments (CC BY) | ingest as-is with attribution | core / ncsa |
| **Style-generated** | SAT, ACT, IB, AP multiple-choice | Claude-authored *original* items modeled on the exam's style/rigor; `item_generation='style_generated'`, always carry an answer key; attribution disclaims affiliation | core |
| **Gray zone (partitioned)** | AP free-response (College Board © , educational-use argument) | separate `oer_ap.db`, opt-out-able; strong attribution | ap |

If a source doesn't clearly fit Open or a defensible gray zone, it's **style-generated**.

## Expansion targets (priority order)

1. **Scale SAT/ACT style items (Claude).** We're already good at this (24 items, 13
   standards). Extend to every standard in the SAT/ACT crosswalk, 2–3 items each,
   varied DOK. Pure Claude, no license risk. *Highest ROI, lowest risk.*
2. **NAEP + Smarter Balanced released items (Open, verbatim).** Public-domain / CC BY —
   the adapters exist (`naep`, `smarter_balanced`) but their endpoints are unverified
   (`# TODO: confirm params`). Verify endpoints, then ingest. Real released items with
   national % -correct difficulty signal (NAEP). *Fleet + endpoint investigation.*
3. **AP expansion.** Already architected: `ap_frq` adapter + `oer_ap.db` partition for
   free-response (gray zone). Add AP-style multiple-choice as Claude style items in
   core. Extend the crosswalk for all AP math subjects (Calc AB/BC, Stats, Precalc).
4. **IB Mathematics (new family).** Copyrighted → treat exactly like AP: Claude-authored
   *IB-style* items (`exam_series='IB Math AA'` / `'IB Math AI'`, style_generated) in
   core, plus an optional partitioned `oer_ib.db` if we ever add gray-zone released
   content. Add IB to `exam_crosswalks`. IB is widely used in US schools, so it fits
   the US focus.
5. **Additional state summative tests.** Many states release items publicly (public
   domain or state-owned, license varies) — case-by-case, verbatim only where the
   license is clear; otherwise style-generated.

## Plumbing already in place (no new architecture needed)

- `style_items` loader now generalizes across families via `_style_slug`
  (sat/act/sbac/naep) — adding `ib` / `ap` is a one-line map entry + a book title.
- `exam_crosswalks` seed + idempotent loader — extend with AP/IB rows.
- `map_to_assessments` matches leaf standards against ancestor prefixes and reports
  `items_status`.

## Explicitly out of scope
- Scraping copyrighted SAT/ACT/IB questions from unofficial PDFs. Not doing it.
- Non-US curricula/exams (beyond IB, which is US-relevant).
