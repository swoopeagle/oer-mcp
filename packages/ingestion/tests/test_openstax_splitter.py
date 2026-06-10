"""Typed sub-chunk splitter (D14) against a synthetic module mirroring the
real CNXML structure verified in S1: content subsections with <example>s,
a key-concepts section, and a section-exercises block of grouped exercises.
"""

from datetime import datetime, timezone

import pytest

from oer_ingestion.adapters.openstax import BookSpec, OpenStaxAdapter, _BookTree, _ModulePlace
from oer_ingestion.load import load_catalog, load_chunks
from oer_ingestion.adapters.base import RawContent
from oer_shared.db import connect

MODULE = """<document xmlns="http://cnx.rice.edu/cnxml"
  xmlns:m="http://www.w3.org/1998/Math/MathML">
<title>Visualize Fractions</title>
<metadata xmlns:md="http://cnx.rice.edu/mdml"><md:content-id>m999</md:content-id></metadata>
<content>
  <note class="be-prepared"><para>Prereq check.</para></note>
  <section>
    <title>Understand Fractions</title>
    <para>A fraction is written <m:math><m:mfrac><m:mn>1</m:mn><m:mn>4</m:mn></m:mfrac></m:math>.</para>
    <example><exercise><problem><para>Name the shaded part.</para></problem>
      <solution><para>It is one half.</para></solution></exercise></example>
    <para>More exposition prose here.</para>
  </section>
  <section class="key-concepts"><title>Key Concepts</title>
    <para>A fraction has a numerator and denominator.</para></section>
  <section class="section-exercises">
    <section class="practice-perfect"><title>Practice Makes Perfect</title>
      <exercise><problem><para>Simplify one half.</para></problem></exercise></section>
    <section class="writing"><title>Writing Exercises</title>
      <exercise><problem><para>Explain fractions.</para></problem></exercise></section>
  </section>
</content></document>"""


@pytest.fixture
def chunks():
    ad = OpenStaxAdapter([BookSpec("osbooks-x", "prealgebra-2e", "6-8")])
    ad._trees["prealgebra-2e"] = _BookTree(
        slug="prealgebra-2e", title="Prealgebra 2e", license="CC BY-NC-SA 4.0",
        places={"m999": _ModulePlace("m999", "4", "Fractions", "1", "Prealgebra 2e", "CC BY-NC-SA 4.0")},
        order=["m999"],
    )
    raw = [RawContent(source_id="openstax", key="prealgebra-2e:m999",
                      url="https://openstax.org/books/prealgebra-2e/pages/m999",
                      fetched_at=datetime.now(timezone.utc).isoformat(), payload=MODULE)]
    return ad.parse(raw)


def test_types_and_counts(chunks):
    by = {}
    for c in chunks:
        by.setdefault(c.content_type, []).append(c)
    assert len(by["exposition"]) == 1
    assert len(by["worked_example"]) == 1
    assert len(by["summary"]) == 1
    assert len(by["exercise_set"]) == 2  # practice + writing groups


def test_example_lifted_out_of_exposition(chunks):
    expo = next(c for c in chunks if c.content_type == "exposition")
    we = next(c for c in chunks if c.content_type == "worked_example")
    # the worked example text is in the example chunk, not the exposition chunk
    assert "Name the shaded part" in we.content
    assert "Name the shaded part" not in expo.content
    assert "More exposition prose" in expo.content


def test_math_rendered_as_latex(chunks):
    expo = next(c for c in chunks if c.content_type == "exposition")
    assert r"$\frac{1}{4}$" in expo.content


def test_ids_share_prefix_and_attribution(chunks):
    assert all(c.id.startswith("openstax-prealgebra-2e-m999-") for c in chunks)
    assert all("CC BY-NC-SA 4.0" in c.attribution for c in chunks)
    assert all(c.chapter == "4" and c.section == "1" for c in chunks)


def test_load_round_trip(tmp_path, chunks):
    conn = connect(tmp_path / "core.db", create=True)
    load_catalog(conn, {
        "source": {"id": "openstax", "full_name": "OpenStax",
                   "license": "CC BY-NC-SA 4.0",
                   "license_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
                   "base_url": "https://openstax.org"},
        "books": [{"id": "openstax-prealgebra-2e", "source_id": "openstax",
                   "title": "Prealgebra 2e", "subject": "mathematics",
                   "grade_band": "6-8", "license": "CC BY-NC-SA 4.0",
                   "url": "https://openstax.org/details/books/prealgebra-2e"}],
    })
    counts = load_chunks(conn, chunks)
    assert counts["added"] == len(chunks)
    # grade band stamped from book; FTS searchable
    hits = conn.execute(
        "SELECT id FROM chunks_fts WHERE chunks_fts MATCH 'numerator'"
    ).fetchall()
    assert len(hits) == 1
    row = conn.execute("SELECT grade_band, content_hash FROM chunks LIMIT 1").fetchone()
    assert row["grade_band"] == "6-8"
    assert row["content_hash"]
    # idempotent re-load updates, doesn't duplicate
    counts2 = load_chunks(conn, chunks)
    assert counts2["updated"] == len(chunks)
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == len(chunks)
    conn.close()
