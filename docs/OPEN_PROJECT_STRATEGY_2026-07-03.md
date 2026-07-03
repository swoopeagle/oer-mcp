# Open Project Strategy — StandardGraph + OER MCP

**Date:** 2026-07-03
**Status:** Adopted as working strategy (revisit at the month-6 gate, ~2027-01)
**Scope:** How to grow SG + OER MCP as an open project that builders build *upon*
(and, eventually, help build) — adoption, ecosystem, sustainability. Not a product/
revenue plan.

---

## Decisions locked in this session (Ian's answers)

| Question | Decision |
|---|---|
| What is this project for me? | Mission infrastructure **and** credibility/portfolio |
| Sustained maintainer time | 5–10 hrs/week |
| First audience to win | **Builders-on-top** (edtech / AI-tutor devs, researchers) |
| Governance | Minimal: **BDFL + DCO**, no CLA, no foundation until forced |
| Bundle SG + OER? | **One umbrella brand, staged launches** (SG first, OER when benchmark clears) |
| MCP coupling | **MCP-first; HF dataset + documented schema as the protocol-agnostic hedge.** No REST API yet |
| Grant-writing appetite | Undecided — decide at the month-6 gate based on reception |
| AP gray-zone tier | **Excluded from public launch.** Build-it-yourself script in repo; never hosted on HF |

---

## Part 1 — Devil's advocate: "keep it small" steelmanned

**The claim, strongest form:** With 5–10 hrs/week, Ian can grow SG + OER MCP into
open infrastructure that a community both builds and builds upon, because the assets
are genuinely rare (a license-partitioned, standards-aligned, benchmark-validated
open corpus) and MCP distribution is a rising tide.

### Structural obstacles

1. **The contribution surface is unusually hostile.** Meaningful contributions (new
   adapters, alignment verification, item generation) require domain knowledge *plus*
   the 7-stage pipeline *plus* local Ollama compute — the pipeline currently assumes
   a personal Mac fleet over Tailscale. Typical OSS contributors fix a function; ours
   would need to reproduce the lab. Projects like this get *data consumers*, not data
   contributors, almost by default.
2. **Open-data projects get adoption without community.** People download the HF
   dataset, build on it, and never file an issue. That's success by CC BY's own logic
   — but "contributors" is a lagging indicator that can't be forced, and every
   community program run at 5–10 hrs/week competes with the engineering that actually
   attracts builders.
3. **The MCP directory is a sea of zero-user servers.** Thousands of listed servers,
   weak discovery, most with no sustained usage. Listing is table stakes, not
   distribution.
4. **The moat is thinner than it feels.** OpenStax and IM are freely downloadable; a
   funded edtech team can replicate chunk-embed-align with frontier LLMs in weeks.
   The durable edge is the *verified* alignments, the crosswalks, the license
   partitioning, and SG's 298-system graph — not the corpus itself.
5. **Scope honesty:** US-centric Common Core (politically wobbly), K–12 math only,
   61% strong coverage, 29 assessment items, ncsa.db not built on the dev machine,
   and the headline benchmark **has not been re-run under the fixed pairwise design**.
   "Infrastructure" is currently an aspiration, not a description.

### Failed analogues

Open-education infrastructure has a specific graveyard: the **Learning Registry**
(federally funded standards-aligned content-metadata network — dead), LRMI's
ecosystem ambitions, various OER alignment registries. They died of exactly this:
alignment metadata is valuable but nobody's *product*, so nobody staffed it after
the grant. A solo maintainer at 5–10 hrs/week has less runway than those had.

### Load-bearing assumptions (what a skeptic attacks first)

- **A1: Builders-on-top exist *now*** — teams building AI tutors who would rather
  adopt this stack than roll their own RAG. If false, everything downstream is
  theater.
- **A2: The benchmark lift is real and reproducible.** The 86% figure predates the
  fixed pairwise design; the honest number doesn't exist yet. If the re-run comes in
  under 60%, the core pitch is unsupported.

### What would refute the counter-case (falsifiable, near-term)

- ≥3 external builders integrate SG or OER within 90 days of launch without
  concierge hand-holding;
- ≥1 unsolicited substantive issue or PR from a stranger;
- pairwise benchmark ≥60%, reproducible by someone who isn't Ian.

### Verdict

