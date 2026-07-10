"""Stage 5 — compute chunk → CCSS standard alignments.

Phase 1 is embedding-only (Pass 2): neither OpenStax nor Khan-via-Kolibri
carries CCSS tags (S2, S3), so there is no publisher-guide pass yet — CK-12
will supply that later (D17). Each chunk's embedding is compared by cosine
similarity against StandardGraph's CCSS standard embeddings (read-only).

The StandardGraph DB is a build-time-only dependency (D2): after this stage
the alignment table is baked in and no runtime SG call is needed.

M1-checkpoint calibration (docs/spikes/M1-alignment-checkpoint.md):
  1. bands recalibrated for embedding scores (oer_shared.coverage); annotate
     flag at EMBED_ANNOTATE_THRESHOLD (0.78), not 0.85 — embedding cosine never
     reaches 0.85 here.
  2. generic exercise groups (Writing Exercises, Self Check) are excluded from
     alignment — they're semantically generic and over-match.
  3. a grade-distance penalty demotes cross-grade matches (a grade 6–8 section
     should not rank against a Kindergarten standard).
Human-verified rows (alignment_source='human') are never overwritten.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from oer_shared.coverage import EMBED_ANNOTATE_THRESHOLD

from .grades import grade_distance

INSERT_THRESHOLD = 0.65
TOP_K = 5  # max standards aligned per chunk
GRADE_PENALTY = 0.02  # score points subtracted per grade-year out of band

# Exercise groups too generic to align well (M1 checkpoint #2). Matched against
# the trailing group label in the chunk title (format "{module} — {group}").
GENERIC_EXERCISE_GROUPS = ("Writing Exercises", "Self Check")


def _is_generic_exercise(content_type: str, title: str) -> bool:
    return content_type == "exercise_set" and any(
        title.rstrip().endswith(g) for g in GENERIC_EXERCISE_GROUPS
    )


def _load_standards(sg_db: Path, system: str) -> tuple[list[str], list[str | None], np.ndarray]:
    """Return (ids, grades, normalized matrix [N,768]) for the given SG standard system."""
    conn = sqlite3.connect(f"file:{sg_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT e.standard_id, e.vector, s.grade
           FROM embeddings e JOIN standards s ON s.id = e.standard_id
           WHERE s.system = ?""",
        (system,),
    ).fetchall()
    conn.close()
    if not rows:
        raise RuntimeError(f"no {system!r} embeddings in StandardGraph DB at {sg_db}")
    ids = [r["standard_id"] for r in rows]
    grades = [r["grade"] for r in rows]
    mat = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
    mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
    return ids, grades, mat


def align_chunks(
    conn: sqlite3.Connection,
    sg_db: str | Path,
    *,
    schema: str = "main",
    top_k: int = TOP_K,
    system: str = "ccss",
    book_ids: list[str] | None = None,
) -> dict[str, int]:
    """Align embedded chunks in `schema` against the given SG standard system
    (default 'ccss' for existing math content). Once a DB holds content for
    more than one subject/system, pass `book_ids` to scope alignment to the
    books that actually belong to `system` — otherwise unrelated chunks (e.g.
    Khan math transcripts) get spurious alignments purely from stray embedding
    similarity. Returns counts."""
    std_ids, std_grades, std_mat = _load_standards(Path(sg_db), system)

    book_filter = ""
    params: list[str] = []
    if book_ids:
        placeholders = ",".join("?" * len(book_ids))
        book_filter = f" AND c.book_id IN ({placeholders})"
        params = list(book_ids)

    rows = conn.execute(
        f"""SELECT ce.chunk_id, ce.vector, c.grade_band, c.content_type, c.title
            FROM {schema}.chunk_embeddings ce
            JOIN {schema}.chunks c ON c.id = ce.chunk_id
            WHERE c.stale = 0{book_filter}""",
        params,
    ).fetchall()
    if not rows:
        print("[align] no embedded chunks")
        return {"chunks": 0, "alignments": 0, "to_annotate": 0, "skipped": 0}

    inserted = to_annotate = skipped = 0
    for r in rows:
        if _is_generic_exercise(r["content_type"], r["title"]):
            skipped += 1
            continue
        vec = np.frombuffer(r["vector"], dtype=np.float32)
        vec = vec / (np.linalg.norm(vec) + 1e-9)
        sims = std_mat @ vec  # cosine, both normalized

        # grade-distance penalty (fix #3): demote standards far from the chunk's
        # grade band, then rank on the adjusted score.
        adjusted = sims.copy()
        if r["grade_band"]:
            for j in range(len(std_ids)):
                d = grade_distance(r["grade_band"], std_grades[j])
                if d:
                    adjusted[j] -= GRADE_PENALTY * d

        for idx in np.argsort(-adjusted)[:top_k]:
            score = float(adjusted[idx])
            if score < INSERT_THRESHOLD:
                break  # sorted desc — nothing better remains
            flag = 1 if score >= EMBED_ANNOTATE_THRESHOLD else 0
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
                    VALUES (?, ?, ?, ?, 'embedding', ?)
                    ON CONFLICT(chunk_id, standard_id) DO UPDATE SET
                      alignment_score=excluded.alignment_score,
                      flagged_for_review=excluded.flagged_for_review,
                      stale=0
                    WHERE standard_alignments.alignment_source != 'human'""",
                (r["chunk_id"], std_ids[idx], system, round(score, 4), flag),
            )
            inserted += 1
            to_annotate += flag
    conn.commit()
    print(
        f"[align] {len(rows)} chunks → {inserted} alignments "
        f"({to_annotate} ≥{EMBED_ANNOTATE_THRESHOLD} flagged; "
        f"{skipped} generic-exercise chunks skipped)"
    )
    return {
        "chunks": len(rows),
        "alignments": inserted,
        "to_annotate": to_annotate,
        "skipped": skipped,
    }
