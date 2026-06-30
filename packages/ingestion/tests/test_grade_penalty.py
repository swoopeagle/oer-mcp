"""Grade-distance penalty (D18) — scoring adjustment for cross-grade alignments."""

from oer_ingestion.grades import grade_distance, standard_grade_to_num, band_range
from oer_ingestion.align import GRADE_PENALTY


def test_grade_distance_zero_when_inside_band():
    """A standard inside the chunk's grade band incurs no penalty."""
    assert grade_distance("6-8", "6") == 0
    assert grade_distance("6-8", "7") == 0
    assert grade_distance("6-8", "8") == 0
    assert grade_distance("k-5", "3") == 0
    assert grade_distance("9-12", "10") == 0  # HS ≈ 10


def test_grade_distance_below_band():
    """A standard below the band: penalty distance = band_min - standard_grade."""
    # K-5 band: 0-5. If standard is K (0), distance = 5 - 0 = 5.
    assert grade_distance("k-5", "K") == 0  # K is at the min of k-5
    assert grade_distance("6-8", "K") == 6  # K=0, band min=6, distance=6
    assert grade_distance("6-8", "3") == 3  # 3, band min=6, distance=3
    assert grade_distance("6-8", "1") == 5


def test_grade_distance_above_band():
    """A standard above the band: penalty distance = standard_grade - band_max."""
    assert grade_distance("6-8", "9") == 1  # 9, band max=8, distance=1
    assert grade_distance("6-8", "HS") == 2  # HS=10, band max=8, distance=2
    assert grade_distance("k-5", "HS") == 5  # HS=10, band max=5, distance=5


def test_grade_distance_unknown_grades():
    """Unknown grades (None, empty, invalid) return 0 (no penalty)."""
    assert grade_distance("6-8", None) == 0
    assert grade_distance("6-8", "") == 0
    assert grade_distance("6-8", "UNKNOWN") == 0
    assert grade_distance(None, "5") == 0
    assert grade_distance("", "5") == 0


def test_penalty_application():
    """Score penalty is GRADE_PENALTY * distance."""
    assert GRADE_PENALTY == 0.02

    # If a match has raw score 0.85 and grade distance 3:
    # adjusted = 0.85 - (0.02 * 3) = 0.85 - 0.06 = 0.79
    raw_score = 0.85
    distance = grade_distance("6-8", "3")  # 3 grade-years out
    penalty = GRADE_PENALTY * distance
    adjusted = raw_score - penalty

    assert distance == 3
    assert penalty == 0.06
    assert adjusted == 0.79


def test_penalty_boundary_monotonic():
    """More distance = lower adjusted score (monotonic)."""
    import pytest
    raw_score = 0.80

    # Test distances 0 through 5
    adjusted_scores = []
    for d in range(6):
        adjusted = raw_score - (GRADE_PENALTY * d)
        adjusted_scores.append(adjusted)

    # Verify monotonic decrease
    for i in range(len(adjusted_scores) - 1):
        assert adjusted_scores[i] > adjusted_scores[i + 1]

    # Specific values (with floating point tolerance)
    assert adjusted_scores[0] == pytest.approx(0.80, abs=1e-9)  # distance 0
    assert adjusted_scores[1] == pytest.approx(0.78, abs=1e-9)  # distance 1
    assert adjusted_scores[5] == pytest.approx(0.70, abs=1e-9)  # distance 5


def test_grade_to_numeric_conversion():
    """standard_grade_to_num handles K, HS, and digit grades."""
    assert standard_grade_to_num("K") == 0
    assert standard_grade_to_num("k") == 0  # case-insensitive
    assert standard_grade_to_num("1") == 1
    assert standard_grade_to_num("8") == 8
    assert standard_grade_to_num("HS") == 10
    assert standard_grade_to_num("hs") == 10  # case-insensitive
    assert standard_grade_to_num(None) is None
    assert standard_grade_to_num("") is None
    assert standard_grade_to_num("UNKNOWN") is None


def test_band_range_lookup():
    """band_range maps grade_band strings to (min, max) tuples."""
    assert band_range("k-5") == (0, 5)
    assert band_range("6-8") == (6, 8)
    assert band_range("9-12") == (9, 12)
    assert band_range("k-8") == (0, 8)
    assert band_range("college") == (13, 16)
    assert band_range("K-5") == (0, 5)  # case-insensitive
    assert band_range(None) is None
    assert band_range("") is None
    assert band_range("unknown") is None
