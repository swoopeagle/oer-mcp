"""SourceAdapter base class (PRD §11) — every source implements this interface;
the pipeline only ever calls the interface. Source-specific logic (API routes,
scrape methods, markup parsing) lives entirely inside the adapter.
"""

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel

from oer_shared.models import ContentChunk


class RawContent(BaseModel):
    """One raw item as fetched, before parsing. Snapshotted to disk before
    chunking on every fetch (PRD §11 — snapshot writing is not optional)."""

    source_id: str
    key: str  # source-native identifier, e.g. "m81285" or a Khan lesson slug
    url: str
    fetched_at: str  # ISO 8601
    payload: str  # raw CNXML / HTML / JSON text


class ValidationResult(BaseModel):
    ok: bool
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, int] = {}


class SourceAdapter(ABC):
    source_id: ClassVar[str]

    @abstractmethod
    def fetch(self) -> list[RawContent]:
        """Pull raw content from the source."""

    @abstractmethod
    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        """Normalize raw content into typed sub-chunks (D14)."""

    @abstractmethod
    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        """Check chunk counts, required fields, content integrity."""
