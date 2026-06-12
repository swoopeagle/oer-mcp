"""check_coverage — gap surfacing with a fake StandardGraph DB, source-aware
bands, and graceful degradation when SG is absent."""

import sqlite3

import pytest

from oer_server import queries
from oer_shared.db import connect


def _fake_sg(path):
    """Minimal StandardGraph DB: cluster 6.RP with three standards."""
    sg = sqlite3.connect(path)
    sg.executescript(
        """CREATE TABLE standards (id TEXT PRIMARY KEY, system TEXT, domain TEXT,
             cluster TEXT, standard_text TEXT);
           INSERT INTO standards VALUES
             ('CCSS.MATH.6.RP.1','ccss','RP','A','Understand ratio concepts.'),
             ('CCSS.MATH.6.RP.2','ccss','RP','A','Understand unit rate.'),
             ('CCSS.MATH.6.RP.3','ccss','RP','A','Use ratio and rate reasoning.');"""
    )
    sg.commit()
    sg.close()


def _seed_oer(conn):
    conn.execute(
        "INSERT INTO sources VALUES ('openstax','OpenStax','CC BY-NC-SA 4.0','u',"
        "'https://openstax.org','2026-06-10',datetime('now'))"
    )
    conn.execute(
        "INSERT INTO books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES ('b','openstax','Prealgebra 2e','mathematics','6-8','CC BY-NC-SA 4.0','u')"
    )

    def chunk_aligned(cid, sid, score, src="embedding"):
        conn.execute(
            "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
            " word_count, source_url, attribution, last_verified)"
            " VALUES (?,?,'openstax','t','body','exposition',2,'u','attr','2026-06-10')",
            (cid, "b"),
        )
        conn.execute(
            "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
            " alignment_score, alignment_source) VALUES (?,?,'ccss',?,?)",
            (cid, sid, score, src),
        )

    # 6.RP.1 strong (embedding ≥0.78), 6.RP.2 moderate, 6.RP.3 none (the gap)
    chunk_aligned("c1", "CCSS.MATH.6.RP.1", 0.80)
    chunk_aligned("c2", "CCSS.MATH.6.RP.2", 0.72)
    conn.commit()


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "core.db", create=True)
    _seed_oer(c)
    yield c
    c.close()


def test_surfaces_gap_with_sg(tmp_path, conn):
    sg = tmp_path / "sg.db"
    _fake_sg(sg)
    out = queries.check_coverage(conn, "CCSS.MATH.6.RP.3", sg_db_path=sg)
    assert out["gap_detection"] == "full"
    assert out["standards_checked"] == 3  # whole cluster, via domain+cluster
    bands = {s["id"]: s["coverage"] for s in out["sub_standards"]}
    assert bands == {
        "CCSS.MATH.6.RP.1": "strong",
        "CCSS.MATH.6.RP.2": "moderate",
        "CCSS.MATH.6.RP.3": "none",
    }
    assert out["gaps"] == ["CCSS.MATH.6.RP.3"]
    assert out["overall_coverage"] == "moderate"  # worst non-gap band


def test_cluster_letter_form_tolerated(tmp_path, conn):
    sg = tmp_path / "sg.db"
    _fake_sg(sg)
    # PRD-style id with the cluster letter that SG's IDs omit
    out = queries.check_coverage(conn, "CCSS.MATH.6.RP.A", sg_db_path=sg)
    assert out["standards_checked"] == 3


def test_degrades_without_sg(conn):
    out = queries.check_coverage(conn, "CCSS.MATH.6.RP", sg_db_path=None)
    assert out["gap_detection"] == "unavailable_without_standardgraph"
    # only the two standards that have alignments are visible; the gap is invisible
    ids = {s["id"] for s in out["sub_standards"]}
    assert ids == {"CCSS.MATH.6.RP.1", "CCSS.MATH.6.RP.2"}
    assert out["gaps"] == []


def test_unknown_standard(tmp_path, conn):
    sg = tmp_path / "sg.db"
    _fake_sg(sg)
    out = queries.check_coverage(conn, "CCSS.MATH.9.ZZ.1", sg_db_path=sg)
    assert out["result"] == "unknown_standard"
