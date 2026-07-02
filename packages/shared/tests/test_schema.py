"""Schema round-trip: every table accepts and returns the shapes the models
expect, FTS5 stays in sync via triggers, and constraints actually constrain."""

import sqlite3

import pytest

from oer_shared.db import (
    _CHUNK_ASSESSMENT_COLUMNS,
    attached_schemas,
    connect,
    init_schema,
    migrate_schema,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    init_schema(c)
    yield c
    c.close()


def seed(c: sqlite3.Connection) -> None:
    c.execute(
        "INSERT INTO sources VALUES ('openstax','OpenStax','CC BY-NC-SA 4.0',"
        "'https://creativecommons.org/licenses/by-nc-sa/4.0/',"
        "'https://openstax.org','2026-06-09',datetime('now'))"
    )
    c.execute(
        "INSERT INTO books (id, source_id, title, subject, grade_band, license, url) "
        "VALUES ('openstax-prealgebra-2e','openstax','Prealgebra 2e','mathematics',"
        "'6-8','CC BY-NC-SA 4.0','https://openstax.org/details/books/prealgebra-2e')"
    )
    c.execute(
        "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
        " chapter, section, grade_band, word_count, source_url, attribution, last_verified)"
        " VALUES ('openstax-prealgebra-2e-m81285-expo','openstax-prealgebra-2e','openstax',"
        "'4.1 Visualize Fractions','A ratio compares two quantities using fractions.',"
        "'exposition','4','1','6-8',7,"
        "'https://openstax.org/books/prealgebra-2e/pages/4-1-visualize-fractions',"
        "'OpenStax Prealgebra 2e, Section 4.1, CC BY-NC-SA 4.0','2026-06-09')"
    )
    c.commit()


def test_round_trip_and_fts(conn):
    seed(conn)
    row = conn.execute("SELECT * FROM chunks").fetchone()
    assert row["attribution"].startswith("OpenStax")

    hits = conn.execute(
        "SELECT id FROM chunks_fts WHERE chunks_fts MATCH 'ratio'"
    ).fetchall()
    assert [h["id"] for h in hits] == ["openstax-prealgebra-2e-m81285-expo"]


def test_fts_follows_update_and_delete(conn):
    seed(conn)
    conn.execute(
        "UPDATE chunks SET content = 'Decimals describe parts of a whole.' "
        "WHERE id = 'openstax-prealgebra-2e-m81285-expo'"
    )
    conn.commit()
    assert not conn.execute(
        "SELECT 1 FROM chunks_fts WHERE chunks_fts MATCH 'ratio'"
    ).fetchall()
    assert conn.execute(
        "SELECT 1 FROM chunks_fts WHERE chunks_fts MATCH 'decimals'"
    ).fetchall()

    conn.execute("DELETE FROM chunks")
    conn.commit()
    assert not conn.execute(
        "SELECT 1 FROM chunks_fts WHERE chunks_fts MATCH 'decimals'"
    ).fetchall()


def test_constraints(conn):
    seed(conn)
    # attribution is non-nullable (D4)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
            " word_count, source_url, attribution, last_verified)"
            " VALUES ('x','openstax-prealgebra-2e','openstax','t','c','exposition',"
            " 1,'u',NULL,'2026-06-09')"
        )
    # content_type is constrained to the four types (D5)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
            " word_count, source_url, attribution, last_verified)"
            " VALUES ('y','openstax-prealgebra-2e','openstax','t','c','video',"
            " 1,'u','a','2026-06-09')"
        )
    # one alignment row per (chunk, standard)
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source) VALUES "
        "('openstax-prealgebra-2e-m81285-expo','CCSS.MATH.6.RP.A.3','ccss',0.91,'embedding')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
            " alignment_score, alignment_source) VALUES "
            "('openstax-prealgebra-2e-m81285-expo','CCSS.MATH.6.RP.A.3','ccss',0.5,'embedding')"
        )


def test_migrate_adds_missing_assessment_columns():
    """A DB whose chunks table predates the assessment columns is healed by
    migrate_schema (ALTER ADD COLUMN), and the migration is idempotent."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_schema(c)  # fresh schema already has the columns

    # Simulate a legacy DB: drop the assessment columns back off.
    for name, _ in _CHUNK_ASSESSMENT_COLUMNS:
        c.execute(f"ALTER TABLE chunks DROP COLUMN {name}")
    present = {r["name"] for r in c.execute("PRAGMA table_info(chunks)")}
    assert not any(name in present for name, _ in _CHUNK_ASSESSMENT_COLUMNS)

    added = migrate_schema(c)
    assert set(added) == {name for name, _ in _CHUNK_ASSESSMENT_COLUMNS}
    present = {r["name"] for r in c.execute("PRAGMA table_info(chunks)")}
    assert all(name in present for name, _ in _CHUNK_ASSESSMENT_COLUMNS)

    # Idempotent: a second run adds nothing.
    assert migrate_schema(c) == []
    c.close()


def test_connect_create_auto_migrates_legacy_db(tmp_path):
    """Opening a legacy DB with create=True runs init_schema → migrate_schema,
    so the assessment columns are present without a manual migration step."""
    path = tmp_path / "legacy.db"
    c = connect(path, create=True)
    for name, _ in _CHUNK_ASSESSMENT_COLUMNS:
        c.execute(f"ALTER TABLE chunks DROP COLUMN {name}")
    c.commit()
    c.close()

    c = connect(path, create=True)  # reopen — init_schema migrates
    present = {r["name"] for r in c.execute("PRAGMA table_info(chunks)")}
    assert all(name in present for name, _ in _CHUNK_ASSESSMENT_COLUMNS)
    c.close()


def test_two_db_attach(tmp_path):
    core = tmp_path / "oer_core.db"
    addon = tmp_path / "oer_ncsa.db"
    for p in (core, addon):
        c = connect(p, create=True)
        c.close()
    conn = connect(core, addon)
    assert attached_schemas(conn) == ["main", "ncsa"]
    conn.close()

    # absent add-on is silent, not an error (D11)
    conn = connect(core, tmp_path / "missing.db")
    assert attached_schemas(conn) == ["main"]
    conn.close()
