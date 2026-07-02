"""Exam crosswalk loader — JSONC comment tolerance, upsert semantics, and that
the built-in seed file actually parses and loads (it never had until the loader
learned to strip its ``//`` section headers)."""

from oer_ingestion.crosswalk import _DEFAULT_FILE, _strip_jsonc_comments, load_crosswalks
from oer_shared.db import connect


def test_strip_jsonc_preserves_urls_in_strings():
    """Full-line // comments are dropped; // inside a string (https://) is kept."""
    src = (
        '{\n'
        '  // a section header\n'
        '    // indented comment\n'
        '  "url": "https://example.com/x//y"\n'
        '}\n'
    )
    cleaned = _strip_jsonc_comments(src)
    assert "section header" not in cleaned
    assert "indented comment" not in cleaned
    assert "https://example.com/x//y" in cleaned


def test_seed_file_loads(tmp_path):
    """The shipped seed parses (despite // comments) and populates the table."""
    conn = connect(tmp_path / "core.db", create=True)
    counts = load_crosswalks(conn, _DEFAULT_FILE)
    assert counts["added"] > 0 and counts["updated"] == 0

    total = conn.execute("SELECT COUNT(*) FROM exam_crosswalks").fetchone()[0]
    assert total == counts["added"]
    exams = {r[0] for r in conn.execute("SELECT DISTINCT exam_series FROM exam_crosswalks")}
    assert {"SAT", "ACT", "AP Statistics"} <= exams
    conn.close()


def test_load_is_idempotent_upsert(tmp_path):
    """Re-loading the same file updates in place rather than duplicating rows."""
    conn = connect(tmp_path / "core.db", create=True)
    first = load_crosswalks(conn, _DEFAULT_FILE)
    second = load_crosswalks(conn, _DEFAULT_FILE)
    assert second["added"] == 0
    assert second["updated"] == first["added"]
    total = conn.execute("SELECT COUNT(*) FROM exam_crosswalks").fetchone()[0]
    assert total == first["added"]
    conn.close()
