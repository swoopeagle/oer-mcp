"""search_content — FTS5 fallback, hybrid fusion, filters, graceful degradation.
Uses a seeded DB and fake embedders so it never touches Ollama (D13)."""

import numpy as np
import pytest

from oer_server import queries
from oer_shared.db import connect

VOCAB = {  # toy 4-d "embeddings" so cosine is predictable in tests
    "fractions": np.array([1, 0, 0, 0], dtype=np.float32),
    "ratios": np.array([0, 1, 0, 0], dtype=np.float32),
    "integers": np.array([0, 0, 1, 0], dtype=np.float32),
}


def _seed(conn):
    conn.execute(
        "INSERT INTO sources VALUES ('openstax','OpenStax','CC BY-NC-SA 4.0','u',"
        "'https://openstax.org','2026-06-10',datetime('now'))"
    )
    conn.execute(
        "INSERT INTO books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES ('b','openstax','Prealgebra 2e','mathematics','6-8','CC BY-NC-SA 4.0','u')"
    )
    rows = [
        ("c-frac", "Dividing Fractions", "To divide fractions multiply by the reciprocal.", "worked_example", "fractions"),
        ("c-ratio", "Ratios and Rates", "A ratio compares two quantities.", "exposition", "ratios"),
        ("c-int", "Adding Integers", "Integers include negative whole numbers.", "exposition", "integers"),
    ]
    for cid, title, content, ctype, vkey in rows:
        conn.execute(
            "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
            " word_count, source_url, attribution, last_verified)"
            " VALUES (?,?,'openstax',?,?,?,5,'u','OpenStax attr','2026-06-10')",
            (cid, "b", title, content, ctype),
        )
        conn.execute(
            "INSERT INTO chunk_embeddings (chunk_id, model, vector, dimensions)"
            " VALUES (?,?,?,?)",
            (cid, "nomic-embed-text", VOCAB[vkey].tobytes(), 4),
        )
    conn.commit()


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "core.db", create=True)
    _seed(c)
    yield c
    c.close()


def test_keyword_fallback_when_no_embedder(conn):
    out = queries.search_content(conn, "dividing fractions", embed_query=None)
    assert out["search_mode"] == "keyword_fallback"
    assert out["results"][0]["chunk_id"] == "c-frac"
    assert out["results"][0]["content"] is None  # include_content default False


def test_embedder_failure_degrades_gracefully(conn):
    def boom(_):
        raise RuntimeError("ollama unreachable")

    out = queries.search_content(conn, "ratios", embed_query=boom)
    assert out["search_mode"] == "keyword_fallback"
    assert out["results"][0]["chunk_id"] == "c-ratio"


def test_hybrid_mode_uses_embeddings(conn):
    # query embeds to the "ratios" axis; semantic arm should surface c-ratio
    out = queries.search_content(
        conn, "proportional comparison", embed_query=lambda q: VOCAB["ratios"]
    )
    assert out["search_mode"] == "hybrid"
    assert out["results"][0]["chunk_id"] == "c-ratio"


def test_filters_and_include_content(conn):
    out = queries.search_content(
        conn, "fractions integers ratios", embed_query=None,
        content_type="exposition", include_content=True,
    )
    ids = {r["chunk_id"] for r in out["results"]}
    assert "c-frac" not in ids  # worked_example filtered out
    assert ids == {"c-ratio", "c-int"}
    assert all(r["content"] for r in out["results"])


def test_empty_query(conn):
    out = queries.search_content(conn, "!!!", embed_query=None)
    assert out["search_mode"] == "empty_query"
    assert out["results"] == []
