#!/usr/bin/env python3
"""
Claude-based coverage note annotation: generate substantive coverage notes for verified alignments.

Replaces the `gemma-annotate` stage with Claude for richer, more pedagogically useful
explanations of how each chunk teaches/addresses a standard.

Targets alignments with:
- alignment_source = 'publisher_guide' or 'human' (high confidence, always)
- alignment_source = 'llm_verified' (already verified)
- alignment_score >= 0.78 (embedding strong band, verified)

Usage:
    python scripts/claude_annotate_alignments.py \
        --db data/oer_core.db \
        --model claude-opus-4-8 \
        --batch-size 10 \
        --dry-run

Prerequisites:
    - ANTHROPIC_API_KEY set in environment
    - StandardGraph DB available (for standard definitions)
"""

import argparse
import sqlite3
from pathlib import Path

import anthropic
from tqdm import tqdm

ANNOTATE_PROMPT = """You are a curriculum specialist. Write a brief, specific note explaining
how the given educational content chunk addresses the stated standard.

**Standard:** {standard_id}
"{standard_text}"

**Chunk (from {source}):**
Title: {chunk_title}
Type: {chunk_type}
Grade: {chunk_grade}
Content preview (first 1500 chars):
{chunk_content}

**Task:** Write a short note (1-2 sentences, ~50 words) explaining:
- What aspect(s) of the standard this chunk teaches
- What methods/examples from the chunk align to the standard
- Any grade-level considerations

Make it specific and grounded in the actual content. A curriculum designer should
understand from your note why this chunk is relevant to the standard.

Reply with ONLY the note text (no JSON, no quotes, no markdown)."""


def get_chunk(conn: sqlite3.Connection, chunk_id: str) -> dict:
    """Fetch chunk details by ID."""
    row = conn.execute(
        """SELECT id, title, content_type, grade_band, content, source_id, attribution
           FROM chunks WHERE id = ? AND stale = 0""",
        (chunk_id,),
    ).fetchone()
    return dict(row) if row else None


def get_standard(conn: sqlite3.Connection, standard_id: str, sg_db_path: str) -> str:
    """Fetch standard text from StandardGraph."""
    sg = sqlite3.connect(f"file:{sg_db_path}?mode=ro", uri=True)
    sg.row_factory = sqlite3.Row
    row = sg.execute(
        "SELECT standard_text FROM standards WHERE id = ? AND system = 'ccss'",
        (standard_id,),
    ).fetchone()
    sg.close()
    return row["standard_text"] if row else ""


def annotate_with_claude(
    client: anthropic.Anthropic,
    standard_id: str,
    standard_text: str,
    chunk: dict,
    model: str,
) -> dict:
    """Call Claude to generate a coverage note."""
    prompt = ANNOTATE_PROMPT.format(
        standard_id=standard_id,
        standard_text=standard_text,
        source=chunk["source_id"],
        chunk_title=chunk["title"],
        chunk_type=chunk["content_type"],
        chunk_grade=chunk["grade_band"] or "unspecified",
        chunk_content=chunk["content"][:1500] if chunk["content"] else "",
    )

    response = client.messages.create(
        model=model,
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )

    return {
        "success": True,
        "note": response.content[0].text.strip() if response.content else "",
    }


def run_annotation(
    db_path: str,
    sg_db_path: str,
    model: str = "claude-opus-4-8",
    batch_size: int = 10,
    dry_run: bool = False,
    max_rows: int = None,
    skip_existing: bool = True,
):
    """Main annotation loop."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Query alignments that should be annotated:
    # - High confidence (publisher_guide, human, llm_verified) always
    # - Embedding strong band (score >= 0.78)
    query = """
        SELECT a.id, a.chunk_id, a.standard_id, a.alignment_source, a.coverage_notes
        FROM standard_alignments a
        WHERE a.stale = 0
          AND (
            a.alignment_source IN ('publisher_guide', 'human', 'llm_verified')
            OR (a.alignment_source = 'embedding' AND a.alignment_score >= 0.78)
          )
    """

    if skip_existing:
        query += " AND (a.coverage_notes IS NULL OR a.coverage_notes = '')"

    rows = conn.execute(query).fetchall()

    if max_rows:
        rows = rows[:max_rows]

    print(f"Found {len(rows)} alignments to annotate")

    if not rows:
        print("Nothing to annotate. Exiting.")
        conn.close()
        return

    if dry_run:
        print(f"\n[DRY RUN] Would process {len(rows)} alignments. Sample:")
        for row in rows[:3]:
            print(f"  {row['standard_id']} ← {row['chunk_id']} ({row['alignment_source']})")
        conn.close()
        return

    # Initialize Claude client
    client = anthropic.Anthropic()

    # Track results
    results = {"annotated": 0, "errors": 0, "skipped": 0, "updates": []}

    # Process in batches
    for batch_start in tqdm(range(0, len(rows), batch_size), desc="Annotating"):
        batch = rows[batch_start : batch_start + batch_size]

        for row in batch:
            # Skip if already has a good note
            if row["coverage_notes"] and len(row["coverage_notes"]) > 20:
                results["skipped"] += 1
                continue

            chunk = get_chunk(conn, row["chunk_id"])
            if not chunk:
                results["errors"] += 1
                continue

            standard_text = get_standard(conn, row["standard_id"], sg_db_path)
            if not standard_text:
                results["errors"] += 1
                continue

            # Generate annotation with Claude
            result = annotate_with_claude(
                client, row["standard_id"], standard_text, chunk, model
            )

            if not result["success"] or not result["note"]:
                results["errors"] += 1
                continue

            note = result["note"]
            results["annotated"] += 1
            results["updates"].append(
                {
                    "id": row["id"],
                    "standard_id": row["standard_id"],
                    "chunk_id": row["chunk_id"],
                    "note": note,
                }
            )

            # Update DB
            conn.execute(
                "UPDATE standard_alignments SET coverage_notes = ? WHERE id = ?",
                (note, row["id"]),
            )

        conn.commit()

    # Summary
    print(f"\n{'='*60}")
    print(f"Annotation Summary ({model})")
    print(f"{'='*60}")
    print(f"Annotated: {results['annotated']}")
    print(f"Skipped (already annotated): {results['skipped']}")
    print(f"Errors: {results['errors']}")

    if results["updates"]:
        print(f"\nSample annotations:")
        for update in results["updates"][:2]:
            print(f"\n  {update['standard_id']} ← {update['chunk_id']}")
            print(f"  Note: {update['note']}")

    conn.close()
    return results


def main():
    p = argparse.ArgumentParser(description="Claude-based alignment annotation")
    p.add_argument("--db", default="data/oer_core.db", help="Path to OER DB")
    p.add_argument("--sg-db", default=str(Path.home() / ".standardgraph" / "common_core.db"))
    p.add_argument("--model", default="claude-opus-4-8", help="Claude model to use")
    p.add_argument("--batch-size", type=int, default=10, help="Batch size for processing")
    p.add_argument("--dry-run", action="store_true", help="Don't modify DB, just show what would happen")
    p.add_argument("--max-rows", type=int, default=None, help="Limit number of rows to process")
    p.add_argument(
        "--include-existing", action="store_true", help="Re-annotate even if notes exist"
    )
    args = p.parse_args()

    run_annotation(
        args.db,
        args.sg_db,
        model=args.model,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        max_rows=args.max_rows,
        skip_existing=not args.include_existing,
    )


if __name__ == "__main__":
    main()
