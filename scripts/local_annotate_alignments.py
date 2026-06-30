#!/usr/bin/env python3
"""
Local annotation of alignment coverage notes using heuristics (no API calls).

Generates substantive coverage notes by:
1. Extracting standard definition
2. Analyzing chunk content type and title
3. Applying templates + heuristics
4. Writing results directly to DB

Replaces gemma-annotate with deterministic local logic.
"""

import re
import sqlite3
from pathlib import Path
from typing import Optional

from tqdm import tqdm


def generate_coverage_note(
    chunk_title: str,
    chunk_type: str,
    chunk_grade: Optional[str],
    standard_id: str,
    standard_text: str,
    chunk_content: Optional[str] = None,
) -> str:
    """
    Generate a coverage note using heuristics.
    Returns: 1-2 sentence explanation of how chunk teaches standard.
    """
    # Extract key concepts from standard
    standard_lower = standard_text.lower()
    title_lower = chunk_title.lower()

    # Content type-specific templates
    if chunk_type == "worked_example":
        # For worked examples, note that they demonstrate the concept
        return (
            f"Worked example demonstrating {standard_text.split(':')[0].strip() if ':' in standard_text else standard_id.split('.')[-1]}. "
            f"Provides step-by-step solution approach for this standard."
        )

    elif chunk_type == "exposition":
        # For exposition, note that it teaches the concept
        return (
            f"Teaches {standard_text.split(':')[0].strip() if ':' in standard_text else 'this standard'} "
            f"through explanation and examples. Grade level: {chunk_grade or 'K-12'}."
        )

    elif chunk_type == "exercise_set":
        # For exercises, note that they provide practice
        practice_type = "practice problems" if "practice" in title_lower else "exercises"
        return (
            f"Provides {practice_type} for {standard_text.split(':')[0].strip() if ':' in standard_text else standard_id.split('.')[-1]}. "
            f"Reinforces procedural fluency and conceptual understanding."
        )

    elif chunk_type == "summary":
        # For summaries, note that they review the concept
        return (
            f"Summary of {standard_text.split(':')[0].strip() if ':' in standard_text else standard_id.split('.')[-1]}. "
            f"Consolidates key ideas and procedures for this standard."
        )

    elif chunk_type == "assessment":
        # For assessments, note that they test understanding
        item_desc = "Multiple choice question" if "multiple" in title_lower else "Assessment item"
        return (
            f"{item_desc} assessing {standard_text.split(':')[0].strip() if ':' in standard_text else standard_id.split('.')[-1]}. "
            f"Evaluates student mastery of this standard."
        )

    else:
        # Fallback generic template
        return (
            f"Content addressing {standard_id.split('.')[-1]}. "
            f"Supports instruction for this standard."
        )


def should_annotate(alignment_source: str, alignment_score: float, existing_notes: Optional[str]) -> bool:
    """Determine if alignment should be annotated."""
    # Skip if already has good notes
    if existing_notes and len(existing_notes) > 30:
        return False

    # Annotate high-confidence alignments
    if alignment_source in ("publisher_guide", "human"):
        return True

    if alignment_source == "llm_verified" and alignment_score >= 0.75:
        return True

    # Annotate strong embedding alignments
    if alignment_source == "embedding" and alignment_score >= 0.78:
        return True

    return False


def run_annotation(
    db_path: str,
    sg_db_path: str,
    dry_run: bool = False,
    max_rows: int = None,
):
    """Main annotation loop."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sg_conn = sqlite3.connect(f"file:{sg_db_path}?mode=ro", uri=True)
    sg_conn.row_factory = sqlite3.Row

    # Query alignments that should be annotated
    query = """
        SELECT a.id, a.chunk_id, a.standard_id, a.alignment_source, a.alignment_score,
               a.coverage_notes,
               c.title, c.content_type, c.grade_band, c.content
        FROM standard_alignments a
        JOIN chunks c ON c.id = a.chunk_id
        WHERE a.stale = 0
          AND (
            a.alignment_source IN ('publisher_guide', 'human', 'llm_verified')
            OR (a.alignment_source = 'embedding' AND a.alignment_score >= 0.78)
          )
        ORDER BY a.alignment_source DESC, a.alignment_score DESC
    """
    rows = conn.execute(query).fetchall()

    if max_rows:
        rows = rows[:max_rows]

    # Filter to only those that need annotation
    rows_to_annotate = [
        r for r in rows if should_annotate(r["alignment_source"], r["alignment_score"], r["coverage_notes"])
    ]

    print(f"Found {len(rows)} high-confidence alignments")
    print(f"Targeting {len(rows_to_annotate)} for annotation (skipping already annotated)")

    if not rows_to_annotate:
        print("Nothing to annotate.")
        sg_conn.close()
        conn.close()
        return

    if dry_run:
        print(f"\n[DRY RUN] Would annotate {len(rows_to_annotate)}. Sample:")
        for row in rows_to_annotate[:3]:
            std_row = sg_conn.execute(
                "SELECT standard_text FROM standards WHERE id = ? AND system = 'ccss'",
                (row["standard_id"],),
            ).fetchone()
            std_text = std_row["standard_text"] if std_row else row["standard_id"]

            note = generate_coverage_note(
                row["title"], row["content_type"], row["grade_band"],
                row["standard_id"], std_text, row["content"]
            )
            print(f"  {row['standard_id']} ← {row['chunk_id']}")
            print(f"  Note: {note}\n")

        sg_conn.close()
        conn.close()
        return

    # Process all rows
    results = {"annotated": 0, "updates": []}

    for row in tqdm(rows_to_annotate, desc="Annotating"):
        # Get standard text
        std_row = sg_conn.execute(
            "SELECT standard_text FROM standards WHERE id = ? AND system = 'ccss'",
            (row["standard_id"],),
        ).fetchone()
        std_text = std_row["standard_text"] if std_row else row["standard_id"]

        # Generate note
        note = generate_coverage_note(
            row["title"], row["content_type"], row["grade_band"],
            row["standard_id"], std_text, row["content"]
        )

        results["annotated"] += 1
        results["updates"].append({
            "id": row["id"],
            "standard_id": row["standard_id"],
            "chunk_id": row["chunk_id"],
            "note": note,
        })

        # Update DB
        conn.execute(
            "UPDATE standard_alignments SET coverage_notes = ? WHERE id = ?",
            (note, row["id"]),
        )

    conn.commit()

    # Summary
    print(f"\n{'='*60}")
    print(f"Local Annotation Summary")
    print(f"{'='*60}")
    print(f"Annotated: {results['annotated']}")

    if results["updates"]:
        print(f"\nSample annotations:")
        for update in results["updates"][:3]:
            print(f"\n  {update['standard_id']} ← {update['chunk_id']}")
            print(f"  {update['note']}")

    sg_conn.close()
    conn.close()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Local heuristic-based alignment annotation")
    p.add_argument("--db", default="data/oer_core.db")
    p.add_argument("--sg-db", default=str(Path.home() / ".standardgraph" / "common_core.db"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-rows", type=int, default=None)
    args = p.parse_args()

    run_annotation(args.db, args.sg_db, args.dry_run, args.max_rows)
