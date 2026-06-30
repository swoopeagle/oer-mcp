"""get_learning_path: BFS prereq walk + OER content per rung."""

import sqlite3

import pytest

from oer_server import queries
from oer_shared.db import connect


# ── SG seed helpers ──────────────────────────────────────────────────────────


def _make_sg(tmp_path, standards: list[tuple], relationships: list[tuple]) -> str:
    """Create a minimal StandardGraph SQLite file and return its path string.

    standards: [(id, system, domain, cluster, text), ...]
    relationships: [(source_id, target_id, relationship, system), ...]
    """
    path = str(tmp_path / "sg.db")
    sg = sqlite3.connect(path)
    sg.executescript("""
        CREATE TABLE standards (
            id TEXT PRIMARY KEY, system TEXT, domain TEXT, cluster TEXT, standard_text TEXT
        );
        CREATE TABLE standard_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT, target_id TEXT, relationship TEXT, system TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(source_id, target_id, relationship)
        );
    """)
    sg.executemany(
        "INSERT INTO standards VALUES (?,?,?,?,?)", standards
    )
    sg.executemany(
        "INSERT INTO standard_relationships (source_id, target_id, relationship, system)"
        " VALUES (?,?,?,?)",
        relationships,
    )
    sg.commit()
    sg.close()
    return path


# ── OER DB seed helpers (mirror test_get_chunk_and_assessments.py pattern) ──


def _source(conn, sid="openstax"):
    conn.execute(
        "INSERT INTO main.sources VALUES (?,?,?,'u','https://example.com',"
        "'2026-06-10',datetime('now'))",
        (sid, "Test Source", "CC BY 4.0"),
    )


def _book(conn, bid="b1", source="openstax"):
    _source(conn, source)
    conn.execute(
        "INSERT INTO main.books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES (?,?,?,'mathematics','6-8','CC BY 4.0','u')",
        (bid, source, f"Book {bid}"),
    )


def _chunk(conn, cid, bid="b1"):
    conn.execute(
        "INSERT INTO main.chunks (id, book_id, source_id, title, content,"
        " content_type, word_count, source_url, attribution, last_verified)"
        " VALUES (?,'b1','openstax','title','body text','exposition',10,'u','attr','2026-06-10')",
        (cid,),
    )


def _align(conn, cid, standard, score=0.9, source="embedding"):
    conn.execute(
        "INSERT INTO main.standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source) VALUES (?,?,'ccss',?,?)",
        (cid, standard, score, source),
    )


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "core.db", create=True)
    _book(c)
    yield c
    c.close()


# ── tests ────────────────────────────────────────────────────────────────────


def test_target_only_when_no_prereqs(conn, tmp_path):
    """A standard with no prereqs returns a path with just the target."""
    sg = _make_sg(
        tmp_path,
        standards=[("CCSS.MATH.6.RP.3", "ccss", "RP", "A", "Ratio reasoning")],
        relationships=[],
    )
    _chunk(conn, "c1"); _align(conn, "c1", "CCSS.MATH.6.RP.3")
    conn.commit()

    result = queries.get_learning_path(conn, "CCSS.MATH.6.RP.3", sg_db_path=sg)
    assert result["sg_available"] is True
    assert len(result["path"]) == 1
    assert result["path"][0]["is_target"] is True
    assert result["path"][0]["standard_id"] == "CCSS.MATH.6.RP.3"
    assert result["path"][0]["coverage"] == "strong"


def test_prereqs_returned_bottom_up_target_last(conn, tmp_path):
    """Direct prereqs appear before the target in the path."""
    sg = _make_sg(
        tmp_path,
        standards=[
            ("TARGET", "ccss", "RP", "A", "Target standard"),
            ("PREREQ1", "ccss", "NF", "B", "Prereq one"),
            ("PREREQ2", "ccss", "NF", "B", "Prereq two"),
        ],
        relationships=[
            ("TARGET", "PREREQ1", "prerequisite", "ccss"),
            ("TARGET", "PREREQ2", "prerequisite", "ccss"),
        ],
    )
    conn.commit()

    result = queries.get_learning_path(conn, "TARGET", sg_db_path=sg, depth=1)
    ids = [e["standard_id"] for e in result["path"]]
    # Target must be last; prereqs before it.
    assert ids[-1] == "TARGET"
    assert "PREREQ1" in ids
    assert "PREREQ2" in ids
    # All prereqs have distance=1, target has distance=0.
    target_entry = next(e for e in result["path"] if e["is_target"])
    assert target_entry["distance"] == 0
    for entry in result["path"]:
        if not entry["is_target"]:
            assert entry["distance"] == 1


