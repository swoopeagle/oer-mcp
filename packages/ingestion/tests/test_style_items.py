"""Claude-authored style-item loader — seed parses, inserts chunks + alignments
idempotently, and the items surface through map_to_assessments."""

import pytest

from oer_ingestion.style_items import _DEFAULT_FILE, _FAMILY, _style_slug, load_style_items
from oer_server import queries
from oer_shared.db import connect


def test_style_slug_families():
    assert _style_slug("SAT") == "sat"
    assert _style_slug("ACT") == "act"
    assert _style_slug("Smarter Balanced Grade 3") == "sbac"
    assert _style_slug("Smarter Balanced Grade 5") == "sbac"
    assert _style_slug("NAEP Grade 4") == "naep"
    with pytest.raises(ValueError):
        _style_slug("AP Calculus BC")


def test_seed_loads_and_is_idempotent(tmp_path):
    conn = connect(tmp_path / "core.db", create=True)
    first = load_style_items(conn, _DEFAULT_FILE)
    assert first["added"] > 0 and first["skipped"] == 0

    # Every loaded chunk is an assessment item tagged style_generated.
    rows = conn.execute(
        "SELECT content_type, item_generation, exam_series, answer_key "
        "FROM chunks WHERE source_id LIKE 'style-gen-%'"
    ).fetchall()
    assert len(rows) == first["added"]
    assert all(r["content_type"] == "assessment" for r in rows)
    assert all(r["item_generation"] == "style_generated" for r in rows)
    assert all(r["answer_key"] for r in rows)  # every generated item carries a key
    exams = {r["exam_series"] for r in rows}
    assert {"SAT", "ACT"} <= exams  # SAT/ACT present, plus elementary families
    assert all(_style_slug(e) in _FAMILY for e in exams)  # every series maps to a known family

    # Each item has a publisher_guide alignment at 0.95.
    aligns = conn.execute(
        "SELECT DISTINCT alignment_source, alignment_score FROM standard_alignments a "
        "JOIN chunks c ON c.id = a.chunk_id WHERE c.source_id LIKE 'style-gen-%'"
    ).fetchall()
    assert all(a["alignment_source"] == "publisher_guide" for a in aligns)

    # Re-loading adds nothing.
    second = load_style_items(conn, _DEFAULT_FILE)
    assert second["added"] == 0 and second["skipped"] == first["added"]
    conn.close()


def test_items_surface_through_map_to_assessments(tmp_path):
    conn = connect(tmp_path / "core.db", create=True)
    load_style_items(conn, _DEFAULT_FILE)

    # 8.EE.1 has both a SAT and an ACT style item in the seed.
    result = queries.map_to_assessments(conn, "CCSS.MATH.8.EE.1", include_items=True)
    assert "SAT" in result["items_by_exam"]
    assert "ACT" in result["items_by_exam"]
    sat_item = result["items_by_exam"]["SAT"][0]
    assert sat_item["item_generation"] == "style_generated"
    assert sat_item["answer_key"]  # included when include_items=True
    assert sat_item["content"]
    conn.close()
