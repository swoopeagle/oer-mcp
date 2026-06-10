"""SQLite connection handling for the two-database architecture (D11).

The server opens the core database as `main` and ATTACHes the optional
license-restricted add-on database as `ncsa` when present. Query helpers
iterate over attached_schemas() so every query transparently spans both.
"""

import sqlite3
from importlib import resources
from pathlib import Path


def init_schema(conn: sqlite3.Connection) -> None:
    """Apply schema.sql (idempotent — everything is IF NOT EXISTS)."""
    sql = resources.files("oer_shared").joinpath("schema.sql").read_text()
    conn.executescript(sql)
    conn.commit()


def connect(
    core_path: str | Path,
    addon_path: str | Path | None = None,
    *,
    create: bool = False,
) -> sqlite3.Connection:
    """Open the core DB, attach the add-on DB if it exists on disk.

    create=True initialises the schema on the core DB (ingestion/tests);
    the server runs with create=False and fails loudly on a missing DB.
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
    if create:
        init_schema(conn)
    if addon_path is not None and Path(addon_path).exists():
        conn.execute("ATTACH DATABASE ? AS ncsa", (str(addon_path),))
    return conn


def attached_schemas(conn: sqlite3.Connection) -> list[str]:
    """Schemas holding OER content: ['main'] or ['main', 'ncsa']."""
    rows = conn.execute("PRAGMA database_list").fetchall()
    return [r["name"] for r in rows if r["name"] in ("main", "ncsa")]
