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
