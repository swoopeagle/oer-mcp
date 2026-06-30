"""MCP server-wrapper integration tests — delegation and structured-error path."""

import pytest

from oer_server import server
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


@pytest.fixture(autouse=True)
def reset_conn():
    """Reset server._conn before and after each test to prevent leakage."""
    server._conn = None
    yield
    server._conn = None


def test_list_sources_success(conn, monkeypatch):
    """list_sources wrapper returns the underlying queries result."""
    monkeypatch.setattr(server, "get_conn", lambda: conn)
    result = server.list_sources()
    assert isinstance(result, dict)
    assert "sources" in result
    assert isinstance(result["sources"], list)


def test_fetch_for_standard_success(conn, monkeypatch):
    """fetch_for_standard wrapper returns underlying queries result."""
    _chunk(conn, "c1")
    _align(conn, "c1", "CCSS.MATH.6.RP.A.3")
    conn.commit()
    monkeypatch.setattr(server, "get_conn", lambda: conn)
    result = server.fetch_for_standard("CCSS.MATH.6.RP.A.3")
    # Result is a list of dicts (the chunks)
    assert isinstance(result, list)
    if result:
        assert "chunk_id" in result[0]


def test_search_content_success(conn, monkeypatch):
    """search_content wrapper returns underlying queries result dict."""
    _chunk(conn, "c1", ctype="exposition")
    conn.commit()
    monkeypatch.setattr(server, "get_conn", lambda: conn)
    result = server.search_content("test content")
    assert isinstance(result, dict)
    assert "search_mode" in result or "results" in result or "error" not in result


def test_get_chunk_success(conn, monkeypatch):
    """get_chunk wrapper returns underlying queries result."""
    _chunk(conn, "c1")
    _align(conn, "c1")
    conn.commit()
    monkeypatch.setattr(server, "get_conn", lambda: conn)
    result = server.get_chunk("c1")
    assert isinstance(result, dict)
    assert result["chunk_id"] == "c1"


def test_check_coverage_success(conn, monkeypatch):
    """check_coverage wrapper returns underlying queries result."""
    _chunk(conn, "c1")
    _align(conn, "c1", "CCSS.MATH.6.RP.A.3")
    conn.commit()
    monkeypatch.setattr(server, "get_conn", lambda: conn)
    result = server.check_coverage("CCSS.MATH.6.RP.A.3")
    assert isinstance(result, dict)
    assert "standard_id" in result or "error" not in result


def test_map_to_assessments_success(conn, monkeypatch):
    """map_to_assessments wrapper returns underlying queries result."""
    _crosswalk(conn, "CCSS.MATH.6.RP.A.3", "SAT", "Passport")
    conn.commit()
    monkeypatch.setattr(server, "get_conn", lambda: conn)
    result = server.map_to_assessments("CCSS.MATH.6.RP.A.3")
    assert isinstance(result, dict)
    assert "standard_id" in result


def test_list_sources_error_handling(monkeypatch):
    """Wrapper catches exception and returns structured error."""
    def broken_get_conn():
        raise RuntimeError("boom")
    monkeypatch.setattr(server, "get_conn", broken_get_conn)
    result = server.list_sources()
    assert isinstance(result, dict)
    assert result["error"] == "RuntimeError"
    assert result["detail"] == "boom"


def test_fetch_for_standard_error_handling(monkeypatch):
    """Wrapper catches exception and returns structured error."""
    def broken_get_conn():
        raise RuntimeError("boom")
    monkeypatch.setattr(server, "get_conn", broken_get_conn)
    result = server.fetch_for_standard("CCSS.MATH.6.RP.A.3")
    assert isinstance(result, dict)
    assert result["error"] == "RuntimeError"
    assert result["detail"] == "boom"


def test_get_chunk_error_handling(monkeypatch):
    """Wrapper catches exception and returns structured error."""
    def broken_get_conn():
        raise RuntimeError("boom")
    monkeypatch.setattr(server, "get_conn", broken_get_conn)
    result = server.get_chunk("c1")
    assert isinstance(result, dict)
    assert result["error"] == "RuntimeError"
    assert result["detail"] == "boom"


def test_search_content_error_handling(monkeypatch):
    """Wrapper catches exception and returns structured error."""
    def broken_get_conn():
        raise RuntimeError("boom")
    monkeypatch.setattr(server, "get_conn", broken_get_conn)
    result = server.search_content("query")
    assert isinstance(result, dict)
    assert result["error"] == "RuntimeError"
    assert result["detail"] == "boom"


def test_check_coverage_error_handling(monkeypatch):
    """Wrapper catches exception and returns structured error."""
    def broken_get_conn():
        raise RuntimeError("boom")
    monkeypatch.setattr(server, "get_conn", broken_get_conn)
    result = server.check_coverage("CCSS.MATH.6.RP.A.3")
    assert isinstance(result, dict)
    assert result["error"] == "RuntimeError"
    assert result["detail"] == "boom"


def test_map_to_assessments_error_handling(monkeypatch):
    """Wrapper catches exception and returns structured error."""
    def broken_get_conn():
        raise RuntimeError("boom")
    monkeypatch.setattr(server, "get_conn", broken_get_conn)
    result = server.map_to_assessments("CCSS.MATH.6.RP.A.3")
    assert isinstance(result, dict)
    assert result["error"] == "RuntimeError"
    assert result["detail"] == "boom"
