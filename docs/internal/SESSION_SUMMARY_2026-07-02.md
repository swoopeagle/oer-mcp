# Session Summary — July 2, 2026

Day 2. The through-line: **the benchmark that "proved OER doesn't help" was lying**,
finding out why, and turning it into real product improvements. Plus closing out the
ops items (GitHub credit, HuggingFace). All on `main`; 159 tests green.

## The benchmark arc (the big one)

1. Ran the pairwise benchmark on the fleet → `both` (OER+SG) lost to `standardgraph`
   alone (0.20). Counterintuitive.
2. Chased it and found the real cause: **`_oer_context` never read the S4
   `fetch_for_standard` envelope** (`isinstance(res, dict) → return ""`), so the
   `both` condition received *no OER content* and the judge's reference was *empty*.
   Every prior "OER doesn't help" number was an artifact. Fixed + regression test
   (`ce9ea1a`).
3. The fleet judge models failed repeatedly: `gemma4:31b-q8` returns empty strings on
   short calls; `gemma3:27b` hung for 7.5h on 512-token generations. Abandoned the
   gemma-generator path.
4. Ran a **Claude-generated** benchmark instead (`run_benchmark_from_segments`):
   Claude authors the segments — the real MCP-consumer scenario — and gemma3:27b only
   judges (short calls work fine). Result, 7 topics grade 1→HS:
   - both vs standardgraph **0.86 ✅**, both vs none **1.00**, sg vs none 0.86.
   OER content genuinely helps once it's actually delivered. (`dfbfd6a`;
   `docs/analysis/claude_bench_*.json`, `BENCHMARK_ANALYSIS.md`.)

## Product improvements that fell out of it

- **Retrieval quality** (`c693ecd`): the benchmark exposed that `fetch_for_standard`
  surfaced IM *teacher-facilitation prose* (publisher_guide `exposition`) over worked
  examples (embedding). e.g. 8.EE.1 had 950 worked examples buried. Added
  `_CONTENT_RANK` (worked_example first) as the leading sort key. Honest limit: can't
  fix semantic false-positives — that's the verify pass.
- **Coverage truth-in-advertising** (`b9f808a`): replaced the unverified "95%" claim
  with measured numbers — 277/343 (81%) any alignment, 210/343 (61%) strong.

## Ops closed out

- **GitHub credit**: 63 commits re-authored `IanTheWang → swoopeagle` (filter-branch,
  dates preserved) + force-push; local identity now swoopeagle. + private-contributions
  enabled. Graph should fill for Jun 30–Jul 2.
- **HuggingFace**: `data/oer_core.db` (177 MB) uploaded to dataset `swoopeagle/oer-mcp`
  (created **private** — flip to public for distribution). **Token was pasted in chat →
  rotate it.**
- **High-stakes expansion plan** drafted (`docs/HIGH_STAKES_EXPANSION_PLAN.md`):
  license-compliant tiers, no scraping copyrighted questions.

## Carryover / next
- Scale SAT/ACT style items across the crosswalk; add AP/IB families.
- NAEP/SBAC released items (verify adapter endpoints — fleet).
- Alignment precision (verify pass) to complement the retrieval fix.
- Flip the HF dataset to public when ready for end-user distribution.
