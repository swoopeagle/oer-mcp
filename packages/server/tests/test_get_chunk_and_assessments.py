"""get_chunk and map_to_assessments MCP tool tests."""

import pytest

from oer_server import queries
from oer_shared.db import connect


def _source(conn, sid="openstax", schema="main"):
    conn.execute(
        f"INSERT INTO {schema}.sources VALUES (?,?,?,'u','https://example.com',"
        "'2026-06-10',datetime('now'))",
        (sid, "Test Source", "CC BY 4.0"),
    )


def _book(conn, bid="b1", source="openstax", schema="main"):
    _source(conn, source, schema)
    conn.execute(
        f"INSERT INTO {schema}.books (id, source_id, title, subject, grade_band,"
        " license, url) VALUES (?,?,?,'mathematics','6-8','CC BY 4.0','u')",
        (bid, source, f"Book {bid}"),
    )


def _chunk(conn, cid, bid="b1", ctype="exposition", exam_series=None, schema="main"):
    conn.execute(
        f"INSERT INTO {schema}.chunks (id, book_id, source_id, title, content,"
        " content_type, word_count, source_url, attribution, last_verified,"
        " item_type, exam_series)"
        f" VALUES (?,?,?,'title {cid}','content {cid}',?,10,'u','attr','2026-06-10',"
        " ?,?)",
        (cid, bid, "openstax", ctype, None, exam_series),
    )


def _align(conn, cid, standard="CCSS.MATH.6.RP.A.3", schema="main"):
    conn.execute(
        f"INSERT INTO {schema}.standard_alignments (chunk_id, standard_id,"
        " standard_system, alignment_score, alignment_source) VALUES (?,?,'ccss',0.9,'embedding')",
        (cid, standard),
    )


def _crosswalk(conn, standard="CCSS.MATH.6.RP.A.3", exam="SAT", skill="Passport"):
    conn.execute(
        "INSERT INTO main.exam_crosswalks (standard_id, exam_series, skill_domain,"
        " notes, source_url) VALUES (?,?,?,?,?)",
        (standard, exam, skill, None, "https://example.com"),
    )


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "core.db", create=True)
    _book(c)
    yield c
    c.close()


def test_get_chunk_found_basic(conn):
    """get_chunk returns content, alignments, and metadata for a known chunk."""
    _chunk(conn, "c1")
    _align(conn, "c1")
    conn.commit()

    result = queries.get_chunk(conn, "c1")
    assert result["chunk_id"] == "c1"
    assert result["title"] == "title c1"
    assert result["content"] == "content c1"
    assert result["source"] == "openstax"
    # NOTE: chunks.grade_band is NULL by default; it's not inherited from books.
    # This may be intended behavior (book and chunk have independent grades) but worth noting.
    assert result["grade_band"] is None
    assert "alignments" in result
    assert len(result["alignments"]) == 1
    assert result["alignments"][0]["standard_id"] == "CCSS.MATH.6.RP.A.3"


def test_get_chunk_not_found(conn):
    """get_chunk on unknown ID returns structured not-found result."""
    result = queries.get_chunk(conn, "unknown_id")
    assert result == {"chunk_id": "unknown_id", "result": "not_found"}


def test_get_chunk_adjacent_none_when_false(conn):
    """By default (include_adjacent=False), adjacent is not returned."""
    _chunk(conn, "c1")
    conn.commit()

    result = queries.get_chunk(conn, "c1", include_adjacent=False)
    assert "adjacent" not in result


def test_get_chunk_adjacent_with_neighbours(conn):
    """When include_adjacent=True, returns prev/next chunk IDs in book order."""
    # Insert 3 chunks in order; they get rowid 1, 2, 3
    _chunk(conn, "c1")
    _chunk(conn, "c2")
    _chunk(conn, "c3")
    conn.commit()

    # Middle chunk should have prev=c1, next=c3
    result = queries.get_chunk(conn, "c2", include_adjacent=True)
    assert "adjacent" in result
    assert result["adjacent"]["previous"] == "c1"
    assert result["adjacent"]["next"] == "c3"


def test_get_chunk_adjacent_first_chunk(conn):
    """First chunk in book has no previous."""
    _chunk(conn, "c1")
    _chunk(conn, "c2")
    conn.commit()

    result = queries.get_chunk(conn, "c1", include_adjacent=True)
    assert result["adjacent"]["previous"] is None
    assert result["adjacent"]["next"] == "c2"


def test_get_chunk_adjacent_last_chunk(conn):
    """Last chunk in book has no next."""
    _chunk(conn, "c1")
    _chunk(conn, "c2")
    conn.commit()

    result = queries.get_chunk(conn, "c2", include_adjacent=True)
    assert result["adjacent"]["previous"] == "c1"
    assert result["adjacent"]["next"] is None


def test_get_chunk_excludes_stale(conn):
    """Stale chunks are not returned."""
    _chunk(conn, "c1")
    # Mark as stale
    conn.execute("UPDATE main.chunks SET stale=1 WHERE id='c1'")
    conn.commit()

    result = queries.get_chunk(conn, "c1")
    assert result == {"chunk_id": "c1", "result": "not_found"}


def test_map_to_assessments_no_crosswalk(conn):
    """Standard with no crosswalk rows returns empty crosswalk."""
    result = queries.map_to_assessments(conn, "CCSS.MATH.6.RP.A.3")
    assert result["standard_id"] == "CCSS.MATH.6.RP.A.3"
    assert result["crosswalk"] == []
    assert result["items_by_exam"] == {}
    assert result["gaps"] == []
    assert result["crosswalk_coverage"] == "unavailable"


