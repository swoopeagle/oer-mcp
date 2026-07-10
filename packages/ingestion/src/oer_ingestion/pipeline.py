"""Ingestion pipeline entry point.

M1 scope: Stages 1–3 (fetch → snapshot → chunk → load) for OpenStax. These
need no Ollama. Stages 4–6 (embed, align, annotate) land once the Mac Studio
inference link is free; they are wired as separate, re-runnable stages.

Usage:
    uv run python -m oer_ingestion.pipeline openstax --book prealgebra-2e
"""

from __future__ import annotations

import argparse
from pathlib import Path

from oer_shared import config
from oer_shared.db import connect

from .adapters import APFRQAdapter, BookSpec, KhanAcademyAdapter, MCASAdapter, NAEPAdapter, OpenMiddleAdapter, OpenStaxAdapter, RegentsAdapter, SmarterBalancedAdapter
from .adapters.illustrative_math import IllustrativeMathAdapter
from .align import align_chunks
from .annotate import annotate
from .crosswalk import load_crosswalks
from .embed import embed_chunks
from .load import load_alignments, load_catalog, load_chunks, record_run, write_snapshots
from .migrate import migrate_alignment_source_check, migrate_assessment_columns
from .validate_db import print_report, validate
from .verify import verify

# Phase 1 OpenStax math catalog (S1). grade_band is coarse; per-chunk
# refinement is a later concern.
OPENSTAX_BOOKS = {
    "prealgebra-2e": BookSpec("osbooks-prealgebra-bundle", "prealgebra-2e", "6-8"),
    "elementary-algebra-2e": BookSpec("osbooks-prealgebra-bundle", "elementary-algebra-2e", "9-12"),
    "intermediate-algebra-2e": BookSpec("osbooks-prealgebra-bundle", "intermediate-algebra-2e", "9-12"),
    "algebra-1": BookSpec("osbooks-algebra-1", "algebra-1", "9-12"),
    "college-algebra-2e": BookSpec("osbooks-college-algebra-bundle", "college-algebra-2e", "college"),
    "precalculus-2e": BookSpec("osbooks-college-algebra-bundle", "precalculus-2e", "college"),
    "calculus-volume-1": BookSpec("osbooks-calculus-bundle", "calculus-volume-1", "college"),
    "statistics": BookSpec("osbooks-statistics", "statistics", "9-12"),
    # Expansion (all CC BY-NC-SA → oer_ncsa.db). Slugs/licenses verified 2026-06-22.
    "algebra-and-trigonometry-2e": BookSpec("osbooks-college-algebra-bundle", "algebra-and-trigonometry-2e", "9-12"),
    "college-algebra-corequisite-support-2e": BookSpec("osbooks-college-algebra-bundle", "college-algebra-corequisite-support-2e", "college"),
    "contemporary-mathematics": BookSpec("osbooks-contemporary-mathematics", "contemporary-mathematics", "9-12"),
    "calculus-volume-2": BookSpec("osbooks-calculus-bundle", "calculus-volume-2", "college"),
    "calculus-volume-3": BookSpec("osbooks-calculus-bundle", "calculus-volume-3", "college"),
}

# Books added in the expansion pass — used by scripts to target just the new set.
EXPANSION_BOOKS = [
    "algebra-and-trigonometry-2e", "college-algebra-corequisite-support-2e",
    "contemporary-mathematics", "calculus-volume-2", "calculus-volume-3",
]

# Social-studies pilot (D22): all CC BY-NC-SA → oer_ncsa.db, same tier as Khan/
# OpenMiddle. Slugs/licenses verified 2026-07-10 against collection.xml on GitHub.
SOCIAL_STUDIES_BOOKS = {
    "american-government-4e": BookSpec(
        "osbooks-american-government", "american-government-4e", "9-12",
        subject="social-studies", class_profile="social-studies",
    ),
}


ALL_OPENSTAX_BOOKS = {**OPENSTAX_BOOKS, **SOCIAL_STUDIES_BOOKS}


