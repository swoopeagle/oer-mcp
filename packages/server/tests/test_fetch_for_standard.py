"""fetch_for_standard ranking + filtering, with seeded alignments (no Ollama)."""

import pytest

from oer_server import queries
from oer_shared.db import connect


def _book(conn, schema="main"):
    conn.execute(
        f"INSERT INTO {schema}.sources VALUES ('openstax','OpenStax','CC BY-NC-SA 4.0',"
        "'u','https://openstax.org','2026-06-10',datetime('now'))"
    )
    conn.execute(
        f"INSERT INTO {schema}.books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES ('b','openstax','Prealgebra 2e','mathematics','6-8','CC BY-NC-SA 4.0','u')"
    )


def _chunk(conn, cid, ctype="exposition", schema="main"):
    conn.execute(
        f"INSERT INTO {schema}.chunks (id, book_id, source_id, title, content, content_type,"
        " word_count, source_url, attribution, last_verified)"
        f" VALUES (?,'b','openstax',?, 'body text','{ctype}',2,'u','OpenStax attr','2026-06-10')",
        (cid, f"title {cid}"),
    )


def _align(conn, cid, score, src, schema="main"):
    conn.execute(
        f"INSERT INTO {schema}.standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source) VALUES (?,?,'ccss',?,?)",
        (cid, "CCSS.MATH.6.RP.A.3", score, src),
    )


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "core.db", create=True)
    _book(c)
    yield c
    c.close()


def test_no_content_is_structured(conn):
    out = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.A.3")
    assert out["result"] == "no_content"
    assert out["available_sources"] == ["openstax"]


def test_confidence_hierarchy_beats_raw_score(conn):
    # a publisher_guide at 0.90 must outrank an embedding at 0.98
    _chunk(conn, "emb"); _align(conn, "emb", 0.98, "embedding")
    _chunk(conn, "pub"); _align(conn, "pub", 0.90, "publisher_guide")
    conn.commit()
    out = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.A.3", limit=2)
    assert [r["chunk_id"] for r in out] == ["pub", "emb"]
    assert out[0]["alignment_source"] == "publisher_guide"


def test_llm_verified_tier_serializes_and_ranks(conn):
    # regression: llm_verified must be a valid alignment_source (D20) and
    # outrank raw embedding even at a lower score
    _chunk(conn, "emb"); _align(conn, "emb", 0.95, "embedding")
    _chunk(conn, "ver"); _align(conn, "ver", 0.90, "llm_verified")
    conn.commit()
    out = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.A.3", limit=2)
    assert [r["chunk_id"] for r in out] == ["ver", "emb"]
    assert out[0]["alignment_source"] == "llm_verified"


def test_filters_and_include_content(conn):
    _chunk(conn, "expo", "exposition"); _align(conn, "expo", 0.9, "embedding")
    _chunk(conn, "ex", "worked_example"); _align(conn, "ex", 0.95, "embedding")
    conn.commit()
    only = queries.fetch_for_standard(
        conn, "CCSS.MATH.6.RP.A.3", content_type="worked_example"
    )
    assert [r["chunk_id"] for r in only] == ["ex"]
    light = queries.fetch_for_standard(
        conn, "CCSS.MATH.6.RP.A.3", include_content=False
    )
    assert all(r["content"] is None for r in light)
    assert all(r["attribution"] for r in light)  # attribution always present (D4)
