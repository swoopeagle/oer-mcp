"""Offline benchmark logic — pairwise preference parsing & aggregation (no Ollama)."""

from oer_ingestion.benchmark import (
    TOPICS,
    Comparison,
    _aggregate,
    _judge_reference,
    _oer_context,
    parse_pref,
)


def test_oer_context_reads_fetch_envelope():
    """Regression: fetch_for_standard returns a {standard_id,count,results} envelope
    (D-S4), not a bare list. _oer_context must read results out of it — otherwise
    the benchmark's 'both' condition (and judge reference) silently get no OER."""

    class EnvelopeQ:
        def fetch_for_standard(self, conn, sid, limit=2, include_content=True):
            return {"standard_id": sid, "count": 1,
                    "results": [{"attribution": "OpenStax Prealgebra", "content": "A ratio compares two quantities."}]}

    ctx = _oer_context(None, "CCSS.MATH.6.RP.3", EnvelopeQ())
    assert "OpenStax Prealgebra" in ctx and "ratio compares" in ctx

    class EmptyEnvelopeQ:
        def fetch_for_standard(self, conn, sid, limit=2, include_content=True):
            return {"standard_id": sid, "count": 0, "results": []}

    assert _oer_context(None, "CCSS.MATH.K.CC.5", EmptyEnvelopeQ()) == ""


def test_judge_reference_is_ground_truth_with_fallback():
    """The judge yardstick is the standard's real OER content, and never blank."""

    class WithContent:
        def fetch_for_standard(self, conn, sid, limit=2, include_content=True):
            return [{"attribution": "OpenStax Prealgebra 2e",
                     "content": "Worked example: 2^3 * 2^4 = 2^7"}]

    ref = _judge_reference(None, "CCSS.MATH.8.EE.1", WithContent())
    assert "OpenStax Prealgebra 2e" in ref and "2^7" in ref

    class NoContent:
        def fetch_for_standard(self, conn, sid, limit=2, include_content=True):
            return {"result": "no_content"}  # fetch_for_standard's empty envelope

    ref_empty = _judge_reference(None, "CCSS.MATH.8.EE.1", NoContent())
    assert ref_empty == "(no reference materials available for this standard)"
    assert ref_empty.strip()  # never a blank yardstick


def test_parse_pref():
    assert parse_pref("A") == "A"
    assert parse_pref("B") == "B"
    assert parse_pref("TIE") == "TIE"
    assert parse_pref("The better one is B.") == "B"
    assert parse_pref("They are equivalent, TIE") == "TIE"
    assert parse_pref("neither, hard to say") is None


def test_aggregate_win_rate_and_target():
    comps = []
    # both beats standardgraph 7, loses 2, ties 1 → win_rate 7/9 ≈ 0.78 ≥ 0.60
    for _ in range(7):
        comps.append(Comparison("t", "S", "both", "standardgraph", "both"))
    for _ in range(2):
        comps.append(Comparison("t", "S", "standardgraph", "both", "standardgraph"))
    comps.append(Comparison("t", "S", "both", "standardgraph", "tie"))
    r = _aggregate(comps, n_topics=10)
    bvs = r["comparisons"]["both_vs_standardgraph"]
    assert bvs["wins"] == 7 and bvs["losses"] == 2 and bvs["ties"] == 1
    assert bvs["win_rate"] == round(7 / 9, 3)
    assert r["both_vs_standardgraph_win_rate"] == round(7 / 9, 3)
    assert r["target_met"] is True


def test_aggregate_target_not_met_and_unparsed():
    comps = [Comparison("t", "S", "both", "standardgraph", "standardgraph"),
             Comparison("t", "S", "both", "standardgraph", "both"),
             Comparison("t", "S", "both", "standardgraph", None)]  # unparsed
    r = _aggregate(comps, n_topics=3)
    bvs = r["comparisons"]["both_vs_standardgraph"]
    assert bvs["unparsed"] == 1
    assert bvs["win_rate"] == 0.5  # 1 win / 2 decisive
    assert r["target_met"] is False


def test_winner_mapped_regardless_of_ab_order():
    # both shown as B and chosen → both wins (order independence)
    comps = [Comparison("t", "S", "standardgraph", "both", "both")]
    r = _aggregate(comps, n_topics=1)
    assert r["comparisons"]["both_vs_standardgraph"]["wins"] == 1


def test_topic_set_spans_k12():
    assert len(TOPICS) == 20
    ids = [s for _, s in TOPICS]
    assert any(".K." in i for i in ids) and any(".HS" in i for i in ids)
    assert all(i.startswith("CCSS.MATH.") for i in ids)
