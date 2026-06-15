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

from .adapters import BookSpec, KhanAcademyAdapter, OpenStaxAdapter
from .align import align_chunks
from .annotate import annotate
from .embed import embed_chunks
from .load import load_catalog, load_chunks, record_run, write_snapshots
from .validate_db import print_report, validate

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
}


def run_openstax(slugs: list[str], db_path: Path, snapshot_root: Path) -> None:
    specs = [OPENSTAX_BOOKS[s] for s in slugs]
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


def run_embed_align(db_path: Path, sg_db: Path) -> None:
    """Stages 4–5: embed chunks, then align to CCSS. Needs Ollama + SG DB."""
    conn = connect(db_path, create=True)
    embed_chunks(conn)
    align_chunks(conn, sg_db)
    conn.close()


def run_annotate(
    db_path: Path, sg_db: Path, limit: int | None = None,
    shard: tuple[int, int] | None = None,
) -> None:
    """Stage 6: gemma coverage notes for flagged alignments. Needs Ollama + SG DB."""
    conn = connect(db_path, create=True)
    annotate(conn, sg_db, limit=limit, shard=shard)
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
    p.add_argument("source", choices=["openstax", "khan", "embed-align", "annotate", "validate"])
    p.add_argument("--book", action="append", dest="books",
                   help="book slug (repeatable); default: prealgebra-2e. 'all' = full catalog")
    p.add_argument("--db", default=str(config.CORE_DB_PATH))
    p.add_argument("--snapshots", default=str(config.DATA_DIR / "raw" / "snapshots"))
    p.add_argument("--sg-db", default=str(config.STANDARDGRAPH_DB_PATH),
                   help="StandardGraph DB (build-time only, for alignment/annotate)")
    p.add_argument("--limit", type=int, default=None, help="cap (annotate)")
    p.add_argument("--shard", default=None,
                   help="annotate work split 'N/M' — process rows where id %% M == N")
    p.add_argument("--channel-db", default=KHAN_CHANNEL_DEFAULT,
                   help="Khan Kolibri channel sqlite3 path")
    p.add_argument("--max-videos", type=int, default=None, help="cap (khan)")
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
    elif args.source == "embed-align":
        run_embed_align(Path(args.db), Path(args.sg_db))
    elif args.source == "annotate":
        run_annotate(Path(args.db), Path(args.sg_db), args.limit, shard)
    elif args.source == "validate":
        run_validate(Path(args.db))


if __name__ == "__main__":
    main()
