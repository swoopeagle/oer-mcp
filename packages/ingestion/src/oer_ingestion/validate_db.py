"""Stage 7 — acceptance validation (PRD §9/§13). Runs structural integrity
checks plus Phase 1 acceptance criteria against a built database. Structural
checks are GPU-free; embedding/alignment completeness checks report current
state. Exit non-zero on hard failures so the pipeline fails loudly.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hard: bool = True  # hard failures fail the pipeline; soft ones just warn


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks if c.hard)

    def add(self, name, ok, detail, hard=True):
        self.checks.append(Check(name, ok, detail, hard))


def validate(conn: sqlite3.Connection, *, min_chunks: int = 5000) -> Report:
    r = Report()

    chunks = conn.execute("SELECT COUNT(*) FROM chunks WHERE stale=0").fetchone()[0]
    r.add("min_chunks", chunks >= min_chunks, f"{chunks} chunks (need ≥{min_chunks})")

    null_content = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE content IS NULL OR trim(content)=''"
    ).fetchone()[0]
    r.add("no_null_content", null_content == 0, f"{null_content} empty-content chunks")

    null_attr = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE attribution IS NULL OR trim(attribution)=''"
    ).fetchone()[0]
    r.add("attribution_present", null_attr == 0, f"{null_attr} chunks missing attribution")

    # FTS5 keyword search returns hits for a common term
    fts = conn.execute(
        "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'fraction'"
    ).fetchone()[0]
    r.add("fts_searchable", fts >= 10, f"'fraction' → {fts} FTS hits (need ≥10)")

    # embedding completeness (soft — gated on Ollama capacity at build time)
    embedded = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
    r.add("embeddings_complete", embedded == chunks,
          f"{embedded}/{chunks} chunks embedded", hard=False)

    # alignment coverage (soft until embeddings complete)
    aligned_std = conn.execute(
        "SELECT COUNT(DISTINCT standard_id) FROM standard_alignments WHERE stale=0"
    ).fetchone()[0]
    r.add("standards_aligned", aligned_std >= 200,
          f"{aligned_std} distinct CCSS standards aligned (target ≥200)", hard=False)

    # spot check: a well-covered standard returns content (soft — needs alignments)
    ns1 = conn.execute(
        "SELECT COUNT(*) FROM standard_alignments WHERE standard_id='CCSS.MATH.6.NS.1' AND stale=0"
    ).fetchone()[0]
    r.add("spot_6ns1", ns1 >= 2,
          f"6.NS.1 (divide fractions) → {ns1} aligned chunks", hard=False)

    return r


def print_report(r: Report) -> None:
    for c in r.checks:
        mark = "✓" if c.ok else ("✗" if c.hard else "○")
        tag = "" if c.hard else " (soft)"
        print(f"  {mark} {c.name}{tag}: {c.detail}")
    print(f"\n{'PASS' if r.passed else 'FAIL'} (hard checks)")
