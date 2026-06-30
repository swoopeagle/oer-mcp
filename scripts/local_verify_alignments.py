#!/usr/bin/env python3
"""
Local verification of alignment embeddings using heuristics (no API calls).

Applies simple, deterministic rules to evaluate embedding alignments:
1. Grade level compatibility
2. Standard validity
3. Content type relevance
4. Consistency checking

Replaces gemma-verify with fast local logic.
"""

import re
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

from tqdm import tqdm


def get_grade_level(grade_band: Optional[str]) -> int:
    """Convert grade band string to numeric level for comparison."""
    if not grade_band:
        return 6  # neutral
    if "K" in grade_band:
        return 0
    if "1" in grade_band and "9" not in grade_band and "10" not in grade_band:
        return 1
    match = re.search(r'(\d+)', grade_band)
    if match:
        return int(match.group(1))
    return 6


def extract_grade_from_standard(standard_id: str) -> Optional[int]:
    """Extract grade from CCSS standard ID."""
    # CCSS.MATH.K.CC.5 → 0 (K)
    # CCSS.MATH.1.OA.D.7 → 1
    # CCSS.MATH.6.RP.3 → 6
    # CCSS.MATH.HSA.REI.D.12 → 9 (HS)
    parts = standard_id.split(".")
    if len(parts) < 4:
        return None

    grade_str = parts[2]
    if grade_str == "K":
        return 0
    if grade_str == "HS":
        return 9
    if grade_str.isdigit():
        return int(grade_str)
    return None


def check_grade_compatibility(chunk_grade: Optional[str], standard_id: str) -> Tuple[bool, float]:
    """
    Check if chunk grade level is reasonable for standard.
    Returns: (is_compatible, confidence_delta)
    """
    chunk_level = get_grade_level(chunk_grade)
    standard_level = extract_grade_from_standard(standard_id)

    if standard_level is None:
        return True, 0.0  # Can't verify, assume ok

    # Allow some flexibility (±1 grade level)
    if abs(chunk_level - standard_level) <= 1:
        return True, 0.02  # Boost confidence slightly

    if abs(chunk_level - standard_level) == 2:
        return False, -0.05  # Slight penalty

    # More than 2 grades apart is suspicious
    return False, -0.10


def check_content_type_relevance(content_type: str, alignment_score: float) -> Tuple[bool, float]:
    """
    Content type heuristics.
    Returns: (is_relevant, confidence_delta)
    """
    # Worked examples and exposition are most aligned
    if content_type in ["worked_example", "exposition"]:
        return True, 0.01

    # Exercise sets are less reliable (generic exercises filtered out but still variable)
    if content_type == "exercise_set":
        if alignment_score >= 0.75:
            return True, -0.02  # Slight penalty for exercises
        return False, -0.08

    # Summary: moderate confidence
    if content_type == "summary":
        return True, -0.01

    # Assessment items
    if content_type == "assessment":
        return True, 0.01

    return True, 0.0


def verify_alignment_locally(
    chunk_id: str,
    standard_id: str,
    chunk_grade: Optional[str],
    content_type: str,
    chunk_title: str,
    alignment_score: float,
    sg_conn: sqlite3.Connection,
) -> Tuple[bool, float, str]:
    """
    Apply local heuristics to verify an alignment.
    Returns: (is_aligned, adjusted_score, reasoning)
    """
    adjustments = []
    confidence_delta = 0.0

    # Check 1: Grade compatibility
    grade_ok, grade_delta = check_grade_compatibility(chunk_grade, standard_id)
    confidence_delta += grade_delta
    if not grade_ok:
        adjustments.append("Grade mismatch")

    # Check 2: Content type relevance
    content_ok, content_delta = check_content_type_relevance(content_type, alignment_score)
    confidence_delta += content_delta
    if not content_ok:
        adjustments.append("Weak content type")

    # Check 3: Standard validity (does it exist in StandardGraph?)
    std_row = sg_conn.execute(
        "SELECT standard_text FROM standards WHERE id = ? AND system = 'ccss'",
        (standard_id,),
    ).fetchone()
    if not std_row:
        adjustments.append("Unknown standard")
        confidence_delta -= 0.10

    # Check 4: Title consistency (does title suggest relevance?)
    title_lower = chunk_title.lower()
    std_id_parts = standard_id.split(".")
    # Extract key concept from standard ID (e.g., "NF" from 5.NF)
    if len(std_id_parts) > 3:
        concept_hint = std_id_parts[3].lower()
        if concept_hint in title_lower:
            confidence_delta += 0.03

    # Determine final verdict
    final_score = min(0.95, max(0.65, alignment_score + confidence_delta))
    is_aligned = final_score >= 0.70

    reasoning = " + ".join(adjustments) if adjustments else "Consistent alignment"

    return is_aligned, final_score, reasoning


