import sqlite3

import pytest

from oer_ingestion.migrate import migrate_alignment_source_check
from oer_shared.db import connect


def _old_schema_db(path):
    """A DB whose standard_alignments predates the llm_verified CHECK value."""
    c = connect(path, create=True)
    # rebuild standard_alignments with the OLD (pre-D20) CHECK
    c.executescript(
        """DROP TABLE standard_alignments;
           CREATE TABLE standard_alignments (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             chunk_id TEXT NOT NULL, standard_id TEXT NOT NULL,
             standard_system TEXT NOT NULL, alignment_score REAL NOT NULL,
             alignment_source TEXT NOT NULL CHECK (alignment_source IN
               ('embedding','publisher_guide','human')),
             coverage_notes TEXT, verified_by_human INTEGER NOT NULL DEFAULT 0,
             flagged_for_review INTEGER NOT NULL DEFAULT 0,
             stale INTEGER NOT NULL DEFAULT 0,
             created_at TEXT NOT NULL DEFAULT (datetime('now')),
             UNIQUE(chunk_id, standard_id));"""
    )
    c.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
        " alignment_score, alignment_source, flagged_for_review) VALUES"
        " ('x','CCSS.MATH.6.NS.1','ccss',0.8,'embedding',1)"
    )
    c.commit()
    return c


def test_migration_adds_llm_verified(tmp_path):
    c = _old_schema_db(tmp_path / "old.db")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute(
            "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system,"
            " alignment_score, alignment_source) VALUES ('y','S','ccss',0.9,'llm_verified')"
        )

    assert migrate_alignment_source_check(c) is True

    # now accepted, and existing row + data preserved
    c.execute(
        "UPDATE standard_alignments SET alignment_source='llm_verified', alignment_score=0.9"
        " WHERE chunk_id='x'"
    )
    c.commit()
    row = c.execute("SELECT alignment_source, flagged_for_review FROM standard_alignments WHERE chunk_id='x'").fetchone()
    assert row["alignment_source"] == "llm_verified"
    assert row["flagged_for_review"] == 1  # preserved through rebuild

    # idempotent: second call is a no-op
    assert migrate_alignment_source_check(c) is False
    c.close()


def test_migration_noop_on_new_schema(tmp_path):
    c = connect(tmp_path / "new.db", create=True)  # already has llm_verified
    assert migrate_alignment_source_check(c) is False
    c.close()
