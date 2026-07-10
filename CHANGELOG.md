# Changelog

All notable changes to OER MCP are documented here. Format follows [Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

## [1.1.0] — 2026-07-10

### Added
- **Multi-subject expansion:** Science and social studies content now available alongside math
  - Science: OpenStax Biology 2e, Biology AP Courses, Chemistry 2e, College Physics 2e, University Physics Volumes 1–3 (~4,600 chunks)
  - Social Studies: OpenStax American Government, US History, Psychology, Macro/Microeconomics AP Courses, Sociology, World History Volumes 1–2 (~5,200 chunks)
- **Multi-system query layer:** All tools now parametrized by `system` to support 12+ curriculum frameworks (CCSS, AP Biology, AP Chemistry, AP Physics 1/2/C Mechanics/C E&M, AP US Government, AP US History, AP Psychology, AP Macro/Microeconomics, AP World History, C3 Framework)
- **New curriculum systems:** Coverage extended beyond CCSS to include:
  - AP Courses: `ap-bio`, `ap-chem`, `ap-phys-1`, `ap-phys-2`, `ap-phys-c-mech`, `ap-phys-c-em`, `ap-us-gov`, `ap-us-history`, `ap-psych`, `ap-macro-econ`, `ap-micro-econ`, `ap-world-history`
  - Inquiry frameworks: `c3` (C3 Framework for Social Studies)
- **System-aware tools:** `check_coverage`, `get_learning_path`, and `fetch_for_standard` now accept optional `system` parameter to target specific curriculum frameworks
- `university-physics-volume-3` (modern/quantum physics) for completeness in the science curriculum

### Changed
- Query layer now **parametrized by standard system** — single tool invocation works across all 12+ frameworks
- Data partitioning expanded: `oer_ncsa.db` now holds science + social studies content (previously math add-ons only)
- Updated chunk counts: ~16,000 content + ~1,000 assessment chunks (up from 17,684 math-only)
- Updated alignment counts: ~55,000 alignments across all systems (up from 67,671 CCSS-only)
- `check_coverage` and `get_learning_path` now system-aware; can analyze gaps in any curriculum framework, not just CCSS

### Fixed
- ~~AP Biology publisher_guide extraction~~ Reverted as negative result: OpenStax biology-ap-courses' baked CNXML tags encode the retired 2012–2019 AP Biology framework, not the 2019+ Course & Exam Description used by StandardGraph. Framework-generation mismatch (0 of 139 IDs matched any SG ap-bio standard) made the 911 publisher_guide alignments unqueryable. Removed from `data/oer_ncsa.db`; biology-ap-courses content retained as embedding-aligned exposition.
- CNXML class-name matching now uses token-set membership instead of exact string equality, allowing multi-class elements (e.g., `class="summary ost-reading-discard"`)

### Deprecated
- None

### Removed
- 911 orphaned ap-bio publisher_guide alignment rows (framework-generation mismatch)

## [1.0.1] — 2026-07-04

### Added
- Assessment items now queryable via `map_to_assessments`: SAT, ACT, AP, NAEP, Smarter Balanced, state exams (NY Regents, MCAS)
- `exam_crosswalks` table and corresponding CLI tool for bulk loading CCSS ↔ exam domain mappings
- NY Regents (1,672 Algebra I/Geometry/Algebra II questions) + MCAS (366 grades 3-8, 10) released exam items
- AP free-response questions (85 FRQs: Calc AB/BC, Stats, Precalc, 2023-2026)
- Assessment-only columns: `item_type`, `dok_level`, `answer_key`, `exam_series`, `exam_year`, `difficulty`

### Changed
- Alignment confidence hierarchy refined: `human` > `publisher_guide` > `llm_verified` > `embedding`
- Coverage bands recalibrated for embedding scores (D20 checkpoint)

### Fixed
- Query-only server mode now detects and handles old DBs missing assessment columns gracefully

## [1.0.0] — 2026-06-28

### Added
- Initial public release: K–12 math content retrieval layer
- Eight MCP tools: `fetch_for_standard`, `search_content`, `get_chunk`, `check_coverage`, `list_sources`, `map_to_assessments`, `get_learning_path`, `get_capabilities`
- Four license-partitioned databases:
  - `oer_core.db`: CC BY / public domain (OpenStax 13 math books, Illustrative Mathematics K–12, Smarter Balanced, NAEP)
  - `oer_ncsa.db`: CC BY-NC-SA (Khan Academy transcripts, OpenMiddle)
  - `oer_state.db`: State copyright (NY Regents, MCAS)
  - `oer_ap.db`: College Board copyright (AP free-response)
- 17,684 content chunks across math
- 47,880 CCSS standard alignments (core DB)
- 486 distinct CCSS standards covered
- Hybrid semantic + FTS5 keyword search (degrades gracefully)
- Pre-built database download via install script
- FastMCP stdio server for Claude Desktop integration
- Full ingestion pipeline (fetch → chunk → embed → align → verify → annotate → validate)

---

**Format notes:**
- Versions follow [Semantic Versioning](https://semver.org)
- Date format: YYYY-MM-DD (ISO 8601)
- Sections per [Keep a Changelog](https://keepachangelog.com): Added, Changed, Deprecated, Removed, Fixed, Security
