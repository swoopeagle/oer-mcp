"""Stage 6b — gemma-verified alignment upgrade (D20).

For each flagged high-confidence embedding alignment, ask gemma a focused
yes/no: does this section actually teach this standard? Confirmed alignments are
promoted to alignment_source='llm_verified' at a fixed high score, so the query
layer ranks them above raw embedding matches. Replaces the missing publisher-
guide seed (no accessible source carries CCSS tags — S2/S3/S4).

Build-time only; needs Ollama + StandardGraph. Idempotent (skips rows already
llm_verified) and resilient (retry/skip per item, like annotate).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import httpx

from oer_shared import config
from oer_shared.ollama_client import complete

VERIFIED_SCORE = 0.90
MAX_RETRIES = 3
GEN_TIMEOUT = 300.0  # 5 min: absorbs cold load + queue wait when 2-3 workers share one endpoint

PROMPT = """You are checking curriculum alignment. Reply with exactly one word: YES or NO.

Standard {sid}: {stext}

Does the following content section TEACH or DIRECTLY PRACTICE this standard
(not merely mention a related idea)?

Title: {title}
Content: {content}

Answer (YES or NO):"""


def _ask(prompt: str, client: httpx.Client) -> bool | None:
    # No num_predict cap: some hosts/models (e.g. the Windows gemma4:12b on
    # /api/chat) return EMPTY when the cap is set. An unclear/empty answer maps
    # to None (skip), never to a rejection — a flaky endpoint must not be able to
    # falsely reject and corrupt the corpus.
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            ans = complete(prompt, config.ANNOTATE_MODEL, client,
                           temperature=0, timeout=GEN_TIMEOUT)
            u = ans.strip().upper()
            if u.startswith("YES"):
                return True
            if u.startswith("NO"):
                return False
            return None  # empty/unclear → skip, leave flagged for another pass
        except (httpx.HTTPError, httpx.TransportError):
            if attempt < MAX_RETRIES:
                time.sleep(2 * attempt)
    return None


def verify(
    conn: sqlite3.Connection, sg_db: str | Path, *, schema: str = "main",
    limit: int | None = None, shard: tuple[int, int] | None = None,
) -> dict:
    """Verify flagged embedding alignments; promote confirmed to llm_verified."""
    sg = sqlite3.connect(f"file:{sg_db}?mode=ro", uri=True)
    sg.row_factory = sqlite3.Row
    q = f"""SELECT a.id, a.standard_id, c.title, c.content
            FROM {schema}.standard_alignments a
            JOIN {schema}.chunks c ON c.id = a.chunk_id
            WHERE a.flagged_for_review = 1 AND a.alignment_source = 'embedding'
              AND c.stale = 0"""
    if shard is not None:
        q += f" AND a.id % {int(shard[1])} = {int(shard[0])}"
    if limit:
        q += f" LIMIT {int(limit)}"
    pending = conn.execute(q).fetchall()
    if not pending:
        sg.close()
        print("[verify] nothing flagged to verify")
        return {"checked": 0, "promoted": 0, "rejected": 0, "skipped": 0}

    print(f"[verify] {len(pending)} flagged alignments via {config.ANNOTATE_MODEL}")
    promoted = rejected = skipped = 0
    stext_cache: dict[str, str] = {}
    with httpx.Client() as client:
        for i, row in enumerate(pending, 1):
            sid = row["standard_id"]
            if sid not in stext_cache:
                r = sg.execute(
                    "SELECT standard_text FROM standards WHERE id=?",
                    (sid,),
                ).fetchone()
                stext_cache[sid] = r["standard_text"] if r else ""
            verdict = _ask(
                PROMPT.format(sid=sid, stext=stext_cache[sid],
                              title=row["title"], content=row["content"][:1500]),
                client,
            )
            if verdict is None:
                skipped += 1
                continue
            if verdict:
                conn.execute(
                    f"UPDATE {schema}.standard_alignments "
                    "SET alignment_source='llm_verified', alignment_score=? WHERE id=?",
                    (VERIFIED_SCORE, row["id"]),
                )
                promoted += 1
            else:
                # leave as embedding but unflag so we don't re-check it
                conn.execute(
                    f"UPDATE {schema}.standard_alignments "
                    "SET flagged_for_review=0 WHERE id=?",
                    (row["id"],),
                )
                rejected += 1
            conn.commit()
            if i % 10 == 0:
                print(f"[verify] {i}/{len(pending)} (promoted {promoted}, rejected {rejected})")
    sg.close()
    print(f"[verify] promoted {promoted}, rejected {rejected}, skipped {skipped}")
    return {"checked": len(pending), "promoted": promoted,
            "rejected": rejected, "skipped": skipped}
