#!/usr/bin/env python3
"""
Performance benchmarking: measure query speed (ideally before/after index optimization).

Current indexes in place:
- idx_chunks_source_stale (added)
- idx_chunks_grade_stale (added)
- idx_alignments_score (existing)
- idx_alignments_standard (existing)
"""

import sqlite3
import time
from pathlib import Path


def benchmark_query(conn: sqlite3.Connection, query: str, params: tuple = (), runs: int = 10) -> dict:
    """Run a query multiple times and measure performance."""
    times = []
    for _ in range(runs):
        start = time.time()
        conn.execute(query, params).fetchall()
        elapsed = (time.time() - start) * 1000  # ms
        times.append(elapsed)

    return {
        "mean": sum(times) / len(times),
        "min": min(times),
        "max": max(times),
        "runs": runs,
    }


def run_benchmarks(db_path: str):
    """Run performance benchmarks."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("="*70)
    print("PERFORMANCE BENCHMARKS")
    print("="*70)

    benchmarks = [
        (
            "Fetch content for standard (no filters)",
            """SELECT c.id, c.title, a.alignment_score, a.alignment_source
               FROM standard_alignments a
               JOIN chunks c ON c.id = a.chunk_id
               WHERE a.standard_id = ? AND a.stale = 0 AND c.stale = 0
               ORDER BY a.alignment_score DESC
               LIMIT 5""",
            ("CCSS.MATH.6.RP.3",),
        ),
        (
            "Fetch with source filter (uses idx_chunks_source_stale)",
            """SELECT c.id, c.title, a.alignment_score
               FROM standard_alignments a
               JOIN chunks c ON c.id = a.chunk_id
               WHERE a.standard_id = ? AND a.stale = 0 AND c.stale = 0
               AND c.source_id = ?
               ORDER BY a.alignment_score DESC
               LIMIT 5""",
            ("CCSS.MATH.6.RP.3", "openstax"),
        ),
        (
            "Fetch with grade filter (uses idx_chunks_grade_stale)",
            """SELECT c.id, c.title, a.alignment_score
               FROM standard_alignments a
               JOIN chunks c ON c.id = a.chunk_id
               WHERE a.standard_id = ? AND a.stale = 0 AND c.stale = 0
               AND c.grade_band = ?
               ORDER BY a.alignment_score DESC
               LIMIT 5""",
            ("CCSS.MATH.6.RP.3", "6-8"),
        ),
        (
            "Search content (FTS5 on title/content)",
            """SELECT c.id FROM chunks_fts f
               JOIN chunks c ON c.rowid = f.rowid
               WHERE f.chunks_fts MATCH ?
               ORDER BY bm25(f.chunks_fts) ASC
               LIMIT 50""",
            ('"fractions"',),
        ),
        (
            "Check coverage (count alignments per standard)",
            """SELECT a.standard_id, COUNT(*) as count
               FROM standard_alignments a
               WHERE a.standard_id LIKE ? AND a.stale = 0
               GROUP BY a.standard_id""",
            ("CCSS.MATH.6%",),
        ),
        (
            "List sources (full inventory)",
            """SELECT DISTINCT s.id, COUNT(DISTINCT c.id) as chunks
               FROM sources s
               LEFT JOIN books b ON b.source_id = s.id
               LEFT JOIN chunks c ON c.book_id = b.id AND c.stale = 0
               GROUP BY s.id""",
            (),
        ),
    ]

    results = {}
    for name, query, params in benchmarks:
        result = benchmark_query(conn, query, params, runs=10)
        results[name] = result
        print(f"\n{name}")
        print(f"  Mean: {result['mean']:.2f}ms | Min: {result['min']:.2f}ms | Max: {result['max']:.2f}ms")

    # ─── Index Analysis ──────────────────────────────────────────────

    print("\n" + "="*70)
    print("INDEX ANALYSIS")
    print("="*70)

    print("\nChunks Table Indexes:")
    indexes = conn.execute(
        "SELECT name, type, tbl_name FROM sqlite_master WHERE type='index' AND tbl_name='chunks'"
    ).fetchall()
    for idx in indexes:
        print(f"  {idx['name']:35} ({idx['type']})")

    print("\nStandard Alignments Table Indexes:")
    indexes = conn.execute(
        "SELECT name, type, tbl_name FROM sqlite_master WHERE type='index' AND tbl_name='standard_alignments'"
    ).fetchall()
    for idx in indexes:
        print(f"  {idx['name']:35} ({idx['type']})")

    # ─── Table Stats ────────────────────────────────────────────────

    print("\n" + "="*70)
    print("TABLE STATISTICS")
    print("="*70)

    stats = conn.execute("""
        SELECT
          'chunks' as table_name,
          COUNT(*) as row_count,
          ROUND(page_count * page_size / 1024.0 / 1024, 2) as size_mb
        FROM pragma_page_count(), pragma_page_size()
    """).fetchone()
    print(f"\nChunks Table:")
    print(f"  Row count:  {stats['row_count']:,}")

    stats = conn.execute("""
        SELECT COUNT(*) as row_count FROM standard_alignments
    """).fetchone()
    print(f"\nStandard Alignments Table:")
    print(f"  Row count:  {stats['row_count']:,}")

    conn.close()

    print("\n" + "="*70)
    print("BENCHMARKS COMPLETE")
    print("="*70)

    return results


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Performance benchmarking")
    p.add_argument("--db", default="data/oer_core.db")
    args = p.parse_args()

    run_benchmarks(args.db)