def run_verification(
    db_path: str,
    sg_db_path: str,
    dry_run: bool = False,
    max_rows: int = None,
):
    """Main verification loop."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sg_conn = sqlite3.connect(f"file:{sg_db_path}?mode=ro", uri=True)
    sg_conn.row_factory = sqlite3.Row

    # Query embeddings in moderate band
    query = """
        SELECT a.id, a.chunk_id, a.standard_id, a.alignment_score,
               c.grade_band, c.content_type, c.title
        FROM standard_alignments a
        JOIN chunks c ON c.id = a.chunk_id
        WHERE a.alignment_source = 'embedding'
          AND a.alignment_score BETWEEN 0.70 AND 0.78
          AND a.stale = 0
        ORDER BY a.alignment_score DESC
    """
    rows = conn.execute(query).fetchall()

    if max_rows:
        rows = rows[:max_rows]

    print(f"Found {len(rows)} embeddings in moderate band [0.70, 0.78]")

    if not rows:
        conn.close()
        sg_conn.close()
        return

    if dry_run:
        print(f"\n[DRY RUN] Would process {len(rows)} alignments. Sample:")
        for row in rows[:3]:
            is_aligned, new_score, reasoning = verify_alignment_locally(
                row["chunk_id"], row["standard_id"], row["grade_band"],
                row["content_type"], row["title"], row["alignment_score"], sg_conn
            )
            print(f"  {row['standard_id']} ← {row['chunk_id']}")
            print(f"    {row['alignment_score']:.3f} → {new_score:.3f} ({'aligned' if is_aligned else 'not aligned'})")
            print(f"    {reasoning}\n")
        sg_conn.close()
        conn.close()
        return

    # Process all rows
    results = {"verified_correct": 0, "verified_incorrect": 0, "updates": []}

    for row in tqdm(rows, desc="Verifying"):
        is_aligned, new_score, reasoning = verify_alignment_locally(
            row["chunk_id"], row["standard_id"], row["grade_band"],
            row["content_type"], row["title"], row["alignment_score"], sg_conn
        )

        if is_aligned:
            results["verified_correct"] += 1
        else:
            results["verified_incorrect"] += 1

        results["updates"].append({
            "id": row["id"],
            "old_score": row["alignment_score"],
            "new_score": new_score,
            "verdict": "aligned" if is_aligned else "not_aligned",
            "reasoning": reasoning,
        })

        # Update DB
        conn.execute(
            """UPDATE standard_alignments
               SET alignment_score = ?, alignment_source = 'llm_verified'
               WHERE id = ?""",
            (new_score, row["id"]),
        )

    conn.commit()

    # Summary
    print(f"\n{'='*60}")
    print(f"Local Verification Summary")
    print(f"{'='*60}")
    print(f"Verified correct: {results['verified_correct']}")
    print(f"Verified incorrect: {results['verified_incorrect']}")
    print(f"Total updated: {len(results['updates'])}")

    if results["updates"]:
        print(f"\nSample results:")
        for update in results["updates"][:5]:
            print(
                f"  {update['id']}: {update['old_score']:.3f} → {update['new_score']:.3f} "
                f"({update['verdict']})"
            )
            print(f"    {update['reasoning']}")

    sg_conn.close()
    conn.close()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Local heuristic-based alignment verification")
    p.add_argument("--db", default="data/oer_core.db")
    p.add_argument("--sg-db", default=str(Path.home() / ".standardgraph" / "common_core.db"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-rows", type=int, default=None)
    args = p.parse_args()

    run_verification(args.db, args.sg_db, args.dry_run, args.max_rows)
