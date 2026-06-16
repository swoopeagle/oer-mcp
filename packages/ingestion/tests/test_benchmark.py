"""Offline benchmark logic — pairwise preference parsing & aggregation (no Ollama)."""

from oer_ingestion.benchmark import TOPICS, Comparison, _aggregate, parse_pref


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
