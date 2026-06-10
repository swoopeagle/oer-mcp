"""Khan Academy adapter — structured scrape (public API retired July 2020).

Gated by Spike S2 (go/no-go): articles + exercise sets only in Phase 1 (D7);
on persistent gate failure CK-12 is promoted instead (D12).

Implementation lands in M3, path set by the S2 verdict.
"""

from .base import RawContent, SourceAdapter, ValidationResult
from oer_shared.models import ContentChunk


class KhanAcademyAdapter(SourceAdapter):
    source_id = "khan-academy"

    def fetch(self) -> list[RawContent]:
        raise NotImplementedError("M3 — gated by Spike S2")

    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        raise NotImplementedError("M3 — gated by Spike S2")

    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        raise NotImplementedError("M3 — gated by Spike S2")