def run_openstax(slugs: list[str], db_path: Path, snapshot_root: Path) -> None:
    specs = [ALL_OPENSTAX_BOOKS[s] for s in slugs]
    adapter = OpenStaxAdapter(specs)

    print(f"[fetch] {len(specs)} book(s): {', '.join(slugs)}")
    raw = adapter.fetch()
    print(f"[fetch] {len(raw)} modules")

    snaps = write_snapshots(raw, snapshot_root)
    print(f"[snapshot] wrote {len(snaps)} raw files → {snapshot_root}")

    chunks = adapter.parse(raw)
    result = adapter.validate(chunks)
    print(f"[chunk] {result.stats}")
    if not result.ok:
        raise SystemExit(f"[chunk] validation failed: {result.errors[:5]}")
    for w in result.warnings:
        print(f"[chunk][warn] {w}")

    conn = connect(db_path, create=True)
    load_catalog(conn, adapter.catalog())
    counts = load_chunks(conn, chunks, snapshot_paths=snaps)
    record_run(conn, adapter.source_id, counts, warnings=result.warnings)
    total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print(f"[load] added={counts['added']} updated={counts['updated']} | db total={total}")
    conn.close()


KHAN_CHANNEL_DEFAULT = str(config.DATA_DIR / "khan_channel.sqlite3")


def run_khan(db_path: Path, snapshot_root: Path, channel_db: str,
             max_videos: int | None = None) -> None:
    """Ingest Khan video transcripts (Kolibri, D16) into the NC-SA database.
    CC BY-NC-SA content lives in its own DB per the D11 license split."""
    adapter = KhanAcademyAdapter(channel_db, max_videos=max_videos)
    print(f"[fetch] Khan transcripts from {channel_db}")
    raw = adapter.fetch()
    print(f"[fetch] {len(raw)} transcripts")
    snaps = write_snapshots(raw, snapshot_root, ext="vtt")
    print(f"[snapshot] wrote {len(snaps)} VTT files")
    chunks = adapter.parse(raw)
    result = adapter.validate(chunks)
    print(f"[chunk] {result.stats}")
    if not result.ok:
        raise SystemExit(f"[chunk] validation failed: {result.errors[:5]}")
    conn = connect(db_path, create=True)
    load_catalog(conn, adapter.catalog())
    counts = load_chunks(conn, chunks)
    record_run(conn, adapter.source_id, counts, warnings=result.warnings)
    total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print(f"[load] added={counts['added']} updated={counts['updated']} | db total={total}")
    conn.close()


def run_open_middle(db_path: Path, snapshot_root: Path,
                    max_problems: int | None = None) -> None:
    """Ingest OpenMiddle DOK-3 problems (CC BY-NC-SA) into the NC-SA database."""
    adapter = OpenMiddleAdapter(max_problems=max_problems)
    print(f"[fetch] OpenMiddle (max_problems={max_problems})")
    raw = adapter.fetch()
    print(f"[fetch] {len(raw)} problems")
    snaps = write_snapshots(raw, snapshot_root, ext="html")
    print(f"[snapshot] wrote {len(snaps)} HTML files")
    chunks = adapter.parse(raw)
    result = adapter.validate(chunks)
    print(f"[chunk] {result.stats}")
    if not result.ok:
        raise SystemExit(f"[chunk] validation failed: {result.errors[:5]}")
    conn = connect(db_path, create=True)
    load_catalog(conn, adapter.catalog())
    counts = load_chunks(conn, chunks)
    acounts = load_alignments(conn, chunks)
    record_run(conn, adapter.source_id, counts, warnings=[])
    total = conn.execute("SELECT COUNT(*) FROM chunks WHERE source_id='open-middle'").fetchone()[0]
    print(f"[load] added={counts['added']} updated={counts['updated']} | "
          f"publisher alignments={acounts['added']} | total open-middle={total}")
    conn.close()


