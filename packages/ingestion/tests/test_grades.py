from oer_ingestion.grades import band_range, grade_distance, standard_grade_to_num


def test_standard_grade_to_num():
    assert standard_grade_to_num("K") == 0
    assert standard_grade_to_num("6") == 6
    assert standard_grade_to_num("HS") == 10
    assert standard_grade_to_num(None) is None
    assert standard_grade_to_num("") is None


def test_band_range():
    assert band_range("6-8") == (6, 8)
    assert band_range("K-5") == (0, 5)
    assert band_range("college") == (13, 16)
    assert band_range(None) is None
    assert band_range("unknown") is None


def test_grade_distance_inside_band_is_zero():
    assert grade_distance("6-8", "6") == 0
    assert grade_distance("6-8", "8") == 0


def test_grade_distance_outside_band():
    assert grade_distance("6-8", "K") == 6   # demotes the K mismatch we saw
    assert grade_distance("6-8", "1") == 5
    assert grade_distance("6-8", "HS") == 2  # 10 - 8


def test_grade_distance_unknown_sides_no_penalty():
    assert grade_distance(None, "6") == 0
    assert grade_distance("6-8", None) == 0
