"""OpenStax adapter — CNXML source from github.com/openstax/osbooks-* repos.

Route verified in docs/spikes/S1-openstax-route.md:
  META-INF/books.xml → collections/{slug}.collection.xml → modules/{id}/index.cnxml
License is read per-book from collection.xml md:license (2e editions are
CC BY-NC-SA, first editions CC BY — never assume per source).

Implementation lands in M1.
"""

from .base import RawContent, SourceAdapter, ValidationResult
from oer_shared.models import ContentChunk


class OpenStaxAdapter(SourceAdapter):
    source_id = "openstax"

    def fetch(self) -> list[RawContent]:
        raise NotImplementedError("M1 — see docs/spikes/S1-openstax-route.md")

    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        raise NotImplementedError("M1 — typed sub-chunk splitter (D14)")

    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        raise NotImplementedError("M1")