def run_im(db_path: Path, snapshot_root: Path, courses: list[str] | None = None,
           max_lessons: int | None = None, path_family: str = "ms") -> None:
    """Ingest Illustrative Mathematics (First Edition, CC BY 4.0) into the
    *core* DB. Supports path_family: 'ms' (6-8), 'k5' (K-5), 'hs' (9-12).
    Each lesson's "Addressing" CCSS standards load as publisher_guide alignments."""
    adapter = IllustrativeMathAdapter(courses=courses, max_lessons=max_lessons,
                                     path_family=path_family)
    label = {"k5": "K-5", "ms": "6-8", "hs": "HS"}[path_family]
    print(f"[fetch] IM {label} crawl (courses={adapter.courses}, max_lessons={max_lessons})")
    raw = adapter.fetch()
    print(f"[fetch] {len(raw)} lessons")
    snaps = write_snapshots(raw, snapshot_root, ext="html")
    print(f"[snapshot] wrote {len(snaps)} HTML files")
    chunks = adapter.parse(raw)
    result = adapter.validate(chunks)
    print(f"[chunk] {result.stats}")
    if not result.ok:
        raise SystemExit(f"[chunk] validation failed: {result.errors[:5]}")
    for w in result.warnings:
        print(f"[chunk][warn] {w}")
    conn = connect(db_path, create=True)
    load_catalog(conn, adapter.catalog())
    counts = load_chunks(conn, chunks)
    acounts = load_alignments(conn, chunks)
    record_run(conn, adapter.source_id, counts, warnings=result.warnings)
    total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    pub = conn.execute("SELECT COUNT(*) FROM standard_alignments "
                       "WHERE alignment_source='publisher_guide'").fetchone()[0]
    print(f"[load] chunks added={counts['added']} updated={counts['updated']} | "
          f"publisher alignments added={acounts['added']} updated={acounts['updated']} "
          f"| db total chunks={total}, publisher_guide={pub}")
    conn.close()


def run_smarter_balanced(db_path: Path, snapshot_root: Path,
                         grades: list[int] | None = None,
                         max_items: int | None = None) -> None:
    """Ingest SBAC sample items (CC BY) into the core DB."""
    adapter = SmarterBalancedAdapter(grades=grades, max_items=max_items)
    print(f"[fetch] Smarter Balanced (grades={adapter.grades})")
    raw = adapter.fetch()
    print(f"[fetch] {len(raw)} items")
    chunks = adapter.parse(raw)
    result = adapter.validate(chunks)
    print(f"[chunk] {result.stats}")
    if not result.ok:
        raise SystemExit(f"[chunk] validation failed: {result.errors[:5]}")
    conn = connect(db_path, create=True)
    migrate_assessment_columns(conn)
    load_catalog(conn, adapter.catalog())
    counts = load_chunks(conn, chunks)
    acounts = load_alignments(conn, chunks)
    record_run(conn, adapter.source_id, counts)
    total = conn.execute("SELECT COUNT(*) FROM chunks WHERE content_type='assessment'").fetchone()[0]
    print(f"[load] added={counts['added']} updated={counts['updated']} | "
          f"pub alignments={acounts['added']} | total assessment chunks={total}")
    conn.close()


def run_naep(db_path: Path, snapshot_root: Path,
             grades: list[int] | None = None,
             max_items: int | None = None) -> None:
    """Ingest NAEP released items (public domain) into the core DB."""
    adapter = NAEPAdapter(grades=grades, max_items=max_items)
    print(f"[fetch] NAEP (grades={adapter.grades})")
    raw = adapter.fetch()
    print(f"[fetch] {len(raw)} items")
    chunks = adapter.parse(raw)
    result = adapter.validate(chunks)
    print(f"[chunk] {result.stats}")
    if not result.ok:
        raise SystemExit(f"[chunk] validation failed: {result.errors[:5]}")
    conn = connect(db_path, create=True)
    migrate_assessment_columns(conn)
    load_catalog(conn, adapter.catalog())
    counts = load_chunks(conn, chunks)
    record_run(conn, adapter.source_id, counts)
    total = conn.execute("SELECT COUNT(*) FROM chunks WHERE content_type='assessment'").fetchone()[0]
    print(f"[load] added={counts['added']} updated={counts['updated']} | total assessment={total}")
    conn.close()