def test_map_to_assessments_with_crosswalk(conn):
    """Standard with crosswalk rows returns exam mappings."""
    _crosswalk(conn, "CCSS.MATH.6.RP.A.3", "SAT", "Passport")
    _crosswalk(conn, "CCSS.MATH.6.RP.A.3", "ACT", "Number & Quantity")
    conn.commit()

    result = queries.map_to_assessments(conn, "CCSS.MATH.6.RP.A.3")
    assert result["standard_id"] == "CCSS.MATH.6.RP.A.3"
    assert len(result["crosswalk"]) == 2
    assert result["crosswalk"][0]["exam_series"] == "ACT"  # sorted
    assert result["crosswalk"][1]["exam_series"] == "SAT"
    assert result["crosswalk_coverage"] == "full"


def test_map_to_assessments_gaps_in_crosswalk(conn):
    """Exam series with crosswalk but no items show as gaps."""
    _crosswalk(conn, "CCSS.MATH.6.RP.A.3", "SAT", "Passport")
    _crosswalk(conn, "CCSS.MATH.6.RP.A.3", "ACT", "Number & Quantity")
    # Add an assessment item for SAT only
    _chunk(conn, "assessment1", ctype="assessment", exam_series="SAT")
    _align(conn, "assessment1", "CCSS.MATH.6.RP.A.3")
    conn.commit()

    result = queries.map_to_assessments(conn, "CCSS.MATH.6.RP.A.3")
    assert "SAT" in result["items_by_exam"]
    assert "ACT" not in result["items_by_exam"]  # no items
    assert "ACT" in result["gaps"]  # but in crosswalk


def test_map_to_assessments_prefix_fallback(conn):
    """Cluster letter fallback: CCSS.MATH.6.RP.A → CCSS.MATH.6.RP when no exact match.

    The fallback only triggers if the last component is a single uppercase letter
    (the cluster letter A, B, C, D, etc). Standards ending in a number (like .3)
    don't trigger the fallback."""
    # Add crosswalk for the prefix (without the cluster letter)
    _crosswalk(conn, "CCSS.MATH.6.RP", "SAT", "Passport")
    conn.commit()

    # Query with a standard that has a cluster letter as the last component
    # This will strip the 'A' and try LIKE 'CCSS.MATH.6.RP%', which matches
    result = queries.map_to_assessments(conn, "CCSS.MATH.6.RP.A")
    assert len(result["crosswalk"]) == 1
    assert result["crosswalk"][0]["exam_series"] == "SAT"


def test_map_to_assessments_include_items_true(conn):
    """When include_items=True, content and answer_key are included."""
    _crosswalk(conn, "CCSS.MATH.6.RP.A.3", "SAT", "Passport")
    _chunk(conn, "assessment1", ctype="assessment", exam_series="SAT")
    conn.execute(
        "UPDATE main.chunks SET answer_key='Correct answer is C' WHERE id='assessment1'"
    )
    _align(conn, "assessment1", "CCSS.MATH.6.RP.A.3")
    conn.commit()

    result = queries.map_to_assessments(conn, "CCSS.MATH.6.RP.A.3", include_items=True)
    assert "SAT" in result["items_by_exam"]
    items = result["items_by_exam"]["SAT"]
    assert len(items) == 1
    assert items[0]["content"] == "content assessment1"
    assert items[0]["answer_key"] == "Correct answer is C"


def test_map_to_assessments_ready_status(conn):
    """A current DB reports items_status='ready' (item store is queryable)."""
    result = queries.map_to_assessments(conn, "CCSS.MATH.6.RP.A.3")
    assert result["items_status"] == "ready"


def test_map_to_assessments_legacy_db_degrades(conn):
    """A DB predating the assessment columns must not crash: crosswalk still
    resolves, items_status flags 'no_item_store', and no items are returned."""
    # Simulate a legacy chunks table by dropping the assessment columns.
    for col in ("item_type", "dok_level", "answer_key", "exam_series",
                "exam_year", "difficulty", "item_generation"):
        conn.execute(f"ALTER TABLE main.chunks DROP COLUMN {col}")
    _crosswalk(conn, "CCSS.MATH.6.RP.A.3", "SAT", "Passport")
    conn.commit()

    result = queries.map_to_assessments(conn, "CCSS.MATH.6.RP.A.3")
    assert result["items_status"] == "no_item_store"
    assert result["items_by_exam"] == {}
    assert len(result["crosswalk"]) == 1  # crosswalk is independent of chunk cols
    assert result["crosswalk_coverage"] == "full"


def test_map_to_assessments_include_items_false(conn):
    """When include_items=False, content and answer_key are stripped."""
    _crosswalk(conn, "CCSS.MATH.6.RP.A.3", "SAT", "Passport")
    _chunk(conn, "assessment1", ctype="assessment", exam_series="SAT")
    conn.execute(
        "UPDATE main.chunks SET answer_key='Correct answer is C' WHERE id='assessment1'"
    )
    _align(conn, "assessment1", "CCSS.MATH.6.RP.A.3")
    conn.commit()

    result = queries.map_to_assessments(conn, "CCSS.MATH.6.RP.A.3", include_items=False)
    items = result["items_by_exam"]["SAT"]
    assert items[0]["content"] is None
    assert items[0]["answer_key"] is None
