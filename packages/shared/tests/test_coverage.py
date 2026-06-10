from oer_shared.coverage import EMBED_ANNOTATE_THRESHOLD, coverage_band


def test_embedding_scale_shifted_down():
    # 0.80 is "strong" on the embedding scale but only "moderate" for a
    # publisher guide — the whole point of source-aware bands (M1 checkpoint).
    assert coverage_band(0.80, "embedding") == "strong"
    assert coverage_band(0.80, "publisher_guide") == "moderate"


def test_embedding_bands():
    assert coverage_band(0.78, "embedding") == "strong"
    assert coverage_band(0.72, "embedding") == "moderate"
    assert coverage_band(0.66, "embedding") == "light"
    assert coverage_band(0.64, "embedding") == "none"


def test_high_confidence_bands():
    assert coverage_band(0.90, "human") == "strong"
    assert coverage_band(0.50, "publisher_guide") == "light"
    assert coverage_band(0.40, "publisher_guide") == "none"


def test_annotate_threshold_matches_embedding_strong():
    assert EMBED_ANNOTATE_THRESHOLD == 0.78
    assert coverage_band(EMBED_ANNOTATE_THRESHOLD, "embedding") == "strong"
