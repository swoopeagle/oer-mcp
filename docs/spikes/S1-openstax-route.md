# Spike S1 — OpenStax content route
**Date:** 2026-06-09 · **Verdict: GO — `osbooks-*` GitHub CNXML repos**

## Decision
Ingest OpenStax from the `github.com/openstax/osbooks-*` repos (raw.githubusercontent.com, `main` branch). The REX page JSON route was not needed: the CNXML source is complete, structured, versioned, and rate-limit-free.

## Verified structure
```
osbooks-{bundle}/
├── META-INF/books.xml            ← lists book slugs + collection hrefs (bundles hold 1–4 books)
├── collections/{slug}.collection.xml  ← book → subcollection (chapter) → col:module refs; md:license here
├── modules/{mNNNNN}/index.cnxml  ← one section per module; shared across books in a bundle
└── media/                        ← images referenced by relative path
```
- `collection.xml` gives the full book tree: `md:title` per subcollection (chapter), `col:module document="m81284"` per section. Prealgebra 2e = 75 modules.
- Module CNXML is richly semantic — verified on m81285 (Visualize Fractions, 1720 lines): `<example>` (18), `<exercise>` (132) each with `<problem>`/`<solution>`, `<note>` with classes (`be-prepared`, `howto`, `key-concepts`, `section-exercises`), `<equation>`, MathML (`m:math`). **The D14 typed sub-chunk splitter has clean element-level handles; no heuristic text splitting needed.**
- Module metadata has `md:content-id` + `md:uuid` → stable chunk ID prefixes.

## Math catalog (verified June 2026)
| Bundle repo | Books | License |
|---|---|---|
| osbooks-prealgebra-bundle | prealgebra-2e, elementary-algebra-2e, intermediate-algebra-2e | **CC BY-NC-SA** |
| osbooks-college-algebra-bundle | college-algebra-2e, precalculus-2e, algebra-and-trigonometry-2e, college-algebra-corequisite-support-2e | **CC BY-NC-SA** |
| osbooks-calculus-bundle | calculus-volume-1/2/3 | **CC BY-NC-SA** |
| osbooks-introductory-statistics-bundle | introductory-statistics-2e, introductory-business-statistics-2e | **CC BY-NC-SA** |
| osbooks-statistics | statistics (HS Statistics) | **CC BY** |
| osbooks-contemporary-mathematics | contemporary-mathematics | **CC BY-NC-SA** |
| osbooks-algebra-1 | algebra-1 (HS, based on Illustrative Mathematics) | **CC BY-NC-SA** |

## ⚠️ Licensing finding (changes PRD assumption)
The PRD assumed OpenStax = CC BY 4.0. In fact **OpenStax relicensed 2e/newer editions to CC BY-NC-SA; only first editions remain CC BY** (confirmed via the OpenStax CMS API `openstax.org/apps/cms/api/v2/pages?type=books.Book&fields=title,license_name`: e.g. College Algebra 1e = CC BY, College Algebra 2e = CC BY-NC-SA).

Consequences:
1. The D11 two-DB split must partition **by license, not by source**. Most current OpenStax math joins Khan in the NC-SA database.
2. The "core CC BY DB" as planned would contain only HS Statistics (+ CK-12 later, which is CC BY).
3. Open question for the owner: index current 2e editions (what students actually use → NC-SA DB) vs CC BY 1e editions (commercially clean, but superseded content, and 1e availability on GitHub is unverified). Recommendation: 2e — grounding in what students actually read is the project's whole premise.
4. License must be read per-book from `collection.xml` `md:license` at ingestion time, never assumed per source.

## Implementation notes for the adapter
- Fetch: `META-INF/books.xml` → collections → modules; one HTTP GET per module file via raw.githubusercontent.com (or one tarball per repo via `codeload` — preferred, single request, snapshot-friendly).
- Parse: lxml; namespaces `http://cnx.rice.edu/cnxml`, `http://cnx.rice.edu/collxml`, `http://cnx.rice.edu/mdml`, MathML.
- MathML → LaTeX conversion needed for chunk text (PRD: "preserve math in LaTeX").
- Chunk IDs: `openstax-{slug}-{module_id}-{type}{n}` (module IDs are stable; chapter/section numbers derived from collection tree).
