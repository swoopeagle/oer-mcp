"""Stage 4 — embed chunks with nomic-embed-text via Ollama.

Mirrors StandardGraph's embedding exactly (raw text, no task prefix, /api/embed
with {"model","input":[...]}) so chunk vectors share the standard vectors'
space — a precondition for the Stage 5 cosine alignment to be meaningful.
Idempotent: only embeds chunks missing an embedding.
"""

from __future__ import annotations

import sqlite3

import time

import httpx
import numpy as np

from oer_shared import config

# Smaller batches make steady progress (and resume cleanly) even when the
# Mac Studio is under competing load; embed is idempotent so a skipped batch
# is just retried on the next run.
BATCH_SIZE = 16
MAX_RETRIES = 3


def embed_texts(texts: list[str], client: httpx.Client) -> np.ndarray:
    # First call cold-loads the model on the Mac Studio (~70s observed); the
    # generous timeout absorbs that one-off load.
    resp = client.post(
        f"{config.OLLAMA_BASE_URL}/api/embed",
        json={"model": config.EMBED_MODEL, "input": texts},
        timeout=300.0,
    )
    resp.raise_for_status()
    return np.array(resp.json()["embeddings"], dtype=np.float32)


def _embed_input(title: str, content: str, limit: int = 2000) -> str:
    return f"{title}\n{content}"[:limit]


def embed_chunks(conn: sqlite3.Connection, *, schema: str = "main") -> int:
    """Embed all chunks in `schema` lacking an embedding. Returns count embedded."""
    pending = conn.execute(
        f"""SELECT c.id, c.title, c.content
            FROM {schema}.chunks c
            LEFT JOIN {schema}.chunk_embeddings e ON e.chunk_id = c.id
            WHERE e.chunk_id IS NULL AND c.stale = 0"""
    ).fetchall()
    if not pending:
        print("[embed] all chunks already embedded")
        return 0

    print(f"[embed] {len(pending)} chunks in batches of {BATCH_SIZE}")
    done = skipped = 0
    with httpx.Client() as client:
        for i in range(0, len(pending), BATCH_SIZE):
            batch = pending[i : i + BATCH_SIZE]
            texts = [_embed_input(r["title"], r["content"]) for r in batch]
            vecs = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    vecs = embed_texts(texts, client)
                    break
                except httpx.HTTPError as exc:
                    if attempt == MAX_RETRIES:
                        print(f"[embed][skip] batch @ {i} after {attempt} tries: {exc!r}")
                        skipped += len(batch)
                    else:
                        time.sleep(2 * attempt)
            if vecs is None:
                continue  # idempotent — picked up on the next run
            for row, vec in zip(batch, vecs):
                conn.execute(
                    """INSERT INTO chunk_embeddings (chunk_id, model, vector, dimensions)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(chunk_id) DO UPDATE SET
                         model=excluded.model, vector=excluded.vector,
                         dimensions=excluded.dimensions""",
                    (row["id"], config.EMBED_MODEL, vec.tobytes(), int(vec.shape[0])),
                )
            conn.commit()
            done += len(batch)
            print(f"[embed] {done}/{len(pending)} (dim={vecs.shape[1]})")
    if skipped:
        print(f"[embed] {skipped} chunks skipped (timeouts) — re-run to resume")
    return done
