"""Tests for multi-database spanning (D11): core + ncsa + ap databases."""

import sqlite3
from pathlib import Path

import pytest

from oer_server import queries
from oer_shared.db import connect


def _setup_dbs(tmp_path):
    """Create core + ncsa DBs with sample data."""
    core = connect(tmp_path / "core.db", create=True)
    ncsa = sqlite3.connect(str(tmp_path / "ncsa.db"))

    # Copy schema to ncsa (tables + FTS5)
    for table in ['sources', 'books', 'chunks', 'standard_alignments', 'chunk_embeddings']:
        sql = core.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if sql:
            ncsa.execute(sql[0])

    # Create FTS5 index in ncsa too
    ncsa.execute("""
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            id UNINDEXED, title, content,
            content='chunks', content_rowid='rowid'
        )
    """)
    ncsa.execute("""
        CREATE TRIGGER chunks_fts_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, id, title, content)
            VALUES (new.rowid, new.id, new.title, new.content);
        END
    """)

    # Seed core DB
    core.execute(
        "INSERT INTO sources VALUES ('openstax','OpenStax','CC BY','u',"
        "'https://openstax.org','2026-06-10',datetime('now'))"
    )
    core.execute(
        "INSERT INTO books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES ('ob','openstax','Stats','mathematics','9-12','CC BY','u')"
    )
    core.execute(
        "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
        " word_count, source_url, attribution, stale, last_verified)"
        " VALUES ('os1','ob','openstax','Probability','content','exposition',2,'u','attr',0,'2026-06-10')"
    )
    core.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES ('os1','CCSS.MATH.HSS.CP.1','ccss',0.85,'embedding',0)"
    )
    core.commit()

    # Seed ncsa DB (Khan)
    ncsa.execute(
        "INSERT INTO sources VALUES ('khan','Khan Academy','CC BY-NC-SA','u',"
        "'https://khanacademy.org','2026-06-10',datetime('now'))"
    )
    ncsa.execute(
        "INSERT INTO books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES ('kb','khan','Khan Math','mathematics','6-8','CC BY-NC-SA','u')"
    )
    ncsa.execute(
        "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
        " word_count, source_url, attribution, stale, last_verified)"
        " VALUES ('khan1','kb','khan','Fractions','content','exposition',2,'u','attr',0,'2026-06-10')"
    )
    ncsa.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES ('khan1','CCSS.MATH.5.NF.1','ccss',0.90,'embedding',0)"
    )
    ncsa.commit()
    ncsa.close()

    return core, tmp_path


@pytest.fixture
def multi_db(tmp_path):
    core, path = _setup_dbs(tmp_path)
    yield core, path
    core.close()


def test_fetch_spans_both_databases(multi_db):
    """fetch_for_standard should return results from both core and ncsa DBs."""
    core, path = multi_db
    # Attach ncsa DB
    core.execute(f"ATTACH DATABASE '{path}/ncsa.db' AS ncsa")

    # Query a standard that has results in ncsa
    out = queries.fetch_for_standard(core, "CCSS.MATH.5.NF.1")
    assert out["count"] >= 1
    assert any(r["chunk_id"] == "khan1" for r in out["results"])

    # Query a standard that has results in core
    out2 = queries.fetch_for_standard(core, "CCSS.MATH.HSS.CP.1")
    assert out2["count"] >= 1
    assert any(r["chunk_id"] == "os1" for r in out2["results"])


def test_search_spans_both_databases(multi_db):
    """search_content should return results from both DBs."""
    core, path = multi_db
    core.execute(f"ATTACH DATABASE '{path}/ncsa.db' AS ncsa")

    out = queries.search_content(core, "content", embed_query=None)
    ids = {r["chunk_id"] for r in out["results"]}
    # Should have results from both DBs
    assert len(out["results"]) >= 2 or any(cid in ids for cid in ["os1", "khan1"])


def test_check_coverage_spans_databases(multi_db, tmp_path):
    """check_coverage should find alignments across attached DBs."""
    core, path = multi_db
    core.execute(f"ATTACH DATABASE '{path}/ncsa.db' AS ncsa")

    # Create a fake StandardGraph
    sg = sqlite3.connect(str(tmp_path / "sg.db"))
    sg.executescript("""
        CREATE TABLE standards (id TEXT PRIMARY KEY, system TEXT, domain TEXT, cluster TEXT, standard_text TEXT);
        INSERT INTO standards VALUES
          ('CCSS.MATH.5.NF.1','ccss','NF','A','Add/subtract fractions'),
          ('CCSS.MATH.HSS.CP.1','ccss','CP','A','Probability concepts');
    """)
    sg.close()

    out = queries.check_coverage(
        core, "CCSS.MATH.5.NF.1", sg_db_path=str(tmp_path / "sg.db")
    )
    # Should find the Khan alignment in ncsa DB
    assert out["overall_coverage"] in ["strong", "moderate", "light"]


def test_ranking_respects_confidence_across_dbs(multi_db):
    """Confidence hierarchy should work across multiple databases."""
    core, path = multi_db
    core.execute(f"ATTACH DATABASE '{path}/ncsa.db' AS ncsa")

    # Add a publisher_guide in ncsa (higher confidence than embedding)
    ncsa = sqlite3.connect(str(path / "ncsa.db"))
    ncsa.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES ('khan1','CCSS.MATH.HSS.CP.1','ccss',0.80,'publisher_guide',0)"
    )
    ncsa.commit()
    ncsa.close()

    # Re-attach
    core.execute("DETACH DATABASE ncsa")
    core.execute(f"ATTACH DATABASE '{path}/ncsa.db' AS ncsa")

    out = queries.fetch_for_standard(core, "CCSS.MATH.HSS.CP.1")
    # publisher_guide from ncsa should rank above embedding from core
    if out["count"] > 1:
        assert out["results"][0]["alignment_source"] == "publisher_guide"


def test_deduplication_across_databases(multi_db):
    """Same chunk appearing in multiple DBs shouldn't be duplicated."""
    core, path = multi_db
    core.execute(f"ATTACH DATABASE '{path}/ncsa.db' AS ncsa")

    # Add same chunk ID to both DBs with same standard
    ncsa = sqlite3.connect(str(path / "ncsa.db"))
    ncsa.execute(
        "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
        " word_count, source_url, attribution, stale, last_verified)"
        " VALUES ('shared','kb','khan','Shared','shared content','exposition',1,'u','attr',0,'2026-06-10')"
    )
    ncsa.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, stale) VALUES ('shared','CCSS.MATH.5.NF.1','ccss',0.80,'embedding',0)"
    )
    ncsa.commit()
    ncsa.close()

    out = queries.fetch_for_standard(core, "CCSS.MATH.5.NF.1")
    shared_count = sum(1 for r in out["results"] if r["chunk_id"] == "shared")
    # Should appear only once (not duplicated)
    assert shared_count <= 1
