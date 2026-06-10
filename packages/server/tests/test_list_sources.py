"""list_sources spans the core DB and the optional NC-SA add-on (D11)."""

import pytest

from oer_server import queries
from oer_shared.db import connect


def seed_source(conn, schema, source_id, license_):
    conn.execute(
        f"INSERT INTO {schema}.sources VALUES (?,?,?,'https://example.com/license',"
        "'https://example.com','2026-06-09',datetime('now'))",
        (source_id, source_id.title(), license_),
    )
    conn.execute(
        f"INSERT INTO {schema}.books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES (?,?,?,'mathematics','6-8',?,'https://example.com')",
        (f"{source_id}-book", source_id, f"{source_id} Book", license_),
    )
    conn.execute(
        f"INSERT INTO {schema}.chunks (id, book_id, source_id, title, content, content_type,"
        " word_count, source_url, attribution, last_verified)"
        " VALUES (?,?,?,'t','some content','exposition',2,'u','attr','2026-06-09')",
        (f"{source_id}-chunk", f"{source_id}-book", source_id),
    )
    conn.commit()


@pytest.fixture
def core_only(tmp_path):
    conn = connect(tmp_path / "core.db", create=True)
    yield conn
    conn.close()


def test_empty_inventory(core_only):
    inv = queries.list_sources(core_only)
    assert inv.sources == []
    assert inv.total_chunks == 0
    assert inv.databases_attached == ["core"]


def test_inventory_spans_attached_dbs(tmp_path):
    core_path, addon_path = tmp_path / "core.db", tmp_path / "ncsa.db"
    addon = connect(addon_path, create=True)
    seed_source(addon, "main", "khan-academy", "CC BY-NC-SA 4.0")
    addon.close()

    conn = connect(core_path, addon_path, create=True)
    seed_source(conn, "main", "ck12", "CC BY 4.0")

    inv = queries.list_sources(conn)
    assert inv.databases_attached == ["core", "ncsa"]
    assert {s.id for s in inv.sources} == {"ck12", "khan-academy"}
    assert inv.total_chunks == 2
    conn.close()


def test_stale_chunks_excluded(core_only):
    seed_source(core_only, "main", "openstax", "CC BY-NC-SA 4.0")
    core_only.execute("UPDATE chunks SET stale = 1")
    core_only.commit()
    inv = queries.list_sources(core_only)
    assert inv.total_chunks == 0
    assert inv.sources[0].chunks_indexed == 0