The counter-case is **strong** against "a community helps build it" in year one, and
**weak** against "builders build upon it." So the plan inverts the original framing:
**this is an adoption-first open project where contributors are a harvested side
effect, not a growth target.** That's the honest synthesis of "grow" vs "stay
small" — and it fits 5–10 hrs/week, where a community-first plan does not.

---

## Part 2 — The roadmap

### Positioning

**"Open curriculum intelligence: the grounding layer for AI-native education."**
SG knows what students must learn; OER MCP knows what content teaches it. One
umbrella brand, staged launches. A *layer* pitch, not a product pitch:

- **vs. Khan / IXL:** closed end-user products. We're the substrate their
  competitors build on. No overlap; don't mention them much.
- **vs. rolling-your-own RAG (the real competitor):** "You can re-scrape OpenStax
  and embed it in a weekend. You cannot cheaply get verified standard alignments, a
  298-system crosswalk graph, exam crosswalks, prerequisite-aware paths, and clean
  license partitioning. We did the boring, expensive layer. CC BY.
  Benchmark-proven." (Last clause usable only after the re-run — hence benchmark is
  milestone #1.)
- **vs. closed RAG-over-textbooks:** license hygiene *is* the feature. Commercial
  builders can ship on `oer_core.db` without a lawyer.

### Licensing & contribution architecture

- **Server code (both repos): Apache-2.0.** Over MIT because the explicit patent
  grant is what corporate builders' counsel looks for in "infrastructure."
- **Contributions: DCO** (`Signed-off-by`, enforced by a bot). No CLA — at this
  scale a CLA signals extraction and kills marginal PRs.
- **Data:** keep the three-tier split, but make it *legible*: a `LICENSING.md`
  decision tree ("Commercial? → core only, here's the flag"), per-chunk provenance
  fields, and a CI check that fails if a non-CC-BY source lands in core. The
  partition is only an asset if builders can verify it without trusting the
  maintainer.
- **AP tier: excluded from public distribution.** Ingestion script stays in-repo as
  build-it-yourself; `oer_ap.db` is never hosted on HF. One takedown letter would
  taint the whole trust story.
- **Original items: CC BY 4.0**, clearly marked `style_generated` / AI-authored;
  surface this in the dataset card.

### Bundle mechanics

One GitHub **org** (name TBD — something like `open-curriculum-intelligence`, not a
personal handle), both repos moved in, one shared docs/landing page. Moving off
`swoopeagle` personal repos is a cheap bus-factor and seriousness signal.
Shared: LICENSING.md, ROADMAP.md, docs site. Separate: releases, versioning, issues.

### Sustainability

Must be **viable at $0** (grant appetite undecided) — and it is: infra costs
~nothing, HF hosts the data, the fleet does the compute.

- **Now:** GitHub Sponsors button + Open Collective page (an hour, passive, gives
  funders a place to look). Nothing else.
- **Month-6 gate:** *if* refutation conditions are met (3+ builders, unsolicited
  contribution, benchmark public), write **1–2 targeted applications** — Hewlett's
  OER program and a Gates K–12 math RFP are natural fits; GitHub Accelerator as a
  wildcard. Grants fund people and there are no people, so scope any ask to compute
  + contract help (e.g., a contractor to close the coverage gap), not salary.
- **Explicitly deferred:** open-core hosted MCP endpoint. The one plausible
  earned-revenue path (remote MCP for orgs that won't download a 1.8 GB DB), but it
  creates on-call obligations a solo maintainer can't staff. Note in ROADMAP.md as
  "future, if pulled."
- **Fiscal host:** not until there's money to receive. Open Collective's OSC is a
  one-week decision when needed; early is pure overhead.

### Three horizons

#### H1 — Days 0–30: "Ship SG, prove OER"

1. **Close SG's four blockers** (71 short-text standards, merge
   `eval-suite-and-merge-tooling` to main, run the live e2e smoke test, refresh HF
   upload) → **tag SG v1.0** under Apache-2.0 + DCO with a builder-facing README
   quickstart.
2. **Re-run the OER pairwise benchmark on the fleet.** Single highest-leverage task
   in the entire plan. Publish the number in `BENCHMARK.md` *whatever it is* —
   ≥60% becomes the launch headline; <60% means fix retrieval before launching OER
   at all, and the plan pauses there honestly.
3. Stand up the org + landing page + LICENSING.md.
4. **Distribute SG:** official MCP registry, Smithery, PulseMCP, Glama, mcp.so; one
   launch post (Show HN and/or the MCP Discord) written for builders, not teachers.

