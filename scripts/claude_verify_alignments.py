#!/usr/bin/env python3
"""
Claude-based alignment verification: re-score embedding alignments in the moderate band.

Replaces the `gemma-verify` stage with Claude Opus/Sonnet for higher-quality
verification. Processes embeddings with score 0.70–0.78 and outputs verified
scores for standard_alignments.alignment_score.

Usage:
    python scripts/claude_verify_alignments.py \
        --db data/oer_core.db \
        --model claude-opus-4-8 \
        --batch-size 10 \
        --dry-run  # See what would be processed without modifying DB

Prerequisites:
    - ANTHROPIC_API_KEY set in environment
    - StandardGraph DB available (for standard definitions)
"""

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Optional

import anthropic
from tqdm import tqdm

# Embedding band thresholds (from CLAUDE.md: D18)
EMBED_MODERATE_MIN = 0.70
EMBED_MODERATE_MAX = 0.78

VERIFY_PROMPT = """You are a curriculum alignment expert. Evaluate whether the following
educational content chunk is actually aligned with the given standard.

**Standard:** {standard_id}
"{standard_text}"

**Chunk (from {source}):**
Title: {chunk_title}
Type: {chunk_type}
Grade: {chunk_grade}
Content preview (first 1000 chars):
{chunk_content}

**Task:** Decide if this chunk truly teaches/covers the standard. Consider:
1. Does the content address the learning objective stated in the standard?
2. Are the methods/examples relevant to this standard?
3. Is the grade level appropriate?
4. Would a student learning from this content learn what the standard requires?

Reply with ONLY a JSON object (no markdown, no explanation):
{{
  "aligned": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "one sentence explaining why"
}}
"""


def get_chunk(conn: sqlite3.Connection, chunk_id: str) -> Optional[dict]:
    """Fetch chunk details by ID."""
    row = conn.execute(
        """SELECT id, title, content_type, grade_band, content, source_id, attribution
           FROM chunks WHERE id = ? AND stale = 0""",
        (chunk_id,),
    ).fetchone()
    return dict(row) if row else None


def get_standard(conn: sqlite3.Connection, standard_id: str, sg_db_path: str) -> Optional[str]:
    """Fetch standard text from StandardGraph."""
    sg = sqlite3.connect(f"file:{sg_db_path}?mode=ro", uri=True)
    sg.row_factory = sqlite3.Row
    row = sg.execute(
        "SELECT standard_text FROM standards WHERE id = ? AND system = 'ccss'",
        (standard_id,),
    ).fetchone()
    sg.close()
    return row["standard_text"] if row else None


def verify_alignment_with_claude(
    client: anthropic.Anthropic,
    standard_id: str,
    standard_text: str,
    chunk: dict,
    model: str,
) -> dict:
    """Call Claude to verify an alignment."""
    prompt = VERIFY_PROMPT.format(
        standard_id=standard_id,
        standard_text=standard_text,
        source=chunk["source_id"],
        chunk_title=chunk["title"],
        chunk_type=chunk["content_type"],
        chunk_grade=chunk["grade_band"] or "unspecified",
        chunk_content=chunk["content"][:1000] if chunk["content"] else "",
    )

    response = client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        result = json.loads(response.content[0].text)
        return {
            "success": True,
            "aligned": result.get("aligned", False),
            "confidence": result.get("confidence", 0.5),
            "reasoning": result.get("reasoning", ""),
        }
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        return {
            "success": False,
            "error": str(e),
            "raw_response": response.content[0].text if response.content else "",
        }


