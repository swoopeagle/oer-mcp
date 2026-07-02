"""SQLite connection handling for the two-database architecture (D11).

The server opens the core database as `main` and ATTACHes the optional
license-restricted add-on database as `ncsa` when present. Query helpers
iterate over attached_schemas() so every query transparently spans both.
"""

import sqlite3
from importlib import resources
from pathlib import Path


# Columns added to `chunks` after the assessment feature landed. `CREATE TABLE
# IF NOT EXISTS` never alters a pre-existing table, so DBs built before these
# columns existed need an explicit ADD COLUMN migration. All nullable → safe and
# non-destructive to backfill onto an old DB.
_CHUNK_ASSESSMENT_COLUMNS = [
    ("item_type", "TEXT"),
    ("dok_level", "INTEGER"),
    ("answer_key", "TEXT"),
    ("exam_series", "TEXT"),
    ("exam_year", "INTEGER"),
    ("difficulty", "REAL"),
    ("item_generation", "TEXT"),
]


def migrate_schema(conn: sqlite3.Connection) -> list[str]:
    """Additive column migrations that IF-NOT-EXISTS DDL can't express.

    Idempotent: only ALTERs columns that are actually missing. Returns the list
    of columns added (empty when the DB is already current). Requires a writable
    connection — callers run this on the create/build path, never on the
    query_only server path.
    """
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(chunks)")}
    added: list[str] = []
    for name, decl in _CHUNK_ASSESSMENT_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE chunks ADD COLUMN {name} {decl}")
            added.append(name)
    if added:
        conn.commit()
    return added


def init_schema(conn: sqlite3.Connection) -> None:
    """Apply schema.sql (idempotent — everything is IF NOT EXISTS), then run
    additive migrations for columns that pre-existing tables would otherwise miss."""
    sql = resources.files("oer_shared").joinpath("schema.sql").read_text()
    conn.executescript(sql)
    conn.commit()
    migrate_schema(conn)


def connect(
    core_path: str | Path,
    addon_path: str | Path | None = None,
    ap_path: str | Path | None = None,
    *,
    create: bool = False,
) -> sqlite3.Connection:
    """Open the core DB; attach the NC-SA add-on and AP databases if present.

    create=True initialises the schema on the core DB (ingestion/tests);
    the server runs with create=False and fails loudly on a missing core DB.
    The add-on and AP databases are always optional — silently skipped when absent.
    """
    core_path = Path(core_path)
    if not create and not core_path.exists():
        raise FileNotFoundError(
            f"OER core database not found at {core_path}. "
            "Run the installer or set OER_CORE_DB_PATH."
        )
    core_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(core_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL + busy_timeout let multiple build-time writers (e.g. sharded annotate
    # workers on different Ollama hosts) write concurrently without locking out.
    conn.execute("PRAGMA busy_timeout = 30000")
    # Performance PRAGMAs safe for both server and build paths.
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA mmap_size = 268435456")   # 256 MB memory-map
    conn.execute("PRAGMA cache_size = -65536")      # 64 MB page cache (negative = KiB)
    if create:
        conn.execute("PRAGMA journal_mode = WAL")
        init_schema(conn)
    if addon_path is not None and Path(addon_path).exists():
        conn.execute("ATTACH DATABASE ? AS ncsa", (str(addon_path),))
    if ap_path is not None and Path(ap_path).exists():
        conn.execute("ATTACH DATABASE ? AS ap", (str(ap_path),))
    # query_only hardens the server against accidental writes; set last so ATTACHes work.
    if not create:
        conn.execute("PRAGMA query_only = ON")
    return conn


def attached_schemas(conn: sqlite3.Connection) -> list[str]:
    """Schemas holding OER content: ['main'], ['main', 'ncsa'], or all three."""
    rows = conn.execute("PRAGMA database_list").fetchall()
    return [r["name"] for r in rows if r["name"] in ("main", "ncsa", "ap")]