*Metrics:* SG v1.0 tagged; benchmark number public; ≥3 registry listings; baseline
HF-download and install counts recorded (do this in week 1 — no growth measurement
without a baseline).

#### H2 — Days 30–90: "OER v1 + first builders"

1. **OER launch:** build and upload `oer_ncsa.db`, ingest SBAC + NAEP items
   (endpoints verified first), one-command install, **Claude Desktop extension
   bundle** (one-click .mcpb is the difference between "developers can try it" and
   "anyone can").
2. **The killer demo:** a "build a standards-grounded AI math tutor in 30 minutes"
   tutorial using both MCPs + a runnable notebook on HF. For builders, one great
   tutorial outperforms any community program.
3. **Concierge outreach, not broadcast:** 5–10 direct conversations with
   AI-tutor/edtech builders and 2–3 education-NLP researchers. At this time budget,
   hand-onboarding the first builders *is* the growth strategy.
4. **Contribution surface, minimal by design:** accept only fleet-free contribution
   types — crosswalk corrections, alignment-verification review (document how to
   check an alignment without Ollama), adapter *specs*, item review. 10–15 genuine
   good-first-issues. Publish ROADMAP.md.

*Metrics:* ≥3 external builders integrated or in serious evaluation; ≥1 unsolicited
issue; strong CCSS coverage 61% → ~70%; OER benchmark cited by someone else.

#### H3 — Days 90–180 → 12 months: "Decide with evidence"

**Month-6 gate — the honest fork:**

- **Traction** (refutation conditions met): write the 1–2 grant applications;
  recruit one co-maintainer *from the most engaged builder* (never from
  volunteers-in-the-abstract); expand where the differentiation is —
  state-standards alignment in OER via SG's crosswalks (nobody else can do
  CCSS → 50-state mapping), coverage to 85%+ strong, community adapter spec for new
  standards systems; revisit hosted MCP as remote-MCP transport matures.
- **No traction:** downgrade *deliberately* to maintained-tool mode — dataset
  refreshes and security fixes at ~2 hrs/month, HF dataset stays live, README says
  exactly what it is. A graceful landing, not a failure; the corpus keeps
  compounding value for Ian's other projects either way.

*12-month metrics (traction branch):* 10+ downstream builders identifiable; 3+
external contributors with merged PRs; 1 research citation; bus-factor ≥ 2; funding
decision made on evidence.

### Risk register

| Risk | De-risk |
|---|---|
| Bus-factor of one | Org not personal account; document a fleet-free pipeline reproduction path (any cloud GPU or OpenAI-compatible endpoint); co-maintainer at month 6 from users, not volunteers |
| Benchmark fails re-run | Run it *first*, before any OER launch spend; treat it as a regression suite thereafter |
| License compliance | Per-chunk provenance, CI license-lint on core, AP never hosted, LICENSING.md decision tree |
| MCP/Anthropic dependence | HF SQLite DBs + documented schema are the hedge; revisit REST only if a real builder asks |
| Adoption-without-contribution | Accepted by design — optimize for builders; contributors are harvest, not target |
| CCSS/US-only fragility | SG's 298 international systems is the hedge; lead with it in positioning |

### Success metrics by audience

- **End-adopters:** installs, HF downloads, registry ratings — track, don't chase.
- **Builders-on-top (primary):** named integrations, schema/API questions in issues,
  tutorial completions, citations. Target: 3 by day 90, 10 by month 12.
- **Contributors (lagging):** unsolicited issues → first merged external PR →
  repeat contributor. Target: 1 / 3 / 1 respectively by month 12.

---

## Three hard truths to hold onto

1. **Nothing ships credibly until the pairwise benchmark is re-run** — it's the
   load-bearing claim and it's currently unverified.
2. **At 5–10 hrs/week this is an *adoption* project with a contribution on-ramp,
   not a community project** — plans that pretend otherwise burn the maintainer out.
3. **The month-6 gate is only useful if the no-traction branch is honored** — which
   is why it's written into the plan.

## Suggested next steps

- Run `/scope-lock` on the H1 milestone so the SG-ship scope can't creep.
- Run `/measurement-framework` once SG v1.0 is out to formalize baseline
  instrumentation.
- Full `/competitive-teardown` if a serious closed competitor (RAG-over-textbooks
  startup) surfaces.