def run_ap_frq(db_path: Path, snapshot_root: Path,
               subjects: list[str] | None = None,
               years: list[int] | None = None) -> None:
    """Ingest AP free-response questions into the AP DB (oer_ap.db)."""
    adapter = APFRQAdapter(subjects=subjects, years=years)
    print(f"[fetch] AP FRQ (subjects={adapter.subjects}, years={adapter.years})")
    raw = adapter.fetch()
    print(f"[fetch] {len(raw)} PDFs")
    chunks = adapter.parse(raw)
    result = adapter.validate(chunks)
    print(f"[chunk] {result.stats}")
    if not result.ok:
        raise SystemExit(f"[chunk] validation failed: {result.errors[:5]}")
    conn = connect(db_path, create=True)
    migrate_assessment_columns(conn)
    load_catalog(conn, adapter.catalog())
    counts = load_chunks(conn, chunks)
    record_run(conn, adapter.source_id, counts)
    total = conn.execute("SELECT COUNT(*) FROM chunks WHERE content_type='assessment'").fetchone()[0]
    print(f"[load] added={counts['added']} updated={counts['updated']} | total assessment={total}")
    conn.close()


def run_regents(db_path: Path, snapshot_root: Path,
                courses: list[str] | None = None,
                years: list[int] | None = None,
                max_exams: int | None = None) -> None:
    """Ingest NY Regents released exams into the state DB (oer_state.db)."""
    adapter = RegentsAdapter(courses=courses, years=years, max_exams=max_exams)
    print(f"[fetch] Regents (courses={adapter.courses}, years={adapter.years[0]}-{adapter.years[-1]})")
    raw = adapter.fetch()
    print(f"[fetch] {len(raw)} exams")
    chunks = adapter.parse(raw)
    result = adapter.validate(chunks)
    print(f"[chunk] {result.stats}")
    if not result.ok:
        raise SystemExit(f"[chunk] validation failed: {result.errors[:5]}")
    for w in result.warnings:
        print(f"[chunk][warn] {w}")
    conn = connect(db_path, create=True)
    migrate_assessment_columns(conn)
    load_catalog(conn, adapter.catalog())
    counts = load_chunks(conn, chunks)
    record_run(conn, adapter.source_id, counts, warnings=result.warnings)
    total = conn.execute("SELECT COUNT(*) FROM chunks WHERE content_type='assessment'").fetchone()[0]
    print(f"[load] added={counts['added']} updated={counts['updated']} | total assessment={total}")
    conn.close()


def run_mcas(db_path: Path, snapshot_root: Path,
             grades: list[str] | None = None,
             max_items: int | None = None) -> None:
    """Ingest MCAS released items into the state DB (oer_state.db)."""
    adapter = MCASAdapter(grades=grades, max_items=max_items)
    print(f"[fetch] MCAS (grades={adapter.grades})")
    raw = adapter.fetch()
    print(f"[fetch] {len(raw)} items")
    chunks = adapter.parse(raw)
    result = adapter.validate(chunks)
    print(f"[chunk] {result.stats}")
    if not result.ok:
        raise SystemExit(f"[chunk] validation failed: {result.errors[:5]}")
    for w in result.warnings:
        print(f"[chunk][warn] {w}")
    conn = connect(db_path, create=True)
    migrate_assessment_columns(conn)
    load_catalog(conn, adapter.catalog())
    counts = load_chunks(conn, chunks)
    acounts = load_alignments(conn, chunks)
    record_run(conn, adapter.source_id, counts, warnings=result.warnings)
    total = conn.execute("SELECT COUNT(*) FROM chunks WHERE content_type='assessment'").fetchone()[0]
    print(f"[load] added={counts['added']} updated={counts['updated']} | "
          f"pub alignments={acounts['added']} | total assessment={total}")
    conn.close()


def run_crosswalks(db_path: Path, crosswalk_file: Path | None = None) -> None:
    """Load exam crosswalk data (standard → exam domain) into the core DB."""
    from pathlib import Path as _Path
    _DEFAULT = _Path(__file__).parent / "data" / "exam_crosswalks.json"
    file = crosswalk_file or _DEFAULT
    conn = connect(db_path, create=True)
    migrate_assessment_columns(conn)
    counts = load_crosswalks(conn, file)
    conn.close()
    print(f"[crosswalk] loaded from {file}: added={counts['added']} updated={counts['updated']}")


