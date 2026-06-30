#!/usr/bin/env python3
"""
Coverage analysis: generate reports, heatmaps, and gap analysis.

Creates CSV reports suitable for visualization in Excel/Sheets.
"""

import csv
import sqlite3
from pathlib import Path


def generate_coverage_by_grade(db_path: str, sg_db_path: str, output_path: str = "coverage_by_grade.csv"):
    """Grade-level coverage heatmap data."""
    conn = sqlite3.connect(db_path)
    sg_conn = sqlite3.connect(f"file:{sg_db_path}?mode=ro", uri=True)

    grades = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
    domains = set()

    # Find all domains
    for row in sg_conn.execute(
        "SELECT DISTINCT domain FROM standards WHERE system='ccss' AND id LIKE 'CCSS.MATH.%'"
    ).fetchall():
        domains.add(row[0])

    domains = sorted(list(domains))

    # Build matrix
    rows = []
    for grade in grades:
        row_data = {"grade": grade}
        for domain in domains:
            # Count standards in this grade/domain with coverage
            count = conn.execute("""
                SELECT COUNT(DISTINCT a.standard_id)
                FROM standard_alignments a
                WHERE a.standard_id LIKE ? AND a.stale = 0
            """, (f"CCSS.MATH.{grade}.{domain}%",)).fetchone()[0]
            row_data[domain] = count
        rows.append(row_data)

    # Write CSV
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["grade"] + domains)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✓ Coverage by grade heatmap → {output_path}")
    conn.close()
    sg_conn.close()


def generate_gap_analysis(db_path: str, sg_db_path: str, output_path: str = "standards_gaps.csv"):
    """Standards with zero or weak coverage."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sg_conn = sqlite3.connect(f"file:{sg_db_path}?mode=ro", uri=True)
    sg_conn.row_factory = sqlite3.Row

    all_standards = sg_conn.execute(
        "SELECT id, standard_text FROM standards WHERE system='ccss' AND id LIKE 'CCSS.MATH.%' ORDER BY id"
    ).fetchall()

    rows = []
    for std_id, std_text in all_standards:
        coverage = conn.execute("""
            SELECT COUNT(*) as count, AVG(alignment_score) as avg_score,
                   MAX(alignment_score) as max_score
            FROM standard_alignments
            WHERE standard_id = ? AND stale = 0
        """, (std_id,)).fetchone()

        rows.append({
            "standard_id": std_id,
            "standard_text": std_text,
            "chunk_count": coverage["count"] or 0,
            "avg_score": coverage["avg_score"] or 0,
            "max_score": coverage["max_score"] or 0,
            "coverage_level": (
                "strong" if coverage["count"] and coverage["count"] >= 3 else
                "weak" if coverage["count"] else "none"
            ),
        })

    # Write CSV
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["standard_id", "standard_text", "chunk_count", "avg_score", "max_score", "coverage_level"])
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    strong = sum(1 for r in rows if r["coverage_level"] == "strong")
    weak = sum(1 for r in rows if r["coverage_level"] == "weak")
    none_count = sum(1 for r in rows if r["coverage_level"] == "none")

    print(f"✓ Gap analysis → {output_path}")
    print(f"  Strong coverage (≥3 chunks):  {strong:3}")
    print(f"  Weak coverage (1-2 chunks):   {weak:3}")
    print(f"  No coverage (0 chunks):       {none_count:3}")
    print(f"  Total standards:              {len(rows):3}")

    conn.close()
    sg_conn.close()


def generate_source_quality_report(db_path: str, output_path: str = "source_quality.csv"):
    """Quality metrics by source."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT
          c.source_id,
          COUNT(DISTINCT c.id) as chunks,
          COUNT(DISTINCT a.standard_id) as standards,
          COUNT(a.id) as alignments,
          ROUND(AVG(a.alignment_score), 3) as avg_score,
          COUNT(CASE WHEN a.alignment_source='publisher_guide' THEN 1 END) as publisher_guide_count,
          COUNT(CASE WHEN a.alignment_source='llm_verified' THEN 1 END) as llm_verified_count,
          COUNT(CASE WHEN a.alignment_score >= 0.8 THEN 1 END) as strong_alignments
        FROM chunks c
        LEFT JOIN standard_alignments a ON c.id = a.chunk_id AND a.stale = 0
        WHERE c.stale = 0
        GROUP BY c.source_id
        ORDER BY alignments DESC
    """).fetchall()

    data = []
    for row in rows:
        data.append({
            "source_id": row["source_id"],
            "chunks": row["chunks"],
            "standards": row["standards"],
            "alignments": row["alignments"],
            "avg_score": row["avg_score"],
            "publisher_guide": row["publisher_guide_count"],
            "llm_verified": row["llm_verified_count"],
            "strong_alignments": row["strong_alignments"],
        })

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)

    print(f"✓ Source quality report → {output_path}")
    conn.close()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Generate coverage analysis reports")
    p.add_argument("--db", default="data/oer_core.db")
    p.add_argument("--sg-db", default=str(Path.home() / ".standardgraph" / "common_core.db"))
    p.add_argument("--output-dir", default=".", help="Directory for CSV outputs")
    args = p.parse_args()

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    print("Generating analysis reports...\n")
    generate_coverage_by_grade(args.db, args.sg_db, f"{args.output_dir}/coverage_by_grade.csv")
    generate_gap_analysis(args.db, args.sg_db, f"{args.output_dir}/standards_gaps.csv")
    generate_source_quality_report(args.db, f"{args.output_dir}/source_quality.csv")
    print("\nAll reports generated! Import CSVs into Excel for visualization.")
