from oer_shared.db import connect

from oer_ingestion.validate_db import validate


def _seed(conn, n_chunks, *, null_attr=False):
    conn.execute(
        "INSERT INTO sources VALUES ('openstax','OpenStax','CC BY 4.0','u','b','2026-06-13',datetime('now'))"
    )
    conn.execute(
        "INSERT INTO books (id, source_id, title, subject, grade_band, license, url)"
        " VALUES ('b','openstax','T','mathematics','6-8','CC BY 4.0','u')"
    )
    for i in range(n_chunks):
        attr = "" if null_attr else "OpenStax attr"
        conn.execute(
            "INSERT INTO chunks (id, book_id, source_id, title, content, content_type,"
            " word_count, source_url, attribution, last_verified)"
            " VALUES (?,?,'openstax','t','a fraction of cake','exposition',4,'u',?,'2026-06-13')",
            (f"c{i}", "b", attr),
        )
    conn.commit()


def test_hard_checks_pass_on_healthy_db(tmp_path):
    conn = connect(tmp_path / "d.db", create=True)
    _seed(conn, 20)
    r = validate(conn, min_chunks=10)
    assert r.passed
    assert {c.name for c in r.checks if c.ok} >= {
        "min_chunks", "no_null_content", "attribution_present", "fts_searchable"
    }
    conn.close()


def test_missing_attribution_fails_hard(tmp_path):
    conn = connect(tmp_path / "d.db", create=True)
    _seed(conn, 20, null_attr=True)
    r = validate(conn, min_chunks=10)
    assert not r.passed
    assert any(c.name == "attribution_present" and not c.ok for c in r.checks)
    conn.close()


def test_embedding_gap_is_soft(tmp_path):
    conn = connect(tmp_path / "d.db", create=True)
    _seed(conn, 20)
    r = validate(conn, min_chunks=10)
    emb = next(c for c in r.checks if c.name == "embeddings_complete")
    assert not emb.ok and not emb.hard  # incomplete embeddings don't fail the build
    assert r.passed
    conn.close()
