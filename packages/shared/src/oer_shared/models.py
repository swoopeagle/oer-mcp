"""Pydantic v2 models — PRD §7.4 plus tool response shapes."""

from typing import Literal

from pydantic import BaseModel, Field

ContentType = Literal["exposition", "worked_example", "exercise_set", "summary"]
AlignmentSource = Literal["embedding", "publisher_guide", "human"]


class StandardAlignment(BaseModel):
    standard_id: str  # "CCSS.MATH.6.RP.A.3"
    standard_system: str = "ccss"
    alignment_score: float = Field(ge=0.0, le=1.0)
    alignment_source: AlignmentSource
    coverage_notes: str | None = None
    verified_by_human: bool = False


class ContentChunk(BaseModel):
    id: str  # "openstax-prealgebra-2e-m81285-expo"
    book_id: str
    source_id: str
    title: str
    content: str
    content_type: ContentType
    chapter: str | None = None
    section: str | None = None
    grade_band: str | None = None
    word_count: int
    source_url: str
    attribution: str  # non-negotiable (D4)
    standard_alignments: list[StandardAlignment] = []


class ChunkResult(BaseModel):
    """Tool response shape for fetch_for_standard / search_content / get_chunk."""

    chunk_id: str
    source: str
    title: str
    content_type: ContentType
    grade_band: str | None = None
    alignment_score: float | None = None
    alignment_source: AlignmentSource | None = None
    coverage_notes: str | None = None
    content: str | None = None  # omitted when include_content=False
    source_url: str
    attribution: str


class SourceInfo(BaseModel):
    id: str
    full_name: str
    books_indexed: int
    chunks_indexed: int
    grade_bands: list[str]
    license: str
    last_indexed: str


class SourceInventory(BaseModel):
    sources: list[SourceInfo]
    total_chunks: int
    total_standards_aligned: int
    databases_attached: list[str]  # ["core"] or ["core", "ncsa"] (D11)
