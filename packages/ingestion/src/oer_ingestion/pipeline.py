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

from .adapters import BookSpec, OpenStaxAdapter
from .align import align_chunks
from .embed import embed_chunks
from .load import load_catalog, load_chunks, record_run, write_snapshots

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


def run_embed_align(db_path: Path, sg_db: Path) -> None:
    """Stages 4–5: embed chunks, then align to CCSS. Needs Ollama + SG DB."""
    conn = connect(db_path, create=True)
    embed_chunks(conn)
    align_chunks(conn, sg_db)
    conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description="OER ingestion pipeline")
    p.add_argument("source", choices=["openstax", "embed-align"])
    p.add_argument("--book", action="append", dest="books",
                   help="book slug (repeatable); default: prealgebra-2e")
    p.add_argument("--db", default=str(config.CORE_DB_PATH))
    p.add_argument("--snapshots", default=str(config.DATA_DIR / "raw" / "snapshots"))
    p.add_argument("--sg-db", default=str(config.STANDARDGRAPH_DB_PATH),
                   help="StandardGraph DB (build-time only, for alignment)")
    args = p.parse_args()

    books = args.books or ["prealgebra-2e"]
    if args.source == "openstax":
        run_openstax(books, Path(args.db), Path(args.snapshots))
    elif args.source == "embed-align":
        run_embed_align(Path(args.db), Path(args.sg_db))


if __name__ == "__main__":
    main()
