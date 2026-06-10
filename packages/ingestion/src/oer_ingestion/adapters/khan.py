"""Khan Academy adapter — Kolibri / Learning Equality channel (D16, Spike S2).

Khan's own site is fully bot-walled; acquisition is via Learning Equality's
published Kolibri channel DB + CDN instead of scraping:
  channel DB:  https://studio.learningequality.org/content/databases/{channel_id}.sqlite3
  CDN files:   https://studio.learningequality.org/content/storage/{c0}/{c1}/{checksum}.{ext}
  channel_id:  c9d7f950ab6b5a1199e3d6c10d7f0103  (Khan Academy, English - US curriculum)

Phase 1 scope: video transcripts (VTT, CC BY-NC-SA) → exposition chunks.
Perseus exercises are reference-only pending a licensing decision (see S2).
No CCSS tags in the export → embedding-only alignment.

Implementation lands in M3.
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
