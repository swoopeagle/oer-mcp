-- OER MCP database schema — PRD §7.3 with the §11 resilience columns merged in
-- from the start (not ALTERs). Applies identically to the core (CC BY) database
-- and the license-restricted add-on database (D11) — partitioned by license.

-- ─────────────────────────────────────────────────────────────────
-- sources — one row per content source (OpenStax, Khan Academy, CK-12)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sources (
    id              TEXT PRIMARY KEY,       -- "openstax" | "khan-academy" | "ck12"
    full_name       TEXT NOT NULL,
    license         TEXT NOT NULL,          -- source-level default; books may override
    license_url     TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    last_indexed    TEXT NOT NULL,          -- ISO 8601
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────
-- books — one row per textbook or course
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS books (
    id              TEXT PRIMARY KEY,       -- "openstax-prealgebra-2e"
    source_id       TEXT NOT NULL REFERENCES sources(id),
    title           TEXT NOT NULL,
    subject         TEXT NOT NULL,          -- always "mathematics" in v1
    grade_band      TEXT,                   -- "K-5" | "6-8" | "9-12" | "college"
    license         TEXT NOT NULL,          -- per-book: OpenStax mixes CC BY and CC BY-NC-SA (S1)
    url             TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_books_source ON books(source_id);
CREATE INDEX IF NOT EXISTS idx_books_grade  ON books(grade_band);

-- ─────────────────────────────────────────────────────────────────
-- chunks — core table; one row per retrievable typed content unit (D14).
-- Never split mid-concept; never deleted when upstream removes content
-- (stale=1 instead, filtered at query time).
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chunks (
    id              TEXT PRIMARY KEY,       -- "openstax-prealgebra-2e-m81285-expo"
    book_id         TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    source_id       TEXT NOT NULL,
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    content_type    TEXT NOT NULL CHECK (content_type IN
                        ('exposition','worked_example','exercise_set','summary')),
    chapter         TEXT,
    section         TEXT,
    grade_band      TEXT,
    word_count      INTEGER NOT NULL,
    source_url      TEXT NOT NULL,
    attribution     TEXT NOT NULL,          -- non-negotiable (D4)
    snapshot_path   TEXT,                   -- raw snapshot file this chunk was parsed from
    content_hash    TEXT,                   -- SHA-256 of content — detects upstream changes
    stale           INTEGER NOT NULL DEFAULT 0,
    last_verified   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_chunks_book   ON chunks(book_id);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_chunks_grade  ON chunks(grade_band);
CREATE INDEX IF NOT EXISTS idx_chunks_type   ON chunks(content_type);

-- FTS5 external-content index, kept in sync by triggers below.
-- NOTE: the pipeline must upsert via explicit UPDATE-else-INSERT, not
-- INSERT OR REPLACE — REPLACE bypasses the delete trigger unless
-- recursive_triggers is on, which would desync the index.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    id UNINDEXED,
    title,
    content,
    content='chunks',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS chunks_fts_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, id, title, content)
    VALUES (new.rowid, new.id, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, id, title, content)
    VALUES ('delete', old.rowid, old.id, old.title, old.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_au AFTER UPDATE OF id, title, content ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, id, title, content)
    VALUES ('delete', old.rowid, old.id, old.title, old.content);
    INSERT INTO chunks_fts(rowid, id, title, content)
    VALUES (new.rowid, new.id, new.title, new.content);
END;

-- ─────────────────────────────────────────────────────────────────
-- chunk_embeddings — separate from chunks; re-embeddable without
-- touching content
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id        TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    model           TEXT NOT NULL,          -- "nomic-embed-text"
    vector          BLOB NOT NULL,          -- numpy float32 tobytes()
    dimensions      INTEGER NOT NULL,       -- 768
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────
-- standard_alignments — chunk → StandardGraph standard ID, built at
-- ingestion time (D2). alignment_source='human' rows are immutable
-- to automation (PRD §10).
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS standard_alignments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id            TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    standard_id         TEXT NOT NULL,      -- "CCSS.MATH.6.RP.A.3"
    standard_system     TEXT NOT NULL,      -- "ccss" (Phase 1: ccss only, D3)
    alignment_score     REAL NOT NULL,
    alignment_source    TEXT NOT NULL CHECK (alignment_source IN
                            ('embedding','publisher_guide','human')),
    coverage_notes      TEXT,
    verified_by_human   INTEGER NOT NULL DEFAULT 0,
    flagged_for_review  INTEGER NOT NULL DEFAULT 0,
    stale               INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(chunk_id, standard_id)
);

CREATE INDEX IF NOT EXISTS idx_alignments_chunk    ON standard_alignments(chunk_id);
CREATE INDEX IF NOT EXISTS idx_alignments_standard ON standard_alignments(standard_id);
CREATE INDEX IF NOT EXISTS idx_alignments_score    ON standard_alignments(alignment_score DESC);
CREATE INDEX IF NOT EXISTS idx_alignments_system   ON standard_alignments(standard_system);

-- ─────────────────────────────────────────────────────────────────
-- pipeline_runs — source health tracking (PRD §11)
-- ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    chunks_expected INTEGER,
    chunks_fetched  INTEGER,
    chunks_added    INTEGER,
    chunks_removed  INTEGER,
    warnings        TEXT,                   -- JSON array of warning strings
    completed       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────
-- updated_at trigger for chunks
-- ─────────────────────────────────────────────────────────────────
CREATE TRIGGER IF NOT EXISTS chunks_updated_at
    AFTER UPDATE ON chunks
    FOR EACH ROW
    BEGIN
        UPDATE chunks SET updated_at = datetime('now') WHERE id = NEW.id;
    END;
