"""Offline benchmark logic — score parsing, aggregation, topic set (no Ollama)."""

from oer_ingestion.benchmark import (
    CONDITIONS,
    DIMENSIONS,
    TOPICS,
    Plan,
    _aggregate,
    parse_scores,
)


def test_parse_scores_json():
    s = parse_scores('Here: {"standards_accuracy": 4, "content_accuracy": 5, "pedagogical_coherence": 3}')
    assert s == {"standards_accuracy": 4, "content_accuracy": 5, "pedagogical_coherence": 3}


def test_parse_scores_loose_fallback():
    s = parse_scores("standards_accuracy: 3\ncontent_accuracy = 4\npedagogical_coherence -> 5")
    assert s == {"standards_accuracy": 3, "content_accuracy": 4, "pedagogical_coherence": 5}


def test_parse_scores_garbage():
    assert parse_scores("the model rambled with no scores") == {}


def test_aggregate_computes_lift_and_target():
    plans = []
    # both strong on content, standardgraph weaker → lift ≥ 1.0
    for cond, content in (("none", 2), ("standardgraph", 3), ("both", 4.5)):
        for _ in range(2):
            plans.append(Plan("t", "S", cond, "plan",
                              {"standards_accuracy": 4, "content_accuracy": int(content),
                               "pedagogical_coherence": 4}))
    # make 'both' average 4.5
    plans[-1].scores["content_accuracy"] = 5
    plans[-2].scores["content_accuracy"] = 4
    r = _aggregate(plans)
    assert r["n_topics"] == 2
    assert r["means"]["both"]["content_accuracy"] == 4.5
    assert r["means"]["standardgraph"]["content_accuracy"] == 3.0
    assert r["content_accuracy_lift_both_vs_sg"] == 1.5
    assert r["target_met"] is True


def test_aggregate_skips_unscored():
    plans = [Plan("t", "S", c, "p", {} if c == "none" else
                  {d: 3 for d in DIMENSIONS}) for c in CONDITIONS]
    r = _aggregate(plans)
    assert r["scored"]["none"] == 0  # unscored excluded
    assert r["scored"]["both"] == 1


def test_topic_set_spans_k12():
    assert len(TOPICS) == 20
    ids = [s for _, s in TOPICS]
    assert any(".K." in i for i in ids)        # kindergarten
    assert any(".HS" in i for i in ids)         # high school
    assert all(i.startswith("CCSS.MATH.") for i in ids)
