"""Apply Claude-authored alignment verifications from a JSON seed.

The gemma `verify` stage judges borderline embedding alignments live via Ollama;
this loader instead applies curated, version-controlled judgments authored by
Claude (higher quality on the standards that matter). Each judgment targets one
chunk<->standard alignment:

  verdict='verified' -> alignment_source upgraded to 'llm_verified' + coverage note
  verdict='reject'   -> row marked stale (a false positive the cosine over-rated)

Human/publisher_guide alignments are never downgraded. Idempotent.

Usage:
    uv run python -m oer_ingestion.verify_seed --db data/oer_core.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

_DEFAULT_FILE = Path(__file__).parent / "data" / "verified_alignments.json"


def load_verifications(conn: sqlite3.Connection, seed_file: Path | str = _DEFAULT_FILE) -> dict[str, int]:
    """Apply verifications from a JSON seed. Returns {'verified','rejected','missing'}."""
    data = json.loads(Path(seed_file).read_text())
    rows = data if isinstance(data, list) else data.get("verifications", [])
    verified = rejected = missing = 0
    for r in rows:
        key = (r["chunk_id"], r["standard_id"])
        exists = conn.execute(
            "SELECT 1 FROM standard_alignments WHERE chunk_id=? AND standard_id=?", key
        ).fetchone()
        if not exists:
            missing += 1
            continue
        if r["verdict"] == "verified":
            # Never downgrade a stronger, human/publisher-sourced tier.
            conn.execute(
                "UPDATE standard_alignments SET alignment_source='llm_verified', "
                "coverage_notes=?, stale=0 WHERE chunk_id=? AND standard_id=? "
                "AND alignment_source NOT IN ('human','publisher_guide')",
                (r["note"], *key),
            )
            verified += 1
        elif r["verdict"] == "reject":
            conn.execute(
                "UPDATE standard_alignments SET stale=1, coverage_notes=? "
                "WHERE chunk_id=? AND standard_id=?",
                (r["note"], *key),
            )
            rejected += 1
        else:
            raise ValueError(f"unknown verdict {r['verdict']!r} (expected verified|reject)")
    conn.commit()
    return {"verified": verified, "rejected": rejected, "missing": missing}


def main() -> None:
    from oer_shared.db import connect

    p = argparse.ArgumentParser(description="Apply Claude alignment verifications")
    p.add_argument("--db", required=True)
    p.add_argument("--file", default=str(_DEFAULT_FILE))
    args = p.parse_args()
    conn = connect(args.db, create=True)
    counts = load_verifications(conn, args.file)
    conn.close()
    print(f"[verify_seed] verified={counts['verified']} rejected={counts['rejected']} "
          f"missing={counts['missing']}")


if __name__ == "__main__":
    main()
