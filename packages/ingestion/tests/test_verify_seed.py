"""Claude verification loader — verified upgrades to llm_verified, reject marks
stale, stronger tiers aren't downgraded, missing rows are counted not fatal."""

import json

from oer_ingestion.verify_seed import load_verifications
from oer_shared.db import connect


def _seed_db(tmp_path):
    conn = connect(tmp_path / "core.db", create=True)
    conn.execute("INSERT INTO sources VALUES ('s','S','CC BY 4.0','u','u','2026-01-01',datetime('now'))")
    conn.execute(
        "INSERT INTO books (id, source_id, title, subject, grade_band, license, url) "
        "VALUES ('b','s','B','mathematics','6-8','CC BY 4.0','u')"
    )
    for cid in ("good", "bad", "pub"):
        conn.execute(
            "INSERT INTO chunks (id, book_id, source_id, title, content, content_type, "
            "word_count, source_url, attribution, last_verified) "
            f"VALUES ('{cid}','b','s','t','c','exposition',1,'u','a','2026-01-01')"
        )
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system, "
        "alignment_score, alignment_source) VALUES ('good','CCSS.MATH.7.EE.4','ccss',0.77,'embedding')"
    )
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system, "
        "alignment_score, alignment_source) VALUES ('bad','CCSS.MATH.8.EE.1','ccss',0.81,'embedding')"
    )
    conn.execute(
        "INSERT INTO standard_alignments (chunk_id, standard_id, standard_system, "
        "alignment_score, alignment_source) VALUES ('pub','CCSS.MATH.6.RP.3','ccss',0.95,'publisher_guide')"
    )
    conn.commit()
    return conn


def _seed_file(tmp_path):
    f = tmp_path / "v.json"
    f.write_text(json.dumps({"verifications": [
        {"chunk_id": "good", "standard_id": "CCSS.MATH.7.EE.4", "verdict": "verified", "note": "correct"},
        {"chunk_id": "bad", "standard_id": "CCSS.MATH.8.EE.1", "verdict": "reject", "note": "false positive"},
        {"chunk_id": "pub", "standard_id": "CCSS.MATH.6.RP.3", "verdict": "verified", "note": "n/a"},
        {"chunk_id": "ghost", "standard_id": "CCSS.MATH.1.OA.1", "verdict": "verified", "note": "missing"},
    ]}))
    return f


def test_apply_verifications(tmp_path):
    conn = _seed_db(tmp_path)
    counts = load_verifications(conn, _seed_file(tmp_path))
    assert counts == {"verified": 2, "rejected": 1, "missing": 1}

    # verified -> llm_verified + note
    row = conn.execute(
        "SELECT alignment_source, coverage_notes, stale FROM standard_alignments WHERE chunk_id='good'"
    ).fetchone()
    assert row["alignment_source"] == "llm_verified" and row["coverage_notes"] == "correct" and row["stale"] == 0

    # reject -> stale=1
    row = conn.execute("SELECT stale, coverage_notes FROM standard_alignments WHERE chunk_id='bad'").fetchone()
    assert row["stale"] == 1 and "false positive" in row["coverage_notes"]

    # publisher_guide NOT downgraded to llm_verified
    row = conn.execute("SELECT alignment_source FROM standard_alignments WHERE chunk_id='pub'").fetchone()
    assert row["alignment_source"] == "publisher_guide"
    conn.close()


def test_idempotent(tmp_path):
    conn = _seed_db(tmp_path)
    f = _seed_file(tmp_path)
    first = load_verifications(conn, f)
    second = load_verifications(conn, f)
    assert first == second
    conn.close()


def test_real_seed_parses():
    """The shipped seed is valid JSON with the expected shape."""
    from oer_ingestion.verify_seed import _DEFAULT_FILE
    data = json.loads(_DEFAULT_FILE.read_text())
    assert data["verifications"]
    assert all(v["verdict"] in ("verified", "reject") for v in data["verifications"])
    assert all(v["note"] and v["chunk_id"] and v["standard_id"] for v in data["verifications"])
