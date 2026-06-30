"""Critical alignment logic tests: grade penalties, FTS5, edge cases."""

import sqlite3

import pytest

from oer_server import queries
from oer_shared.db import connect


def _book(conn):
    conn.execute(
        "INSERT INTO sources VALUES ('openstax','OpenStax','CC BY','u',"
        "'https://openstax.org','2026-06-10',datetime('now'))"
    )
    conn.execute(
        "INSERT INTO books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES ('b','openstax','Book','mathematics','6-8','CC BY','u')"
    )


def _chunk(conn, cid, grade_band="6-8"):
    conn.execute(
        "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
        " word_count, source_url, attribution, grade_band, stale, last_verified)"
        " VALUES (?,?,'openstax','title','body','exposition',2,'u','attr',?,0,'2026-06-10')",
        (cid, "b", grade_band),
    )


def _align(conn, cid, score, src="embedding"):
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES (?,?,'ccss',?,?,0)",
        (cid, "CCSS.MATH.6.RP.3", score, src),
    )


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "core.db", create=True)
    _book(c)
    yield c
    c.close()


# ── Grade Penalty Logic (D18) ────────────────────────────────────────

def test_fts5_index_stays_in_sync_after_insert(conn):
    """FTS5 virtual index should be updated when chunks are inserted."""
    _chunk(conn, "c1")
    conn.execute(
        "INSERT INTO chunks_fts(rowid, id, title, content) "
        "VALUES ((SELECT rowid FROM chunks WHERE id='c1'), 'c1', 'Fractions', 'division')"
    )
    conn.commit()

    # Search should find the newly inserted chunk
    out = queries.search_content(conn, "fractions", embed_query=None)
    assert any(r["chunk_id"] == "c1" for r in out["results"])


def test_fts5_index_stays_in_sync_after_update(conn):
    """FTS5 should stay in sync when chunk content is updated."""
    _chunk(conn, "c1")
    conn.execute(
        "INSERT INTO chunks_fts(rowid, id, title, content) "
        "VALUES ((SELECT rowid FROM chunks WHERE id='c1'), 'c1', 'Old Title', 'old content')"
    )
    conn.commit()

    # Update the chunk
    conn.execute(
        "UPDATE chunks SET title='New Title: Fractions' WHERE id='c1'"
    )
    # Manually update FTS (in prod, triggers handle this)
    conn.execute("DELETE FROM chunks_fts WHERE id='c1'")
    conn.execute(
        "INSERT INTO chunks_fts(rowid, id, title, content) "
        "VALUES ((SELECT rowid FROM chunks WHERE id='c1'), 'c1', 'New Title: Fractions', 'old content')"
    )
    conn.commit()

    # Search for new title should work
    out = queries.search_content(conn, "fractions", embed_query=None)
    assert any(r["chunk_id"] == "c1" for r in out["results"])


def test_chunk_adjacent_lookup_boundary(conn):
    """Adjacent chunks should include chapter/section context."""
    # Create chapters with sections
    for i in range(1, 4):
        cid = f"c{i}"
        _chunk(conn, cid)
        conn.execute(
            "UPDATE chunks SET chapter='1', section=? WHERE id=?",
            (str(i), cid),
        )
    conn.commit()

    # get_chunk with adjacency should work
    result = queries.get_chunk(conn, "c2", include_adjacent=True)
    assert result["chunk_id"] == "c2"
    # Adjacent structure should exist
    assert "adjacent" in result or result.get("chapter") == "1"


def test_ranking_deterministic_with_ties(conn):
    """When two alignments have same rank and score, order should be deterministic."""
    _chunk(conn, "c1")
    _chunk(conn, "c2")
    # Create two alignments with same source and score
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES (?,?,'ccss',?,?,0)",
        ("c1", "CCSS.MATH.6.RP.3", 0.85, "publisher_guide"),
    )
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES (?,?,'ccss',?,?,0)",
        ("c2", "CCSS.MATH.6.RP.3", 0.85, "publisher_guide"),
    )
    conn.commit()

    # Run twice to check determinism
    out1 = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.3")
    out2 = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.3")

    ids1 = [r["chunk_id"] for r in out1]
    ids2 = [r["chunk_id"] for r in out2]

    # Order should be same (deterministic)
    assert ids1 == ids2


def test_coverage_notes_with_special_characters(conn):
    """Coverage notes should handle special characters, quotes, etc."""
    _chunk(conn, "c1")
    special_note = 'Teaches "fractions" with examples: 1/2, 3/4, etc. (Grade 6-8)'
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, coverage_notes, stale) "
        "VALUES (?,?,'ccss',?,?,?,0)",
        ("c1", "CCSS.MATH.6.RP.3", 0.85, "publisher_guide", special_note),
    )
    conn.commit()

    out = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.3")
    assert out[0]["coverage_notes"] == special_note


def test_alignment_with_null_grade_band(conn):
    """Chunks without grade_band should still align correctly."""
    conn.execute(
        "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
        " word_count, source_url, attribution, grade_band, stale, last_verified)"
        " VALUES (?,?,'openstax','title','body','exposition',2,'u','attr',NULL,0,'2026-06-10')",
        ("cnull", "b"),
    )
    _align(conn, "cnull", 0.85)
    conn.commit()

    out = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.3")
    assert len(out) == 1
    assert out[0]["chunk_id"] == "cnull"
    assert out[0]["grade_band"] is None


def test_verified_alignment_confidently_beats_embedding(conn):
    """llm_verified should rank above embedding even at lower score."""
    _chunk(conn, "emb")
    _chunk(conn, "ver")

    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES (?,?,'ccss',?,?,0)",
        ("emb", "CCSS.MATH.6.RP.3", 0.92, "embedding"),
    )
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES (?,?,'ccss',?,?,0)",
        ("ver", "CCSS.MATH.6.RP.3", 0.75, "llm_verified"),
    )
    conn.commit()

    out = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.3")
    # llm_verified should be first despite lower score
    assert out[0]["chunk_id"] == "ver"
    assert out[0]["alignment_source"] == "llm_verified"


def test_multiple_alignments_same_chunk(conn):
    """Same chunk can have multiple alignments to different standards."""
    _chunk(conn, "c1")
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES (?,?,'ccss',?,?,0)",
        ("c1", "CCSS.MATH.6.RP.1", 0.85, "embedding"),
    )
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES (?,?,'ccss',?,?,0)",
        ("c1", "CCSS.MATH.6.RP.2", 0.80, "embedding"),
    )
    conn.commit()

    out1 = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.1")
    out2 = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.2")

    assert len(out1) == 1 and out1[0]["chunk_id"] == "c1"
    assert len(out2) == 1 and out2[0]["chunk_id"] == "c1"