def run_style_gen_pipeline(db_path: Path, sg_db: Path,
                           style: str = "sat",
                           limit: int | None = None,
                           shard: tuple[int, int] | None = None) -> None:
    """Generate SAT/ACT-style items for all standards not yet covered."""
    # Lazy import: style_gen depends on the gemma OllamaClient path, which is
    # separately broken (imports a since-removed class). Keeping it out of the
    # module top level means the other subcommands (embed-align, verify, …) work.
    from .style_gen import run_style_gen

    conn = connect(db_path, create=True)
    migrate_assessment_columns(conn)
    run_style_gen(conn, str(sg_db), style=style, limit=limit, shard=shard)  # type: ignore[arg-type]
    conn.close()


def run_migrate(db_path: Path) -> None:
    """Run all pending schema migrations on an existing DB (idempotent)."""
    conn = connect(db_path, create=False)
    did_align = migrate_alignment_source_check(conn)
    did_assess = migrate_assessment_columns(conn)
    conn.close()
    print(f"[migrate] alignment_source CHECK: {'migrated' if did_align else 'already current'}")
    print(f"[migrate] assessment columns: {'migrated' if did_assess else 'already current'}")


def run_embed_align(db_path: Path, sg_db: Path, system: str = "ccss") -> None:
    """Stages 4–5: embed chunks, then align to a StandardGraph system (default
    CCSS math). Needs Ollama + SG DB."""
    conn = connect(db_path, create=True)
    embed_chunks(conn)
    align_chunks(conn, sg_db, system=system)
    conn.close()


def run_annotate(
    db_path: Path, sg_db: Path, limit: int | None = None,
    shard: tuple[int, int] | None = None,
) -> None:
    """Stage 6: gemma coverage notes for flagged alignments. Needs Ollama + SG DB."""
    conn = connect(db_path, create=True)
    annotate(conn, sg_db, limit=limit, shard=shard)
    conn.close()


def run_verify(db_path: Path, sg_db: Path, limit: int | None = None,
               shard: tuple[int, int] | None = None) -> None:
    """Stage 6b: gemma-verified alignment upgrade (D20). Migrates the CHECK
    constraint first. Needs Ollama + SG DB."""
    conn = connect(db_path, create=True)
    if migrate_alignment_source_check(conn):
        print("[migrate] expanded alignment_source CHECK for llm_verified")
    verify(conn, sg_db, limit=limit, shard=shard)
    conn.close()


def run_validate(db_path: Path) -> None:
    """Stage 7: acceptance validation. GPU-free."""
    conn = connect(db_path, create=True)
    report = validate(conn)
    print_report(report)
    conn.close()
    if not report.passed:
        raise SystemExit(1)


