"""Exam crosswalk loader — populate exam_crosswalks from a JSON seed file.

The crosswalk maps CCSS standard prefixes to high-stakes exam skill domains.
It is source-of-truth reference data (from College Board / ACT alignment
documents) and lives in the core DB's exam_crosswalks table.

Usage:
    uv run python -m oer_ingestion.crosswalk \
        --db data/oer_core.db \
        --file packages/ingestion/src/oer_ingestion/data/exam_crosswalks.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_FILE = Path(__file__).parent / "data" / "exam_crosswalks.json"


def _strip_jsonc_comments(text: str) -> str:
    """Drop full-line ``//`` comments so the seed file can carry section headers
    and source citations. Conservative on purpose: only whole-line comments are
    removed (leading whitespace allowed), never trailing ``//`` — that would
    corrupt ``https://`` inside string values like source_url."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )


def load_crosswalks(conn: sqlite3.Connection, crosswalk_file: Path | str) -> dict[str, int]:
    """Upsert crosswalk rows from a JSON(C) file into exam_crosswalks.
    Returns {'added', 'updated'} counts."""
    data = json.loads(_strip_jsonc_comments(Path(crosswalk_file).read_text()))
    rows = data if isinstance(data, list) else data.get("crosswalks", [])
    added = updated = 0
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        existing = conn.execute(
            "SELECT 1 FROM exam_crosswalks WHERE standard_id=? AND exam_series=?",
            (row["standard_id"], row["exam_series"]),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE exam_crosswalks
                     SET skill_domain=?, notes=?, source_url=?
                   WHERE standard_id=? AND exam_series=?""",
                (row["skill_domain"], row.get("notes"), row["source_url"],
                 row["standard_id"], row["exam_series"]),
            )
            updated += 1
        else:
            conn.execute(
                """INSERT INTO exam_crosswalks
                     (standard_id, exam_series, skill_domain, notes, source_url, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (row["standard_id"], row["exam_series"], row["skill_domain"],
                 row.get("notes"), row["source_url"], now),
            )
            added += 1
    conn.commit()
    return {"added": added, "updated": updated}


def main() -> None:
    p = argparse.ArgumentParser(description="Load exam crosswalk data into the core DB")
    p.add_argument("--db", required=True, help="path to oer_core.db")
    p.add_argument("--file", default=str(_DEFAULT_FILE),
                   help="crosswalk JSON file (default: built-in seed)")
    args = p.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    counts = load_crosswalks(conn, args.file)
    conn.close()
    print(f"[crosswalk] added={counts['added']} updated={counts['updated']}")


if __name__ == "__main__":
    main()
