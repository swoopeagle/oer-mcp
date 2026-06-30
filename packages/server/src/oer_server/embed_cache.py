"""In-memory normalized embedding cache for semantic search.

Loaded once per (connection, schema) pair on the first semantic search call;
thereafter cosine similarity is a pure NumPy matmul with no SQLite I/O.
"""

from __future__ import annotations

import sqlite3

import numpy as np

# (id(conn), schema) → (chunk_ids, normalized_matrix, id_to_idx)
_CACHE: dict[tuple[int, str], tuple[list[str], np.ndarray, dict[str, int]]] = {}


def get_matrix(
    conn: sqlite3.Connection, schema: str
) -> tuple[list[str], np.ndarray, dict[str, int]]:
    """Return (ids, norm_matrix, id_to_idx) for the schema, loading on first call.

    Rows of norm_matrix are L2-normalized float32 vectors aligned to ids.
    id_to_idx maps chunk_id → row index in the matrix.
    """
    key = (id(conn), schema)
    if key not in _CACHE:
        rows = conn.execute(
            f"SELECT chunk_id, vector FROM {schema}.chunk_embeddings"
        ).fetchall()
        if not rows:
            _CACHE[key] = ([], np.empty((0, 768), dtype=np.float32), {})
        else:
            ids = [r["chunk_id"] for r in rows]
            mat = np.vstack(
                [np.frombuffer(r["vector"], dtype=np.float32) for r in rows]
            )
            mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
            id_to_idx: dict[str, int] = {cid: i for i, cid in enumerate(ids)}
            _CACHE[key] = (ids, mat, id_to_idx)
    return _CACHE[key]


def clear() -> None:
    """Empty the cache (used in tests and after schema changes)."""
    _CACHE.clear()
