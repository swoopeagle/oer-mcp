"""get_capabilities: live self-describing corpus manifest."""

import pytest

from oer_server import queries, server
from oer_shared.db import connect

_ALL_TOOLS = queries._ALL_TOOLS


def _book(conn, bid="b1", source="openstax", grade_band="6-8"):
    conn.execute(
        "INSERT INTO main.sources VALUES (?,?,?,'u','https://example.com',"
        "'2026-06-10',datetime('now'))",
        (source, "Test Source", "CC BY 4.0"),
    )
    conn.execute(
        "INSERT INTO main.books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES (?,?,?,'mathematics',?,?,'u')",
        (bid, source, f"Book {bid}", grade_band, "CC BY 4.0"),
    )


def _chunk(conn, cid, bid="b1", ctype="exposition", exam_series=None):
    conn.execute(
        "INSERT INTO main.chunks (id, book_id, source_id, title, content, content_type,"
        " word_count, source_url, attribution, last_verified, exam_series)"
        " VALUES (?,'b1','openstax','title','body text',?,10,'u','attr','2026-06-10',?)",
        (cid, ctype, exam_series),
    )


def _align(conn, cid, standard="CCSS.MATH.6.RP.A.3", system="ccss", source="embedding"):
    conn.execute(
        "INSERT INTO main.standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source) VALUES (?,?,?,0.9,?)",
        (cid, standard, system, source),
    )


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "core.db", create=True)
    _book(c, grade_band="6-8")
    yield c
    c.close()


# ── query-layer tests ────────────────────────────────────────────────────────


def test_capabilities_has_required_keys(conn):
    """Response includes all top-level keys."""
    conn.commit()
    caps = queries.get_capabilities(conn)
    for key in ("databases_attached", "sources", "standard_systems", "content_types",
                "exam_series", "grade_bands", "alignment_sources",
                "alignment_confidence_bands", "tools", "total_chunks", "total_alignments"):
        assert key in caps, f"missing key: {key}"


def test_capabilities_lists_all_tools(conn):
    """All 8 tools appear in the tools list."""
    conn.commit()
    caps = queries.get_capabilities(conn)
    for tool in _ALL_TOOLS:
        assert tool in caps["tools"], f"tool not listed: {tool}"


def test_capabilities_sources_reflect_db(conn):
    """Sources list matches what's indexed."""
    conn.commit()
    caps = queries.get_capabilities(conn)
    source_ids = [s["id"] for s in caps["sources"]]
    assert "openstax" in source_ids


def test_capabilities_exam_series_from_chunks(conn):
    """Exam series are drawn from live chunk data."""
    _chunk(conn, "c1", exam_series="SAT")
    conn.commit()
    caps = queries.get_capabilities(conn)
    assert "SAT" in caps["exam_series"]


def test_capabilities_standard_systems_from_alignments(conn):
    """Standard systems reflect what's actually aligned."""
    _chunk(conn, "c1")
    _align(conn, "c1", system="ccss")
    conn.commit()
    caps = queries.get_capabilities(conn)
    assert "ccss" in caps["standard_systems"]


def test_capabilities_grade_bands_from_books(conn):
    """Grade bands are drawn from the books table."""
    conn.commit()
    caps = queries.get_capabilities(conn)
    assert "6-8" in caps["grade_bands"]


def test_capabilities_content_types_are_static(conn):
    """Content types list is complete and stable."""
    conn.commit()
    caps = queries.get_capabilities(conn)
    expected = {"exposition", "worked_example", "exercise_set", "summary", "assessment"}
    assert set(caps["content_types"]) == expected


def test_capabilities_alignment_confidence_bands_present(conn):
    """Confidence band thresholds are included for all sources."""
    conn.commit()
    caps = queries.get_capabilities(conn)
    bands = caps["alignment_confidence_bands"]
    for src in ("embedding", "llm_verified", "publisher_guide", "human"):
        assert src in bands
        assert {"strong", "moderate", "light"} == set(bands[src])


def test_capabilities_totals_match_db(conn):
    """total_chunks and total_alignments reflect real counts."""
    _chunk(conn, "c1"); _chunk(conn, "c2")
    _align(conn, "c1"); _align(conn, "c2")
    conn.commit()
    caps = queries.get_capabilities(conn)
    assert caps["total_chunks"] == 2
    assert caps["total_alignments"] == 2


# ── wrapper tests (delegation + error path) ──────────────────────────────────


@pytest.fixture(autouse=True)
def reset_server_conn():
    server._conn = None
    yield
    server._conn = None


def test_get_capabilities_wrapper_success(conn, monkeypatch):
    """get_capabilities wrapper delegates to queries and returns manifest dict."""
    conn.commit()
    monkeypatch.setattr(server, "get_conn", lambda: conn)
    result = server.get_capabilities()
    assert isinstance(result, dict)
    assert "tools" in result
    assert len(result["tools"]) == 8


def test_get_capabilities_wrapper_error(monkeypatch):
    """get_capabilities wrapper catches exceptions and returns structured error."""
    monkeypatch.setattr(server, "get_conn", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    result = server.get_capabilities()
    assert result["error"]["code"] == "internal_error"
    assert result["error"]["type"] == "RuntimeError"
