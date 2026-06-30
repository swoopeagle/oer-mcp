"""embed_cache: normalized embedding matrix and filtered semantic search regression."""

import numpy as np
import pytest

from oer_server import embed_cache, queries
from oer_shared.db import connect


def _make_vec(dims: int = 768, idx: int = 0) -> np.ndarray:
    """Unit-like float32 vector with 1.0 at position idx, 0 elsewhere."""
    v = np.zeros(dims, dtype=np.float32)
    v[idx] = 1.0
    return v


def _book(conn):
    conn.execute(
        "INSERT INTO main.sources VALUES ('src','Test Source','CC BY 4.0','u',"
        "'https://example.com','2026-06-10',datetime('now'))"
    )
    conn.execute(
        "INSERT INTO main.books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES ('b','src','Book','mathematics','6-8','CC BY 4.0','u')"
    )


def _chunk(conn, cid, ctype="exposition"):
    conn.execute(
        "INSERT INTO main.chunks (id, book_id, source_id, title, content, content_type,"
        " word_count, source_url, attribution, last_verified)"
        " VALUES (?,'b','src','title','body text',?,10,'u','attr','2026-06-10')",
        (cid, ctype),
    )


def _embed(conn, cid, vec: np.ndarray):
    conn.execute(
        "INSERT INTO main.chunk_embeddings (chunk_id, model, vector, dimensions)"
        " VALUES (?, 'nomic-embed-text', ?, ?)",
        (cid, vec.tobytes(), vec.shape[0]),
    )


@pytest.fixture(autouse=True)
def clear_cache():
    embed_cache.clear()
    yield
    embed_cache.clear()


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "core.db", create=True)
    _book(c)
    yield c
    c.close()


# ── cache unit tests ────────────────────────────────────────────────────────


def test_cache_populated_after_first_call(conn):
    """First get_matrix call loads the cache; second call returns the same objects."""
    _chunk(conn, "c1")
    _embed(conn, "c1", _make_vec(idx=0))
    conn.commit()

    assert (id(conn), "main") not in embed_cache._CACHE
    ids, mat, idx_map = embed_cache.get_matrix(conn, "main")
    assert (id(conn), "main") in embed_cache._CACHE
    assert "c1" in ids
    assert idx_map["c1"] == 0
    # Cached objects are reused — not reloaded.
    ids2, mat2, _ = embed_cache.get_matrix(conn, "main")
    assert ids2 is ids
    assert mat2 is mat


def test_matrix_is_l2_normalized(conn):
    """Vectors in the cache are L2-normalized regardless of original scale."""
    _chunk(conn, "c1")
    unnormed = np.array([3.0, 4.0] + [0.0] * 766, dtype=np.float32)  # norm=5
    _embed(conn, "c1", unnormed)
    conn.commit()

    _, mat, _ = embed_cache.get_matrix(conn, "main")
    np.testing.assert_allclose(np.linalg.norm(mat, axis=1), 1.0, atol=1e-5)


def test_empty_schema_returns_empty_structures(conn):
    """A schema with no embeddings returns empty ids/matrix/map."""
    conn.commit()  # no embeddings inserted
    ids, mat, idx_map = embed_cache.get_matrix(conn, "main")
    assert ids == []
    assert mat.shape[0] == 0
    assert idx_map == {}


def test_clear_empties_cache(conn):
    """clear() removes all entries so the next call reloads from DB."""
    _chunk(conn, "c1")
    _embed(conn, "c1", _make_vec(idx=0))
    conn.commit()

    embed_cache.get_matrix(conn, "main")
    assert embed_cache._CACHE
    embed_cache.clear()
    assert not embed_cache._CACHE


# ── semantic search regression tests ────────────────────────────────────────


def test_search_content_returns_hybrid_mode(conn):
    """search_content uses 'hybrid' mode when embed_query succeeds."""
    _chunk(conn, "c1")
    _embed(conn, "c1", _make_vec(idx=0))
    conn.commit()

    res = queries.search_content(conn, "test", embed_query=lambda _: _make_vec(idx=0))
    assert res["search_mode"] == "hybrid"


def test_search_content_identical_results_on_cache_hit(conn):
    """Two consecutive search_content calls return identical results (cache used on 2nd)."""
    _chunk(conn, "c1"); _embed(conn, "c1", _make_vec(idx=0))
    _chunk(conn, "c2"); _embed(conn, "c2", _make_vec(idx=1))
    conn.commit()

    qvec = _make_vec(idx=0)
    res_a = queries.search_content(conn, "body", embed_query=lambda _: qvec)
    res_b = queries.search_content(conn, "body", embed_query=lambda _: qvec)
    assert res_a["results"] == res_b["results"]


def test_search_content_top_result_matches_query_direction(conn):
    """The chunk whose vector is closest to the query vector ranks first."""
    _chunk(conn, "c1"); _embed(conn, "c1", _make_vec(idx=0))  # aligns with dim-0 query
    _chunk(conn, "c2"); _embed(conn, "c2", _make_vec(idx=1))  # aligns with dim-1
    conn.commit()

    qvec = _make_vec(idx=0)
    res = queries.search_content(conn, "body", embed_query=lambda _: qvec)
    ids = [r["chunk_id"] for r in res["results"]]
    assert ids[0] == "c1"


def test_search_content_filter_respected_via_cache(conn):
    """Filtered search only returns chunks matching the filter, even from cached matrix."""
    _chunk(conn, "c1", "exposition");    _embed(conn, "c1", _make_vec(idx=0))
    _chunk(conn, "c2", "worked_example"); _embed(conn, "c2", _make_vec(idx=0))
    conn.commit()

    # Warm the cache first.
    embed_cache.get_matrix(conn, "main")

    qvec = _make_vec(idx=0)
    res = queries.search_content(
        conn, "body", embed_query=lambda _: qvec, content_type="worked_example"
    )
    ids = [r["chunk_id"] for r in res["results"]]
    assert "c2" in ids
    assert "c1" not in ids


def test_search_content_stale_chunk_excluded_from_cache_path(conn):
    """Stale chunks are excluded even when the matrix is already cached."""
    _chunk(conn, "c1"); _embed(conn, "c1", _make_vec(idx=0))
    _chunk(conn, "c2"); _embed(conn, "c2", _make_vec(idx=0))
    conn.execute("UPDATE main.chunks SET stale=1 WHERE id='c2'")
    conn.commit()

    embed_cache.get_matrix(conn, "main")  # warms cache (both c1 and c2 in matrix)

    qvec = _make_vec(idx=0)
    res = queries.search_content(conn, "body", embed_query=lambda _: qvec)
    ids = [r["chunk_id"] for r in res["results"]]
    assert "c2" not in ids
    assert "c1" in ids
