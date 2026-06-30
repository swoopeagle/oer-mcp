#!/usr/bin/env python3
"""
Deep data quality audit: alignment distribution, outliers, coverage gaps, source quality.

Analyzes:
1. Alignment distribution by grade level
2. Coverage by standard (which standards are well/poorly covered)
3. Outliers and suspicious alignments
4. Quality comparison by source
5. Gap analysis (zero/weak coverage standards)
"""

import sqlite3
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm


def analyze_alignment_data(db_path: str, sg_db_path: str):
    """Run comprehensive alignment quality audit."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sg_conn = sqlite3.connect(f"file:{sg_db_path}?mode=ro", uri=True)
    sg_conn.row_factory = sqlite3.Row

    print("="*70)
    print("ALIGNMENT DATA QUALITY AUDIT")
    print("="*70)

    # ─── 1. Grade-Level Distribution ──────────────────────────────────

    print("\n1. COVERAGE BY GRADE LEVEL")
    print("─" * 70)

    grade_stats = conn.execute("""
        SELECT
          c.grade_band,
          COUNT(DISTINCT c.id) as unique_chunks,
          COUNT(DISTINCT a.standard_id) as aligned_standards,
          COUNT(a.id) as total_alignments,
          ROUND(AVG(a.alignment_score), 3) as avg_score,
          ROUND(MIN(a.alignment_score), 3) as min_score,
          ROUND(MAX(a.alignment_score), 3) as max_score
        FROM chunks c
        LEFT JOIN standard_alignments a ON c.id = a.chunk_id AND a.stale = 0
        WHERE c.stale = 0
        GROUP BY c.grade_band
        ORDER BY c.grade_band
    """).fetchall()

    for row in grade_stats:
        grade = row["grade_band"] or "unspecified"
        print(f"{grade:15} | {row['unique_chunks']:5} chunks | {row['aligned_standards']:5} standards | "
              f"{row['total_alignments']:6} alignments | avg score: {row['avg_score']}")

    # ─── 2. Source Quality Comparison ─────────────────────────────────

    print("\n2. QUALITY BY SOURCE")
    print("─" * 70)

    source_stats = conn.execute("""
        SELECT
          c.source_id,
          COUNT(DISTINCT c.id) as unique_chunks,
          COUNT(DISTINCT a.standard_id) as aligned_standards,
          COUNT(a.id) as total_alignments,
          ROUND(AVG(a.alignment_score), 3) as avg_score,
          ROUND(AVG(CASE WHEN a.alignment_source IN ('human','publisher_guide','llm_verified') THEN 1 ELSE 0 END), 2) as pct_high_confidence
        FROM chunks c
        LEFT JOIN standard_alignments a ON c.id = a.chunk_id AND a.stale = 0
        WHERE c.stale = 0
        GROUP BY c.source_id
        ORDER BY total_alignments DESC
    """).fetchall()

    for row in source_stats:
        print(f"{row['source_id']:15} | {row['unique_chunks']:5} chunks | {row['aligned_standards']:5} standards | "
              f"{row['total_alignments']:6} alignments | avg score: {row['avg_score']} | high conf: {row['pct_high_confidence']:.0%}")

    # ─── 3. Alignment Score Distribution ──────────────────────────────

    print("\n3. ALIGNMENT SCORE DISTRIBUTION")
    print("─" * 70)

    score_dist = conn.execute("""
        SELECT
          alignment_source,
          COUNT(*) as count,
          ROUND(AVG(alignment_score), 3) as mean,
          ROUND(MIN(alignment_score), 3) as min,
          ROUND(MAX(alignment_score), 3) as max,
          ROUND(COUNT(CASE WHEN alignment_score >= 0.8 THEN 1 END) * 100.0 / COUNT(*), 1) as pct_strong
        FROM standard_alignments
        WHERE stale = 0
        GROUP BY alignment_source
        ORDER BY count DESC
    """).fetchall()

    for row in score_dist:
        print(f"{row['alignment_source']:20} | {row['count']:5} | mean: {row['mean']} | "
              f"range: [{row['min']}, {row['max']}] | strong (≥0.8): {row['pct_strong']:5.1f}%")

    # ─── 4. Coverage by Standard ──────────────────────────────────────

    print("\n4. TOP 20 BEST COVERED STANDARDS")
    print("─" * 70)

    top_covered = conn.execute("""
        SELECT
          a.standard_id,
          COUNT(DISTINCT a.chunk_id) as num_chunks,
          ROUND(AVG(a.alignment_score), 3) as avg_score,
          GROUP_CONCAT(DISTINCT a.alignment_source) as sources
        FROM standard_alignments a
        WHERE a.stale = 0
        GROUP BY a.standard_id
        ORDER BY num_chunks DESC
        LIMIT 20
    """).fetchall()

    for i, row in enumerate(top_covered, 1):
        std_row = sg_conn.execute(
            "SELECT standard_text FROM standards WHERE id = ? AND system = 'ccss'",
            (row["standard_id"],),
        ).fetchone()
        std_text = (std_row["standard_text"][:50] if std_row else "unknown")[:50]
        print(f"{i:2}. {row['standard_id']:30} | {row['num_chunks']:3} chunks | "
              f"score: {row['avg_score']} | sources: {row['sources'][:30]}")
        print(f"    {std_text}")

    # ─── 5. Outliers (Suspicious Alignments) ──────────────────────────

    print("\n5. POTENTIAL OUTLIERS (LOW CONFIDENCE PUBLISHERS/HUMAN)")
    print("─" * 70)

    outliers = conn.execute("""
        SELECT
          a.id,
          a.chunk_id,
          a.standard_id,
          a.alignment_score,
          c.title
        FROM standard_alignments a
        JOIN chunks c ON c.id = a.chunk_id
        WHERE a.alignment_source IN ('publisher_guide', 'human')
          AND a.alignment_score < 0.7
          AND a.stale = 0
        LIMIT 10
    """).fetchall()

    if outliers:
        for row in outliers:
            print(f"  {row['standard_id']} ← {row['chunk_id'][:30]:30} (score: {row['alignment_score']})")
            print(f"    {row['title'][:60]}")
    else:
        print("  ✓ No outliers found (all publisher_guide/human alignments have score ≥0.7)")

    # ─── 6. Coverage Gaps ────────────────────────────────────────────

    print("\n6. POTENTIAL COVERAGE GAPS (STANDARDS WITH WEAK COVERAGE)")
    print("─ ──────────────────────────────────────────────────────────")

    # Get all CCSS standards
    all_standards = sg_conn.execute(
        "SELECT DISTINCT id FROM standards WHERE system = 'ccss' AND id LIKE 'CCSS.MATH%' ORDER BY id"
    ).fetchall()

    # Find which standards have no strong coverage
    weak_coverage = []
    for std_row in tqdm(all_standards, desc="Checking standards", disable=True):
        std_id = std_row["id"]
        coverage = conn.execute("""
            SELECT COUNT(*) as count, AVG(alignment_score) as avg_score
            FROM standard_alignments
            WHERE standard_id = ? AND stale = 0
        """, (std_id,)).fetchone()

        if coverage["count"] == 0 or (coverage["count"] < 2 and coverage["avg_score"] < 0.75):
            weak_coverage.append((std_id, coverage["count"] or 0, coverage["avg_score"] or 0))

    print(f"Found {len(weak_coverage)} standards with weak coverage (0-1 low-quality alignments)")
    print("Sample weak coverage standards:")
    for std_id, count, avg_score in weak_coverage[:10]:
        std_row = sg_conn.execute(
            "SELECT standard_text FROM standards WHERE id = ? AND system = 'ccss'",
            (std_id,),
        ).fetchone()
        std_text = (std_row["standard_text"][:50] if std_row else "")[:50]
        print(f"  {std_id:30} | {count} chunks | avg: {avg_score:.2f} | {std_text}")

    # ─── 7. Summary Statistics ───────────────────────────────────────

    print("\n7. SUMMARY STATISTICS")
    print("─" * 70)

    summary = conn.execute("""
        SELECT
          COUNT(DISTINCT a.chunk_id) as total_aligned_chunks,
          COUNT(DISTINCT a.standard_id) as total_aligned_standards,
          COUNT(a.id) as total_alignments,
          ROUND(AVG(a.alignment_score), 3) as global_avg_score,
          COUNT(CASE WHEN a.alignment_source = 'human' THEN 1 END) as human_verified,
          COUNT(CASE WHEN a.alignment_source = 'publisher_guide' THEN 1 END) as publisher_guide,
          COUNT(CASE WHEN a.alignment_source = 'llm_verified' THEN 1 END) as llm_verified,
          COUNT(CASE WHEN a.alignment_source = 'embedding' THEN 1 END) as embedding
        FROM standard_alignments a
        WHERE a.stale = 0
    """).fetchone()

    print(f"Total aligned chunks:      {summary['total_aligned_chunks']}")
    print(f"Total aligned standards:   {summary['total_aligned_standards']}")
    print(f"Total alignments:          {summary['total_alignments']}")
    print(f"Global average score:      {summary['global_avg_score']}")
    print()
    print(f"By source:")
    print(f"  Human verified:          {summary['human_verified']:5}")
    print(f"  Publisher guide:         {summary['publisher_guide']:5}")
    print(f"  LLM verified:            {summary['llm_verified']:5}")
    print(f"  Embedding (raw):         {summary['embedding']:5}")

    # ─── 8. Coverage Notes Quality ───────────────────────────────────

    print("\n8. COVERAGE NOTES QUALITY")
    print("─" * 70)

    notes_stats = conn.execute("""
        SELECT
          COUNT(*) as total_alignments,
          COUNT(CASE WHEN coverage_notes IS NOT NULL THEN 1 END) as with_notes,
          COUNT(CASE WHEN coverage_notes IS NOT NULL AND LENGTH(coverage_notes) > 30 THEN 1 END) as with_substantial_notes,
          ROUND(AVG(LENGTH(coverage_notes)), 1) as avg_note_length
        FROM standard_alignments
        WHERE stale = 0
    """).fetchone()

    pct_notes = (notes_stats["with_notes"] / notes_stats["total_alignments"] * 100) if notes_stats["total_alignments"] > 0 else 0
    pct_substantial = (notes_stats["with_substantial_notes"] / notes_stats["total_alignments"] * 100) if notes_stats["total_alignments"] > 0 else 0

    print(f"Total alignments:          {notes_stats['total_alignments']}")
    print(f"With any coverage notes:   {notes_stats['with_notes']:5} ({pct_notes:.1f}%)")
    print(f"With substantial notes:    {notes_stats['with_substantial_notes']:5} ({pct_substantial:.1f}%)")
    print(f"Average note length:       {notes_stats['avg_note_length']:.0f} chars")

    print("\n" + "="*70)
    print("AUDIT COMPLETE")
    print("="*70)

    sg_conn.close()
    conn.close()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Alignment data quality audit")
    p.add_argument("--db", default="data/oer_core.db")
    p.add_argument("--sg-db", default=str(Path.home() / ".standardgraph" / "common_core.db"))
    args = p.parse_args()

    analyze_alignment_data(args.db, args.sg_db)
