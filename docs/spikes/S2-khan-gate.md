# Spike S2 — Khan Academy acquisition gate
**Date:** 2026-06-09 (run 1 of 2) · **Verdict: GO — but via Kolibri/Learning Equality, NOT scraping**

## Headline
Direct Khan scraping is **dead** (worse than the PRD assumed). But the official Khan Academy content is redistributed as a clean, complete SQLite database by **Learning Equality (Kolibri)** — a sanctioned channel that is strictly better than scraping on every axis. The gate passes through this route. This supersedes decision **D7** (structured scrape) — see proposed **D16**.

## Why scraping is dead
- `khanacademy.org` serves a Cloudflare "Client Challenge" shell to all non-browser traffic — **including `robots.txt`** (verified: 3 KB challenge HTML, `<title>Client Challenge</title>`).
- The internal GraphQL endpoint (`/api/internal/graphql/ContentForPath`) requires a per-query `hash=` and returns `400 {"errors":[{"message":"No hash= specified"}]}` without it. The hash is tied to the deployed client bundle — not reproducible from outside.
- A scrape adapter would need a full headless browser per page across ~27k nodes, fighting an active anti-bot system. Fragile, slow, and adversarial. **Do not build this.**

## The Kolibri route (GO)
Learning Equality publishes the Khan Academy channels through Kolibri Studio. The English–US curriculum channel:

| Property | Value |
|---|---|
| Channel ID | `c9d7f950ab6b5a1199e3d6c10d7f0103` (Khan Academy, English - US curriculum) |
| Channel DB | `https://studio.learningequality.org/content/databases/{channel_id}.sqlite3` — 114 MB, `content-type: application/vnd.sqlite3` |
| Content files | `https://studio.learningequality.org/content/storage/{c0}/{c1}/{checksum}.{ext}` (CDN, Cloudflare-cached, no challenge) |
| Resources | 27,701 nodes · last published 2026-01-23 |
| Node kinds | `topic` 6,787 · `video` 18,629 · `exercise` 9,072 |
| Grade tree | **Kindergarten → 8th grade (every grade), High school, Illustrative Mathematics, Eureka Math/EngageNY** — full K-12, K-5 confirmed |

Other English channels available if useful later: Standardized Test Prep (`6616efc8…`), CBSE India (`2fd54ca4…`), Philippines (`d0c9abcb…`).

### Schema (Kolibri `content_*` tables, verified)
- `content_contentnode`: `id, parent_id, title, description, kind, sort_order, lft/rght/tree_id/level` (nested-set tree), `license_name`, `grade_levels`, `categories`, `lang_id`. The tree reconstructs course → unit → lesson cleanly.
- `content_assessmentmetadata`: `assessment_item_ids` (JSON), `mastery_model` — links an exercise node to its Perseus items.
- `content_file` + `content_localfile`: map nodes to CDN files by `preset`. Presets present: `perseus` (3,167 exercise item bundles), `mp4`/`low_res_video`, **`video_subtitle` → 55,724 VTT files**, thumbnails.

### Content extraction — both work
- **Exercises:** Perseus `.perseus` files are ZIP archives containing per-item JSON. Verified: question `content` is Markdown + LaTeX (`**Put $7$ acorns in the box.**`), plus `hints[]` and `widgets`. A KG item confirms K-5 depth. ⚠️ Many items are interactive-widget-based (orderers, graphers, manipulatives) that degrade to text imperfectly — the parser must extract question stem + hints and flag widget-only items.
- **Video transcripts:** VTT subtitle files on the CDN — **this is the big win.** The PRD deferred transcripts as a separate fragile pipeline; via Kolibri they're a flat CDN download. Transcripts (not videos) become the natural Khan exposition content.

## Gate scorecard
| Criterion | Result |
|---|---|
| Tree for ≥3 grade levels incl. K-2 | ✅ Full K-12, KG/1st/2nd present |
| Written content w/ intact math notation | ✅ Perseus Markdown+LaTeX; VTT transcripts |
| Exercise sets as discrete units | ✅ 9,072 exercise nodes → Perseus items |
| Reproducible across runs | ✅✅ Static published DB w/ version — far more stable than any scrape |
| CCSS alignment metadata present | ❌ **No CCSS tags** (`content_contenttag` empty; no `categories` CCSS values) |

**4.5 / 5 → GO.** The one miss (CCSS metadata) means Khan alignment is **embedding-only**, same as OpenStax (S3). The `publisher_guide` confidence tier now has **no Phase 1 source** unless CK-12 (which does carry CCSS tags) is added. This raises the importance of the M1 embedding-alignment quality checkpoint for the whole project.

## Scope changes vs PRD
1. **Khan content = video transcripts + exercises.** There is no `article`/`document` node kind in the export — the "articles" half of the D7 scope isn't present here. Transcripts replace it (and are better exposition anyway).
2. **Transcripts promoted into Phase 1** (D7 had them deferred behind "if cheap"; they are cheap).
3. **Acquisition mechanism: Kolibri channel DB + CDN, no scraping, no headless browser.** Adapter `fetch()` = download channel sqlite + pull referenced Perseus/VTT files from CDN.

## ⚠️ Licensing — needs an owner decision (blocks Khan in the redistributable DB)
Per-node `license_name` in the channel DB:
| Content | License | Redistributable in our DB? |
|---|---|---|
| Videos / transcripts | **CC BY-NC-SA** (18,575) + a few CC BY-NC-ND | Yes → NC-SA add-on DB (D11), with attribution + ShareAlike |
| Exercises (Perseus) | **"Special Permissions — granted to distribute through Kolibri for non-commercial use"** (9,072); some College Board | **Unclear.** This permission is scoped to *Kolibri's* distribution, not arbitrary redistribution. Some items are College Board (non-CC). |

The CC BY-NC-ND videos are **No-Derivatives** — chunking a transcript is arguably a derivative, so ND content likely can't be included at all (only ~52 nodes; safe to exclude).

**Recommendation:** Phase 1 Khan = **video transcripts only** (CC BY-NC-SA, clean for the NC-SA add-on DB). Treat Perseus exercises as reference-by-URL metadata (store node + source_url + attribution, no redistributed content) until the "Special Permissions" scope is clarified with Learning Equality / Khan. This keeps us unambiguously in bounds while still delivering K-12 Khan exposition.

## Reproducibility (run 2)
Re-download the channel DB ≥24h later; confirm same `channel_id`, comparable node counts, and that the published version is stable. Because this is a static published artifact (not a live scrape), run 2 is a formality — the real risk is Learning Equality unpublishing/relicensing, not per-session drift.

## Next-step pointers for the Khan adapter (M3)
- `fetch()`: GET channel sqlite → for in-scope nodes, GET `{checksum}.vtt` (and `.perseus` if licensing clears) from CDN; snapshot all raw files (PRD §11).
- `parse()`: VTT → plain transcript text (strip timecodes) → typed `exposition` chunk per video; Perseus JSON → `exercise_set` chunk (stem + hints) if in scope.
- Map Kolibri `grade_levels` / tree position → our `grade_band`.
- Khan alignment: embedding-only (Stage 5 Pass 2).
