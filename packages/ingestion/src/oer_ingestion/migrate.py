"""One-off migrations for already-populated databases.

SQLite can't ALTER a CHECK constraint in place, so adding the 'llm_verified'
alignment_source value (D20) to an existing DB means rebuilding the
standard_alignments table. Idempotent: a no-op if the new value is already
accepted.
"""

import sqlite3


def _accepts_llm_verified(conn: sqlite3.Connection, schema: str = "main") -> bool:
    """True if the standard_alignments CHECK already allows 'llm_verified'.
    Reads the table DDL from sqlite_master — an insert probe would instead trip
    the chunk_id foreign key and give a false negative."""
    row = conn.execute(
        f"SELECT sql FROM {schema}.sqlite_master "
        "WHERE type='table' AND name='standard_alignments'"
    ).fetchone()
    return bool(row) and "llm_verified" in (row[0] or "")


def migrate_alignment_source_check(conn: sqlite3.Connection, schema: str = "main") -> bool:
    """Rebuild standard_alignments with the expanded CHECK if needed. Returns
    True if a migration was performed."""
    if _accepts_llm_verified(conn, schema):
        return False
    conn.executescript(
        f"""
        PRAGMA foreign_keys=OFF;
        BEGIN;
        CREATE TABLE {schema}.standard_alignments_new (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id            TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            standard_id         TEXT NOT NULL,
            standard_system     TEXT NOT NULL,
            alignment_score     REAL NOT NULL,
            alignment_source    TEXT NOT NULL CHECK (alignment_source IN
                                    ('embedding','llm_verified','publisher_guide','human')),
            coverage_notes      TEXT,
            verified_by_human   INTEGER NOT NULL DEFAULT 0,
            flagged_for_review  INTEGER NOT NULL DEFAULT 0,
            stale               INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(chunk_id, standard_id)
        );
        INSERT INTO {schema}.standard_alignments_new
            SELECT id, chunk_id, standard_id, standard_system, alignment_score,
                   alignment_source, coverage_notes, verified_by_human,
                   flagged_for_review, stale, created_at
            FROM {schema}.standard_alignments;
        DROP TABLE {schema}.standard_alignments;
        ALTER TABLE {schema}.standard_alignments_new RENAME TO standard_alignments;
        CREATE INDEX IF NOT EXISTS {schema}.idx_alignments_chunk    ON standard_alignments(chunk_id);
        CREATE INDEX IF NOT EXISTS {schema}.idx_alignments_standard ON standard_alignments(standard_id);
        CREATE INDEX IF NOT EXISTS {schema}.idx_alignments_score    ON standard_alignments(alignment_score DESC);
        CREATE INDEX IF NOT EXISTS {schema}.idx_alignments_system   ON standard_alignments(standard_system);
        COMMIT;
        PRAGMA foreign_keys=ON;
        """
    )
    return True
