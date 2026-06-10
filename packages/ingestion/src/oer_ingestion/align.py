"""Stage 5 — compute chunk → CCSS standard alignments.

Phase 1 is embedding-only (Pass 2): neither OpenStax nor Khan-via-Kolibri
carries CCSS tags (S2, S3), so there is no publisher-guide pass yet — CK-12
will supply that later (D17). Each chunk's embedding is compared by cosine
similarity against StandardGraph's CCSS standard embeddings (read-only); top
matches above threshold are inserted.

The StandardGraph DB is a build-time-only dependency (D2): after this stage
the alignment table is baked in and no runtime SG call is needed.

Thresholds (PRD §9 Stage 5):
  >= 0.85  insert, flag for the annotate stage
  0.65..   insert, no annotation
  < 0.65   drop
Human-verified rows (alignment_source='human') are never overwritten.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

ANNOTATE_THRESHOLD = 0.85
INSERT_THRESHOLD = 0.65
TOP_K = 5  # max standards aligned per chunk


def _load_standard_matrix(sg_db: Path) -> tuple[list[str], np.ndarray]:
    """Return (standard_ids, normalized matrix [N,768]) for CCSS standards."""
    conn = sqlite3.connect(f"file:{sg_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT e.standard_id, e.vector
           FROM embeddings e JOIN standards s ON s.id = e.standard_id
           WHERE s.system = 'ccss'"""
    ).fetchall()
    conn.close()
    if not rows:
        raise RuntimeError(f"no CCSS embeddings in StandardGraph DB at {sg_db}")
    ids = [r["standard_id"] for r in rows]
    mat = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
    mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
    return ids, mat


def align_chunks(
    conn: sqlite3.Connection,
    sg_db: str | Path,
    *,
    schema: str = "main",
    top_k: int = TOP_K,
) -> dict[str, int]:
    """Align every embedded chunk in `schema` against CCSS. Returns counts."""
    std_ids, std_mat = _load_standard_matrix(Path(sg_db))

    rows = conn.execute(
        f"""SELECT ce.chunk_id, ce.vector
            FROM {schema}.chunk_embeddings ce
            JOIN {schema}.chunks c ON c.id = ce.chunk_id
            WHERE c.stale = 0"""
    ).fetchall()
    if not rows:
        print("[align] no embedded chunks")
        return {"chunks": 0, "alignments": 0, "to_annotate": 0}

    inserted = to_annotate = 0
    for r in rows:
        vec = np.frombuffer(r["vector"], dtype=np.float32)
        vec = vec / (np.linalg.norm(vec) + 1e-9)
        sims = std_mat @ vec  # cosine, both normalized
        top = np.argsort(-sims)[:top_k]
        for idx in top:
            score = float(sims[idx])
            if score < INSERT_THRESHOLD:
                break  # sorted desc — nothing better remains
            flag = 1 if score >= ANNOTATE_THRESHOLD else 0
            # never clobber a human-verified row
            existing = conn.execute(
                f"""SELECT alignment_source FROM {schema}.standard_alignments
                    WHERE chunk_id=? AND standard_id=?""",
                (r["chunk_id"], std_ids[idx]),
            ).fetchone()
            if existing and existing["alignment_source"] == "human":
                continue
            conn.execute(
                f"""INSERT INTO {schema}.standard_alignments
                      (chunk_id, standard_id, standard_system, alignment_score,
                       alignment_source, flagged_for_review)
                    VALUES (?, ?, 'ccss', ?, 'embedding', ?)
                    ON CONFLICT(chunk_id, standard_id) DO UPDATE SET
                      alignment_score=excluded.alignment_score,
                      flagged_for_review=excluded.flagged_for_review,
                      stale=0
                    WHERE standard_alignments.alignment_source != 'human'""",
                (r["chunk_id"], std_ids[idx], score, flag),
            )
            inserted += 1
            to_annotate += flag
    conn.commit()
    print(
        f"[align] {len(rows)} chunks → {inserted} alignments "
        f"({to_annotate} ≥{ANNOTATE_THRESHOLD} flagged for annotation)"
    )
    return {"chunks": len(rows), "alignments": inserted, "to_annotate": to_annotate}
