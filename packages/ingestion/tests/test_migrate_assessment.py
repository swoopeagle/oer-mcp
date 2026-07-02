"""migrate_assessment_columns — rebuilds chunks to allow content_type='assessment'
while preserving data and, critically, restoring the FTS/updated_at triggers that
DROP TABLE removes. Regression: an earlier version left FTS silently un-synced."""

import sqlite3

import pytest

from oer_ingestion.migrate import (
    _chunks_check_allows_assessment,
    migrate_assessment_columns,
)
from oer_shared.db import connect, migrate_schema


def _legacy_chunks_db(path):
    """A DB whose chunks table has the pre-assessment 4-value CHECK and no
    assessment columns — the shape of DBs built before the assessment feature."""
    conn = connect(path, create=True)
    # Rebuild chunks back to the legacy shape (drop assessment cols + narrow CHECK).
    conn.executescript(
        """
        PRAGMA foreign_keys=OFF;
        BEGIN;
        DROP TABLE chunks;
        CREATE TABLE chunks (
            id TEXT PRIMARY KEY,
            book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            source_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            content_type TEXT NOT NULL CHECK (content_type IN
                ('exposition','worked_example','exercise_set','summary')),
            chapter TEXT, section TEXT, grade_band TEXT,
            word_count INTEGER NOT NULL,
            source_url TEXT NOT NULL, attribution TEXT NOT NULL,
            snapshot_path TEXT, content_hash TEXT,
            stale INTEGER NOT NULL DEFAULT 0,
            last_verified TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        COMMIT;
        PRAGMA foreign_keys=ON;
        """
    )
    # Recreate the FTS triggers the legacy DB would have had.
    from importlib import resources
    # (schema.sql triggers are IF NOT EXISTS — safe to re-apply for the fts pieces)
    conn.executescript(resources.files("oer_shared").joinpath("schema.sql").read_text())
    conn.execute(
        "INSERT INTO sources VALUES ('s','S','CC BY 4.0','u','u','2026-01-01',datetime('now'))"
    )
    conn.execute(
        "INSERT INTO books (id, source_id, title, subject, grade_band, license, url) "
        "VALUES ('b','s','B','mathematics','6-8','CC BY 4.0','u')"
    )
    conn.execute(
        "INSERT INTO chunks (id, book_id, source_id, title, content, content_type, "
        "word_count, source_url, attribution, last_verified) "
        "VALUES ('c1','b','s','Ratios','ratio and proportion','exposition',3,'u','a','2026-01-01')"
    )
    conn.commit()
    return conn


def test_migrate_expands_check_preserves_data_and_fts(tmp_path):
    conn = _legacy_chunks_db(tmp_path / "legacy.db")
    assert not _chunks_check_allows_assessment(conn)

    did = migrate_assessment_columns(conn)
    assert did is True
    assert _chunks_check_allows_assessment(conn)

    # Existing row preserved.
    assert conn.execute("SELECT title FROM chunks WHERE id='c1'").fetchone()[0] == "Ratios"
    # Existing FTS content still searchable.
    assert [r[0] for r in conn.execute(
        "SELECT id FROM chunks_fts WHERE chunks_fts MATCH 'ratio'"
    )] == ["c1"]

    # An assessment row now inserts (CHECK expanded) AND syncs to FTS (triggers
    # restored) — the regression this test guards.
    conn.execute(
        "INSERT INTO chunks (id, book_id, source_id, title, content, content_type, "
        "word_count, source_url, attribution, last_verified, exam_series, item_generation) "
        "VALUES ('a1','b','s','SAT Item','solve for x quadratic','assessment',4,'u','a',"
        "'2026-01-01','SAT','style_generated')"
    )
    conn.commit()
    assert [r[0] for r in conn.execute(
        "SELECT id FROM chunks_fts WHERE chunks_fts MATCH 'quadratic'"
    )] == ["a1"]

    # Idempotent second run.
    assert migrate_assessment_columns(conn) is False
    conn.close()


def test_migrate_is_noop_on_current_schema(tmp_path):
    """A fresh DB already allows assessment; migration does nothing."""
    conn = connect(tmp_path / "core.db", create=True)
    migrate_schema(conn)
    assert _chunks_check_allows_assessment(conn)
    assert migrate_assessment_columns(conn) is False
    conn.close()
