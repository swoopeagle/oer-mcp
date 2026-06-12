"""M1 alignment-quality checkpoint (BUILD_PLAN standing risk #1).

Embedding-only alignment is all we have for OpenStax (S3) — so before scaling
beyond one book, eyeball whether the top chunks for known standards are
actually on-topic. Run after embed-align. Prints, for a handful of CCSS
standards, the top aligned chunks with scores.

Usage:
    OER_CORE_DB_PATH=data/oer_core.db uv run python scripts/m1_checkpoint.py
"""

import sqlite3
import sys
from pathlib import Path

from oer_shared import config

# Standards a Prealgebra book should cover well, with a human-language gloss.
# NOTE: StandardGraph CCSS IDs omit cluster letters (6.RP.3, not 6.RP.A.3) —
# alignments use SG's IDs verbatim, so probes must too.
PROBES = [
    ("CCSS.MATH.6.RP.3", "ratio & rate reasoning"),
    ("CCSS.MATH.6.NS.1", "dividing fractions by fractions"),
    ("CCSS.MATH.6.NS.5", "integers / number line"),
    ("CCSS.MATH.6.NS.6", "rational numbers / number line"),
    ("CCSS.MATH.6.EE.1", "whole-number exponents"),
]


def main() -> int:
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else config.CORE_DB_PATH
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    total = conn.execute("SELECT COUNT(*) FROM standard_alignments").fetchone()[0]
    distinct = conn.execute(
        "SELECT COUNT(DISTINCT standard_id) FROM standard_alignments"
    ).fetchone()[0]
    strong = conn.execute(
        "SELECT COUNT(*) FROM standard_alignments WHERE alignment_score >= 0.85"
    ).fetchone()[0]
    print(f"alignments: {total} | distinct CCSS standards: {distinct} | ≥0.85: {strong}\n")

    for sid, gloss in PROBES:
        print(f"━━ {sid}  ({gloss})")
        rows = conn.execute(
            """SELECT c.title, c.content_type, a.alignment_score
               FROM standard_alignments a JOIN chunks c ON c.id = a.chunk_id
               WHERE a.standard_id = ?
               ORDER BY a.alignment_score DESC LIMIT 3""",
            (sid,),
        ).fetchall()
        if not rows:
            print("   (no aligned chunks)\n")
            continue
        for r in rows:
            print(f"   {r['alignment_score']:.3f}  [{r['content_type']:14}] {r['title'][:70]}")
        print()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
