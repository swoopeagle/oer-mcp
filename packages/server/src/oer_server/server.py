"""OER MCP stdio server.

M0 scope: server boots, list_sources works against the two-database layout.
Remaining tools (fetch_for_standard, search_content, get_chunk, check_coverage)
land in M1–M2 per BUILD_PLAN.md.
"""

from fastmcp import FastMCP

from oer_shared import config
from oer_shared.db import connect

mcp = FastMCP(
    "oer-mcp",
    instructions=(
        "Curriculum content retrieval layer: open-licensed math textbook and "
        "lesson content (OpenStax and others), chunked by concept and aligned "
        "to curriculum standards. Companion to the StandardGraph standards MCP. "
        "Every content response carries an attribution string that must be "
        "preserved in downstream output."
    ),
)

_conn = None


def get_conn():
    global _conn
    if _conn is None:
        _conn = connect(config.CORE_DB_PATH, config.ADDON_DB_PATH)
    return _conn


@mcp.tool()
def list_sources() -> dict:
    """Live inventory of indexed OER sources, books, and chunks, including
    which databases are attached (core CC BY / optional NC-SA add-on)."""
    from . import queries

    try:
        return queries.list_sources(get_conn()).model_dump()
    except Exception as exc:  # graceful degradation — structured errors, never bare exceptions
        return {"error": type(exc).__name__, "detail": str(exc)}


@mcp.tool()
def fetch_for_standard(
    standard_id: str,
    source: str | None = None,
    content_type: str | None = None,
    limit: int = 3,
    include_content: bool = True,
) -> list[dict] | dict:
    """Return OER content that teaches a given curriculum standard, by its
    StandardGraph ID (e.g. 'CCSS.MATH.6.RP.A.3'). Results are ranked by
    alignment confidence (human > publisher guide > embedding) then score.
    Optionally filter by source or content_type (exposition / worked_example /
    exercise_set / summary). Every result carries an attribution string to
    preserve in downstream output."""
    from . import queries

    try:
        return queries.fetch_for_standard(
            get_conn(), standard_id, source=source, content_type=content_type,
            limit=limit, include_content=include_content,
        )
    except Exception as exc:
        return {"error": type(exc).__name__, "detail": str(exc)}


@mcp.tool()
def search_content(
    query: str,
    standard_id: str | None = None,
    source: str | None = None,
    grade_band: str | None = None,
    content_type: str | None = None,
    limit: int = 5,
    include_content: bool = False,
) -> dict:
    """Find OER content by natural-language concept (e.g. 'dividing fractions').
    Hybrid semantic + keyword search; degrades to keyword-only when the embedder
    is unavailable (response 'search_mode' says which). Optionally filter by
    source, grade_band, content_type, or re-rank toward a standard_id. Set
    include_content=true to return full text (omitted by default to save tokens).
    Every result carries an attribution string to preserve downstream."""
    from . import queries
    from .embedding import embed_query

    try:
        return queries.search_content(
            get_conn(), query, embed_query=embed_query, standard_id=standard_id,
            source=source, grade_band=grade_band, content_type=content_type,
            limit=limit, include_content=include_content,
        )
    except Exception as exc:
        return {"error": type(exc).__name__, "detail": str(exc)}


@mcp.tool()
def check_coverage(standard_id: str, source: str | None = None) -> dict:
    """Report how completely indexed OER content covers a standard or cluster
    (e.g. 'CCSS.MATH.6.RP.3' or a cluster prefix). Returns per-standard coverage
    bands (strong/moderate/light/none) and surfaces gaps — standards with no
    aligned content. Optionally restrict to one source. Gap detection needs the
    StandardGraph database; the response flags if it was unavailable."""
    from . import queries

    try:
        return queries.check_coverage(
            get_conn(), standard_id,
            sg_db_path=config.STANDARDGRAPH_DB_PATH, source=source,
        )
    except Exception as exc:
        return {"error": type(exc).__name__, "detail": str(exc)}


@mcp.tool()
def get_chunk(chunk_id: str, include_adjacent: bool = False) -> dict:
    """Retrieve a specific OER content chunk by its ID — full content,
    attribution (preserve this in any downstream output), and the curriculum
    standards it aligns to. Set include_adjacent to also get neighbouring
    section IDs."""
    from . import queries

    try:
        return queries.get_chunk(get_conn(), chunk_id, include_adjacent)
    except Exception as exc:
        return {"error": type(exc).__name__, "detail": str(exc)}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