def run_verification(
    db_path: str,
    sg_db_path: str,
    model: str = "claude-opus-4-8",
    batch_size: int = 10,
    dry_run: bool = False,
    max_rows: int = None,
):
    """Main verification loop."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Query alignments in the moderate embedding band
    query = """
        SELECT a.id, a.chunk_id, a.standard_id, a.alignment_score
        FROM standard_alignments a
        WHERE a.alignment_source = 'embedding'
          AND a.alignment_score BETWEEN ? AND ?
          AND a.stale = 0
        ORDER BY a.alignment_score DESC
    """
    rows = conn.execute(query, (EMBED_MODERATE_MIN, EMBED_MODERATE_MAX)).fetchall()

    if max_rows:
        rows = rows[:max_rows]

    print(f"Found {len(rows)} embeddings in moderate band [{EMBED_MODERATE_MIN}, {EMBED_MODERATE_MAX}]")

    if not rows:
        print("Nothing to verify. Exiting.")
        conn.close()
        return

    if dry_run:
        print(f"\n[DRY RUN] Would process {len(rows)} alignments. Sample:")
        for row in rows[:3]:
            chunk = get_chunk(conn, row["chunk_id"])
            print(f"  {row['standard_id']} ← {row['chunk_id']} (score: {row['alignment_score']:.3f})")
        conn.close()
        return

    # Initialize Claude client
    client = anthropic.Anthropic()

    # Track results
    results = {"verified_correct": 0, "verified_incorrect": 0, "errors": 0, "updates": []}

    # Process in batches (to use Claude's batch API if available, or just for logging)
    for batch_start in tqdm(range(0, len(rows), batch_size), desc="Processing batches"):
        batch = rows[batch_start : batch_start + batch_size]

        for row in batch:
            chunk = get_chunk(conn, row["chunk_id"])
            if not chunk:
                results["errors"] += 1
                continue

            standard_text = get_standard(conn, row["standard_id"], sg_db_path)
            if not standard_text:
                results["errors"] += 1
                continue

            # Verify with Claude
            verdict = verify_alignment_with_claude(
                client, row["standard_id"], standard_text, chunk, model
            )

            if not verdict["success"]:
                results["errors"] += 1
                continue

            aligned = verdict["aligned"]
            confidence = verdict["confidence"]

            if aligned:
                results["verified_correct"] += 1
                new_score = min(0.95, row["alignment_score"] + 0.05)  # boost verified
            else:
                results["verified_incorrect"] += 1
                new_score = min(0.65, row["alignment_score"] - 0.10)  # penalize wrong

            results["updates"].append(
                {
                    "id": row["id"],
                    "old_score": row["alignment_score"],
                    "new_score": new_score,
                    "verdict": "aligned" if aligned else "not_aligned",
                    "confidence": confidence,
                    "reasoning": verdict.get("reasoning", ""),
                }
            )

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
    print(f"Verification Summary ({model})")
    print(f"{'='*60}")
    print(f"Verified correct: {results['verified_correct']}")
    print(f"Verified incorrect: {results['verified_incorrect']}")
    print(f"Errors: {results['errors']}")
    print(f"Total updated: {len(results['updates'])}")

    if results["updates"]:
        print(f"\nSample updates:")
        for update in results["updates"][:3]:
            print(
                f"  {update['id']}: {update['old_score']:.3f} → {update['new_score']:.3f} "
                f"({update['verdict']}, confidence: {update['confidence']:.2f})"
            )

    conn.close()
    return results


def main():
    p = argparse.ArgumentParser(description="Claude-based alignment verification")
    p.add_argument("--db", default="data/oer_core.db", help="Path to OER DB")
    p.add_argument("--sg-db", default=str(Path.home() / ".standardgraph" / "common_core.db"))
    p.add_argument("--model", default="claude-opus-4-8", help="Claude model to use")
    p.add_argument("--batch-size", type=int, default=10, help="Batch size for processing")
    p.add_argument("--dry-run", action="store_true", help="Don't modify DB, just show what would happen")
    p.add_argument("--max-rows", type=int, default=None, help="Limit number of rows to process")
    args = p.parse_args()

    run_verification(
        args.db,
        args.sg_db,
        model=args.model,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        max_rows=args.max_rows,
    )


if __name__ == "__main__":
    main()