def test_depth_two_walks_two_levels(conn, tmp_path):
    """depth=2 walks two levels of prereqs and dedupes via visited set."""
    sg = _make_sg(
        tmp_path,
        standards=[
            ("A", "ccss", "RP", "A", "A"),
            ("B", "ccss", "RP", "A", "B"),
            ("C", "ccss", "RP", "A", "C"),
        ],
        # A→B (B prereq of A), B→C (C prereq of B)
        relationships=[
            ("A", "B", "prerequisite", "ccss"),
            ("B", "C", "prerequisite", "ccss"),
        ],
    )
    conn.commit()

    result = queries.get_learning_path(conn, "A", sg_db_path=sg, depth=2)
    ids = [e["standard_id"] for e in result["path"]]
    assert "A" in ids and "B" in ids and "C" in ids
    # C is deepest (distance=2), A is target (distance=0).
    assert ids[0] == "C"
    assert ids[-1] == "A"


def test_cycle_terminates(conn, tmp_path):
    """Cyclic prereq relationships don't cause infinite BFS."""
    sg = _make_sg(
        tmp_path,
        standards=[
            ("X", "ccss", "RP", "A", "X"), ("Y", "ccss", "RP", "A", "Y")
        ],
        # X→Y and Y→X (cycle)
        relationships=[
            ("X", "Y", "prerequisite", "ccss"),
            ("Y", "X", "prerequisite", "ccss"),
        ],
    )
    conn.commit()

    # Must not hang.
    result = queries.get_learning_path(conn, "X", sg_db_path=sg, depth=5)
    ids = [e["standard_id"] for e in result["path"]]
    # Both appear exactly once.
    assert ids.count("X") == 1
    assert ids.count("Y") == 1


def test_sg_unavailable_returns_degraded(conn, tmp_path):
    """When SG DB is missing, returns just the target with sg_available=False."""
    _chunk(conn, "c1"); _align(conn, "c1", "CCSS.MATH.6.RP.3")
    conn.commit()

    result = queries.get_learning_path(
        conn, "CCSS.MATH.6.RP.3", sg_db_path=str(tmp_path / "missing.db")
    )
    assert result["sg_available"] is False
    assert len(result["path"]) == 1
    assert result["path"][0]["is_target"] is True


def test_unknown_standard_returns_structured_result(conn, tmp_path):
    """A standard not in SG returns {"result": "unknown_standard"}."""
    sg = _make_sg(tmp_path, standards=[], relationships=[])
    conn.commit()

    result = queries.get_learning_path(conn, "CCSS.MATH.DOESNOTEXIST", sg_db_path=sg)
    assert result["result"] == "unknown_standard"


def test_prereq_with_no_content_shows_gap(conn, tmp_path):
    """A prereq standard with no OER content appears in prerequisite_gaps."""
    sg = _make_sg(
        tmp_path,
        standards=[
            ("TARGET", "ccss", "RP", "A", "Target"),
            ("PREREQ_NO_CONTENT", "ccss", "NF", "B", "Prereq with no content"),
        ],
        relationships=[("TARGET", "PREREQ_NO_CONTENT", "prerequisite", "ccss")],
    )
    # Give the target content but not the prereq.
    _chunk(conn, "c1"); _align(conn, "c1", "TARGET")
    conn.commit()

    result = queries.get_learning_path(conn, "TARGET", sg_db_path=sg)
    assert "PREREQ_NO_CONTENT" in result["prerequisite_gaps"]
    gap_entry = next(e for e in result["path"] if e["standard_id"] == "PREREQ_NO_CONTENT")
    assert gap_entry["coverage"] == "none"
    assert gap_entry["content"] == []


def test_include_content_toggles_text(conn, tmp_path):
    """include_content=True includes chunk text; False omits it."""
    sg = _make_sg(
        tmp_path,
        standards=[("STD", "ccss", "RP", "A", "Standard")],
        relationships=[],
    )
    _chunk(conn, "c1"); _align(conn, "c1", "STD")
    conn.commit()

    with_content = queries.get_learning_path(
        conn, "STD", sg_db_path=sg, include_content=True
    )
    without = queries.get_learning_path(
        conn, "STD", sg_db_path=sg, include_content=False
    )

    target_with = with_content["path"][0]["content"]
    target_without = without["path"][0]["content"]
    assert target_with[0]["content"] is not None
    assert target_without[0]["content"] is None
