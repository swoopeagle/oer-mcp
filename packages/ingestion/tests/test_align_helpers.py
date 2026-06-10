from oer_ingestion.align import _is_generic_exercise


def test_generic_exercise_groups_excluded():
    assert _is_generic_exercise("exercise_set", "Subtract Whole Numbers — Writing Exercises")
    assert _is_generic_exercise("exercise_set", "Divide Whole Numbers — Self Check")


def test_substantive_exercises_kept():
    # Practice Makes Perfect / Everyday Math are real standard-relevant practice
    assert not _is_generic_exercise("exercise_set", "Divide Whole Numbers — Practice Makes Perfect")
    assert not _is_generic_exercise("exercise_set", "Ratios — Everyday Math")


def test_non_exercise_types_never_excluded():
    assert not _is_generic_exercise("exposition", "Anything — Writing Exercises")
    assert not _is_generic_exercise("worked_example", "Self Check")
