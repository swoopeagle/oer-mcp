"""One-off migrations for already-populated databases.

SQLite can't ALTER a CHECK constraint in place, so schema changes that touch
CHECK values require rebuilding the affected table. All migrations are
idempotent — safe to re-run.
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


def _chunks_check_allows_assessment(conn: sqlite3.Connection, schema: str = "main") -> bool:
    """True if the chunks content_type CHECK already allows 'assessment'.
    We gate on the CHECK, not on column presence: oer_shared.db.migrate_schema
    may have ALTER-added the columns while leaving the old 4-value CHECK in
    place, and gating on a column would then wrongly skip the CHECK rebuild."""
    row = conn.execute(
        f"SELECT sql FROM {schema}.sqlite_master "
        "WHERE type='table' AND name='chunks'"
    ).fetchone()
    return bool(row) and "'assessment'" in (row[0] or "")


def migrate_assessment_columns(conn: sqlite3.Connection, schema: str = "main") -> bool:
    """Add all assessment-specific columns (item_type, dok_level, answer_key,
    exam_series, exam_year, difficulty, item_generation) and expand the
    content_type CHECK to include 'assessment'. Rebuilds chunks to update the
    CHECK, then restores the FTS/updated_at triggers that DROP TABLE removes.
    Also creates the exam_crosswalks table if absent. Returns True if a
    migration was performed."""
    if _chunks_check_allows_assessment(conn, schema):
        return False

    conn.executescript(
        f"""
        PRAGMA foreign_keys=OFF;
        BEGIN;
        CREATE TABLE {schema}.chunks_new (
            id              TEXT PRIMARY KEY,
            book_id         TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            source_id       TEXT NOT NULL,
            title           TEXT NOT NULL,
            content         TEXT NOT NULL,
            content_type    TEXT NOT NULL CHECK (content_type IN
                                ('exposition','worked_example','exercise_set','summary','assessment')),
            chapter         TEXT,
            section         TEXT,
            grade_band      TEXT,
            word_count      INTEGER NOT NULL,
            source_url      TEXT NOT NULL,
            attribution     TEXT NOT NULL,
            item_type       TEXT,
            dok_level       INTEGER,
            answer_key      TEXT,
            exam_series     TEXT,
            exam_year       INTEGER,
            difficulty      REAL,
            item_generation TEXT,
            snapshot_path   TEXT,
            content_hash    TEXT,
            stale           INTEGER NOT NULL DEFAULT 0,
            last_verified   TEXT NOT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO {schema}.chunks_new
            SELECT id, book_id, source_id, title, content, content_type,
                   chapter, section, grade_band, word_count, source_url, attribution,
                   NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                   snapshot_path, content_hash, stale, last_verified, created_at, updated_at
            FROM {schema}.chunks;
        DROP TABLE {schema}.chunks;
        ALTER TABLE {schema}.chunks_new RENAME TO chunks;
        CREATE INDEX IF NOT EXISTS {schema}.idx_chunks_book   ON chunks(book_id);
        CREATE INDEX IF NOT EXISTS {schema}.idx_chunks_source ON chunks(source_id);
        CREATE INDEX IF NOT EXISTS {schema}.idx_chunks_grade  ON chunks(grade_band);
        CREATE INDEX IF NOT EXISTS {schema}.idx_chunks_type   ON chunks(content_type);
        CREATE TABLE IF NOT EXISTS {schema}.exam_crosswalks (
            standard_id     TEXT NOT NULL,
            exam_series     TEXT NOT NULL,
            skill_domain    TEXT NOT NULL,
            notes           TEXT,
            source_url      TEXT NOT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (standard_id, exam_series)
        );
        CREATE INDEX IF NOT EXISTS {schema}.idx_crosswalks_standard ON exam_crosswalks(standard_id);
        CREATE INDEX IF NOT EXISTS {schema}.idx_crosswalks_exam     ON exam_crosswalks(exam_series);
        COMMIT;
        PRAGMA foreign_keys=ON;
        """
    )
    # DROP TABLE chunks also dropped the triggers bound to it (chunks_fts_ai/ad/au
    # keep FTS5 in sync; chunks_updated_at stamps updated_at). Re-running the
    # schema restores every IF-NOT-EXISTS object that went missing, leaving the
    # rebuilt chunks table otherwise untouched. Without this, FTS silently stops
    # syncing after the migration.
    from oer_shared.db import init_schema

    init_schema(conn)
    return True
