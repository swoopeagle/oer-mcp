"""Edge case tests for alignment logic: grade penalties, multi-DB, stale filtering."""

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


def _chunk(conn, cid, grade_band="6-8", stale=0, schema="main"):
    conn.execute(
        f"INSERT INTO {schema}.chunks (id, book_id, source_id, title, content, content_type,"
        " word_count, source_url, attribution, grade_band, stale, last_verified)"
        f" VALUES (?,?,'openstax','title',?,'exposition',2,'u','attr',?,{stale},'2026-06-10')",
        (cid, "b", f"content for {cid}", grade_band),
    )


def _align(conn, cid, score, src="embedding", schema="main"):
    conn.execute(
        f"INSERT INTO {schema}.standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES (?,?,'ccss',?,?,0)",
        (cid, "CCSS.MATH.6.RP.3", score, src),
    )


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "core.db", create=True)
    _book(c)
    yield c
    c.close()


# ── Stale Filtering ──────────────────────────────────────────────────

def test_stale_chunks_excluded_from_fetch(conn):
    """Chunks marked stale=1 should not appear in fetch_for_standard."""
    _chunk(conn, "live", stale=0)
    _chunk(conn, "stale", stale=1)
    _align(conn, "live", 0.85)
    _align(conn, "stale", 0.90)  # Higher score but stale
    conn.commit()

    out = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.3")
    assert out["count"] == 1
    assert out["results"][0]["chunk_id"] == "live"


def test_stale_alignments_excluded(conn):
    """Alignments marked stale=1 should not be returned."""
    _chunk(conn, "c1", stale=0)
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES (?,?,'ccss',?,?,1)",
        ("c1", "CCSS.MATH.6.RP.3", 0.95, "embedding"),
    )
    conn.commit()

    out = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.3")
    assert out["count"] == 0
    assert out["results"] == []
    assert "reason" in out
    assert out["available_sources"] == ["openstax"]


# ── Assessment Content Fields ───────────────────────────────────────

def test_assessment_fields_included(conn):
    """Assessment-specific fields should serialize correctly."""
    conn.execute(
        "INSERT INTO sources VALUES ('assessments','Test Items','CC BY','u',"
        "'https://example.com','2026-06-10',datetime('now'))"
    )
    conn.execute(
        "INSERT INTO books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES ('ab','assessments','Test Bank','mathematics','6-8','CC BY','u')"
    )
    conn.execute(
        "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
        " word_count, source_url, attribution, item_type, dok_level, answer_key,"
        " exam_series, exam_year, difficulty, item_generation, stale, last_verified)"
        " VALUES (?,?,'assessments','Q1','What is 2+2?','assessment',1,'u','attr',"
        "'multiple_choice',1,'D) 4','SAT',2024,0.85,'released',0,'2026-06-10')",
        ("assess1", "ab"),
    )
    _align(conn, "assess1", 0.8, schema="main")
    conn.commit()

    out = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.3", include_content=True)
    assert out["count"] == 1
    result = out["results"][0]
    assert result["item_type"] == "multiple_choice"
    assert result["dok_level"] == 1
    assert result["answer_key"] == "D) 4"
    assert result["exam_series"] == "SAT"
    assert result["exam_year"] == 2024
    assert result["difficulty"] == 0.85
    assert result["item_generation"] == "released"


def test_assessment_fields_null_for_exposition(conn):
    """Non-assessment chunks should have NULL assessment fields."""
    _chunk(conn, "expo")
    _align(conn, "expo", 0.85)
    conn.commit()

    out = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.3")
    result = out["results"][0]
    assert result["item_type"] is None
    assert result["dok_level"] is None
    assert result["answer_key"] is None
    assert result["exam_series"] is None


# ── Coverage Notes ──────────────────────────────────────────────────

def test_coverage_notes_included_when_present(conn):
    """Coverage notes should serialize and be included in results."""
    _chunk(conn, "c1")
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, coverage_notes) VALUES (?,?,'ccss',?,?,?)",
        ("c1", "CCSS.MATH.6.RP.3", 0.85, "publisher_guide", "Teaches ratio concepts via examples"),
    )
    conn.commit()

    out = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.3")
    assert out["results"][0]["coverage_notes"] == "Teaches ratio concepts via examples"


def test_coverage_notes_null_when_absent(conn):
    """Coverage notes should be None if not populated."""
    _chunk(conn, "c1")
    _align(conn, "c1", 0.85)
    conn.commit()

    out = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.3")
    assert out["results"][0]["coverage_notes"] is None


# ── Grade Band Filtering ────────────────────────────────────────────

def test_grade_band_filter_works(conn):
    """Filter by grade_band should return only matching chunks."""
    _chunk(conn, "k5", grade_band="K-5")
    _chunk(conn, "68", grade_band="6-8")
    _chunk(conn, "912", grade_band="9-12")
    _align(conn, "k5", 0.85)
    _align(conn, "68", 0.80)
    _align(conn, "912", 0.75)
    conn.commit()

    out = queries.search_content(conn, "content", content_type="exposition", grade_band="6-8")
    assert len(out["results"]) >= 1
    assert all(r["grade_band"] == "6-8" for r in out["results"] if r["chunk_id"] in ["k5", "68", "912"])


# ── Source Filtering ────────────────────────────────────────────────

def test_source_filter_on_fetch(conn):
    """Source filter should only return chunks from specified source."""
    conn.execute(
        "INSERT INTO sources VALUES ('khan','Khan Academy','CC BY','u',"
        "'https://khanacademy.org','2026-06-10',datetime('now'))"
    )
    conn.execute(
        "INSERT INTO books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES ('kb','khan','Khan Math','mathematics','6-8','CC BY','u')"
    )
    conn.execute(
        "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
        " word_count, source_url, attribution, stale, last_verified)"
        " VALUES (?,?,?,'Video','content','exposition',2,'u','attr',0,'2026-06-10')",
        ("khan1", "kb", "khan"),
    )

    _chunk(conn, "os1")  # OpenStax
    _align(conn, "os1", 0.85, schema="main")
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES (?,?,'ccss',?,?,0)",
        ("khan1", "CCSS.MATH.6.RP.3", 0.80, "embedding"),
    )
    conn.commit()

    os_only = queries.fetch_for_standard(conn, "CCSS.MATH.6.RP.3", source="openstax")
    assert all(r["source"] == "openstax" for r in os_only["results"])
    assert os_only["count"] == 1