def main() -> None:
    p = argparse.ArgumentParser(description="OER ingestion pipeline")
    p.add_argument("source", choices=[
        "openstax", "khan", "im", "im-k5", "im-hs", "open-middle",
        "smarter-balanced", "naep", "ap-frq", "regents", "mcas",
        "crosswalks", "style-gen",
        "embed-align", "annotate", "verify", "validate", "migrate",
    ])
    p.add_argument("--book", action="append", dest="books",
                   help="book slug (repeatable); default: prealgebra-2e. 'all' = full catalog")
    p.add_argument("--db", default=str(config.CORE_DB_PATH))
    p.add_argument("--snapshots", default=str(config.DATA_DIR / "raw" / "snapshots"))
    p.add_argument("--sg-db", default=str(config.STANDARDGRAPH_DB_PATH),
                   help="StandardGraph DB (build-time only, for alignment/annotate)")
    p.add_argument("--system", default="ccss",
                   help="StandardGraph standard system to align against (embed-align); "
                        "e.g. 'ccss' (default, math) or 'ap-us-gov' (social studies)")
    p.add_argument("--limit", type=int, default=None, help="cap (annotate)")
    p.add_argument("--shard", default=None,
                   help="annotate work split 'N/M' — process rows where id %% M == N")
    p.add_argument("--channel-db", default=KHAN_CHANNEL_DEFAULT,
                   help="Khan Kolibri channel sqlite3 path")
    p.add_argument("--max-videos", type=int, default=None, help="cap (khan)")
    p.add_argument("--course", action="append", dest="courses",
                   help="IM MS course (repeatable): 1=Gr6, 2=Gr7, 3=Gr8; default all")
    p.add_argument("--max-lessons", type=int, default=None, help="cap (im)")
    p.add_argument("--grade", type=int, action="append", dest="grades",
                   help="grade filter (smarter-balanced, naep; repeatable)")
    p.add_argument("--subject", action="append", dest="subjects",
                   help="AP subject slug (ap-frq; repeatable)")
    p.add_argument("--year", type=int, action="append", dest="years",
                   help="year filter (ap-frq; repeatable)")
    p.add_argument("--max-items", type=int, default=None, help="cap (smarter-balanced, naep)")
    p.add_argument("--regents-course", action="append", dest="regents_courses",
                   help="Regents course (repeatable): algebra-i, geometry, algebra-ii; default all")
    p.add_argument("--crosswalk-file", default=None,
                   help="crosswalk JSON file (crosswalks; default: built-in seed)")
    p.add_argument("--style", choices=["sat", "act"], default="sat",
                   help="exam style (style-gen)")
    args = p.parse_args()

    shard = None
    if args.shard:
        n, m = (int(x) for x in args.shard.split("/"))
        shard = (n, m)

    books = args.books or ["prealgebra-2e"]
    if books == ["all"]:
        books = list(OPENSTAX_BOOKS)
    if args.source == "openstax":
        run_openstax(books, Path(args.db), Path(args.snapshots))
    elif args.source == "khan":
        run_khan(Path(args.db), Path(args.snapshots), args.channel_db, args.max_videos)
    elif args.source == "im":
        run_im(Path(args.db), Path(args.snapshots), args.courses, args.max_lessons,
               path_family="ms")
    elif args.source == "im-k5":
        run_im(Path(args.db), Path(args.snapshots), args.courses, args.max_lessons,
               path_family="k5")
    elif args.source == "im-hs":
        run_im(Path(args.db), Path(args.snapshots), args.courses, args.max_lessons,
               path_family="hs")
    elif args.source == "open-middle":
        run_open_middle(Path(args.db), Path(args.snapshots), args.max_items)
    elif args.source == "smarter-balanced":
        run_smarter_balanced(Path(args.db), Path(args.snapshots),
                             grades=args.grades, max_items=args.max_items)
    elif args.source == "naep":
        run_naep(Path(args.db), Path(args.snapshots),
                 grades=args.grades, max_items=args.max_items)
    elif args.source == "ap-frq":
        run_ap_frq(Path(args.db), Path(args.snapshots),
                   subjects=args.subjects, years=args.years)
    elif args.source == "regents":
        run_regents(Path(args.db), Path(args.snapshots),
                    courses=args.regents_courses, years=args.years,
                    max_exams=args.max_items)
    elif args.source == "mcas":
        run_mcas(Path(args.db), Path(args.snapshots),
                 grades=[str(g) for g in args.grades] if args.grades else None,
                 max_items=args.max_items)
    elif args.source == "crosswalks":
        run_crosswalks(Path(args.db),
                       Path(args.crosswalk_file) if args.crosswalk_file else None)
    elif args.source == "style-gen":
        run_style_gen_pipeline(Path(args.db), Path(args.sg_db),
                               style=args.style, limit=args.limit, shard=shard)
    elif args.source == "migrate":
        run_migrate(Path(args.db))
    elif args.source == "embed-align":
        run_embed_align(Path(args.db), Path(args.sg_db), system=args.system)
    elif args.source == "annotate":
        run_annotate(Path(args.db), Path(args.sg_db), args.limit, shard)
    elif args.source == "verify":
        run_verify(Path(args.db), Path(args.sg_db), args.limit, shard)
    elif args.source == "validate":
        run_validate(Path(args.db))


if __name__ == "__main__":
    main()
