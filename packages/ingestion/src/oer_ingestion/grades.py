"""Grade-band ↔ numeric helpers for the alignment grade-distance penalty
(M1 checkpoint fix #3). CCSS standard grades are K, 1–8, HS; chunk grade_bands
are coarse ranges like "6-8", "9-12", "K-5", "college".
"""

from __future__ import annotations

# Numeric grade line: K=0, 1..8, high school ≈ 10, college ≈ 14.
_BAND_RANGES = {
    "k-5": (0, 5),
    "k-8": (0, 8),
    "6-8": (6, 8),
    "9-12": (9, 12),
    "college": (13, 16),
}


def standard_grade_to_num(grade: str | None) -> int | None:
    if not grade:
        return None
    g = grade.strip().upper()
    if g == "K":
        return 0
    if g == "HS":
        return 10
    return int(g) if g.isdigit() else None


def band_range(grade_band: str | None) -> tuple[int, int] | None:
    if not grade_band:
        return None
    return _BAND_RANGES.get(grade_band.strip().lower())


def grade_distance(grade_band: str | None, standard_grade: str | None) -> int:
    """Grade-years the standard sits outside the chunk's band (0 if inside or
    if either side is unknown)."""
    rng = band_range(grade_band)
    num = standard_grade_to_num(standard_grade)
    if rng is None or num is None:
        return 0
    lo, hi = rng
    if num < lo:
        return lo - num
    if num > hi:
        return num - hi
    return 0
