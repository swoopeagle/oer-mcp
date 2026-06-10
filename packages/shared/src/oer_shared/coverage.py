"""Coverage bands — source-aware (M1 checkpoint, 2026-06-10).

Embedding cosine between long chunk text and short standard text compresses
into a lower range than publisher-guide/human confidence scores (observed max
~0.83 for OpenStax embedding alignment). So coverage bands are keyed by
alignment_source: high-confidence sources keep the original PRD scale; the
embedding scale is shifted down. This keeps check_coverage honest instead of
reporting everything as "moderate".
"""

from typing import Literal

CoverageLevel = Literal["strong", "moderate", "light", "none"]

# (strong_min, moderate_min, light_min). Below light_min → "none".
_BANDS = {
    "embedding": (0.78, 0.70, 0.65),
    "publisher_guide": (0.85, 0.65, 0.45),
    "human": (0.85, 0.65, 0.45),
}

# Threshold at which a freshly-computed embedding alignment is flagged for the
# gemma annotate stage. Tied to the embedding "strong" band.
EMBED_ANNOTATE_THRESHOLD = _BANDS["embedding"][0]


def coverage_band(score: float, source: str = "embedding") -> CoverageLevel:
    strong, moderate, light = _BANDS.get(source, _BANDS["embedding"])
    if score >= strong:
        return "strong"
    if score >= moderate:
        return "moderate"
    if score >= light:
        return "light"
    return "none"
