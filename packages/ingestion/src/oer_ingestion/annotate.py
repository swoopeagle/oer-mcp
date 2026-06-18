"""Stage 6 — generate coverage_notes for high-confidence alignments via gemma.

Runs only at build time, only on alignments flagged by Stage 5
(flagged_for_review=1, i.e. embedding score ≥ EMBED_ANNOTATE_THRESHOLD).
Small targeted prompt; needs StandardGraph (read-only) for standard text +
sub-standards. Idempotent: skips alignments that already have coverage_notes.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import httpx

from oer_shared import config
from oer_shared.ollama_client import complete

MAX_RETRIES = 3
GEN_TIMEOUT = 300.0  # contended Studio gemma can be slow; generous per-call cap

PROMPT = """Given this curriculum standard:
  ID: {sid}
  Text: {stext}
  Sub-standards: {subs}

And this OER content section:
  Title: {title}
  Content: {content}

Describe in 1-2 sentences which sub-standards this section covers well, and
which it treats lightly or skips. Be specific about sub-standard letters.
Return only the description. No preamble."""


def _standard_context(sg: sqlite3.Connection, sid: str) -> tuple[str, str] | None:
    row = sg.execute(
        "SELECT standard_text FROM standards WHERE id=? AND system='ccss'", (sid,)
    ).fetchone()
    if row is None:
        return None
    subs = sg.execute(
        "SELECT id, text FROM sub_standards WHERE parent_id=? ORDER BY position", (sid,)
    ).fetchall()
    sub_str = "; ".join(f"{s['id'].split('.')[-1]}: {s['text']}" for s in subs) or "(none)"
    return row["standard_text"], sub_str


def _gemma(prompt: str, client: httpx.Client) -> str | None:
    """One generation with retry/backoff. Returns None if it keeps failing so
    the caller can skip the item (idempotent — picked up on the next run)."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return complete(prompt, config.ANNOTATE_MODEL, client, timeout=GEN_TIMEOUT)
        except httpx.HTTPError:
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
    return None


def annotate(
    conn: sqlite3.Connection, sg_db: str | Path, *, schema: str = "main",
    limit: int | None = None, shard: tuple[int, int] | None = None,
) -> int:
    """Annotate flagged alignments lacking coverage_notes. Returns count written.
    shard=(n, m) processes only rows where id % m == n — lets independent workers
    (e.g. Studio + Mini on different Ollama hosts) split the work without overlap."""
    sg = sqlite3.connect(f"file:{sg_db}?mode=ro", uri=True)
    sg.row_factory = sqlite3.Row
    # Annotate any flagged alignment lacking notes, whether still 'embedding' or
    # already promoted to 'llm_verified' by the verify stage (order of stages
    # differs per source: OpenStax annotated pre-verify, Khan post-verify).
    q = f"""SELECT a.id, a.standard_id, a.chunk_id, c.title, c.content
            FROM {schema}.standard_alignments a
            JOIN {schema}.chunks c ON c.id = a.chunk_id
            WHERE a.flagged_for_review = 1 AND a.coverage_notes IS NULL
              AND a.alignment_source IN ('embedding','llm_verified')"""
    if shard is not None:
        n, m = shard
        q += f" AND a.id % {int(m)} = {int(n)}"
    if limit:
        q += f" LIMIT {int(limit)}"
    pending = conn.execute(q).fetchall()
    if not pending:
        print("[annotate] nothing flagged to annotate")
        sg.close()
        return 0

    print(f"[annotate] {len(pending)} flagged alignments via {config.ANNOTATE_MODEL}")
    done = skipped = 0
    with httpx.Client() as client:
        for i, row in enumerate(pending, 1):
            ctx = _standard_context(sg, row["standard_id"])
            if ctx is None:
                continue
            stext, subs = ctx
            note = _gemma(
                PROMPT.format(sid=row["standard_id"], stext=stext, subs=subs,
                              title=row["title"], content=row["content"][:1500]),
                client,
            )
            if note is None:  # persistent failure — leave NULL, resume next run
                skipped += 1
                continue
            conn.execute(
                f"UPDATE {schema}.standard_alignments SET coverage_notes=? WHERE id=?",
                (note, row["id"]),
            )
            conn.commit()
            done += 1
            if i % 10 == 0:
                print(f"[annotate] {i}/{len(pending)} (wrote {done}, skipped {skipped})")
    sg.close()
    print(f"[annotate] wrote {done} coverage notes, skipped {skipped}")
    return done
