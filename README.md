# OER MCP

**Curriculum content retrieval layer for LLMs.** Open-licensed math textbook and lesson content (OpenStax, more coming), chunked by concept, aligned to curriculum standards, and queryable by StandardGraph standard ID. Companion to [StandardGraph](https://github.com/swoopeagle/standardgraph).

> ⚠️ Pre-release — under active development. See `../PRD.md` and `../BUILD_PLAN.md` (PRD v1.2, Phase 1 in progress).

## Layout

```
packages/
├── shared/      # config, schema.sql, db helpers (two-DB attach), Pydantic models
├── ingestion/   # 7-stage pipeline + SourceAdapter implementations
└── server/      # FastMCP stdio server — the five retrieval tools
docs/spikes/     # dated spike verdicts (S1 OpenStax route, S2 Khan gate, S3 correlation guides)
```

## Licensing model (D11)

Two databases, partitioned **by content license**:

- `oer_core.db` — CC BY content only; ships pre-built as the default install.
- `oer_ncsa.db` — CC BY-NC-SA content (Khan Academy, OpenStax 2e editions); optional add-on with its own license terms. Attached automatically when present.

Every chunk carries a non-nullable attribution string, surfaced in every tool response.

## Dev

```bash
uv sync
uv run pytest
OER_CORE_DB_PATH=data/oer_core.db uv run oer-mcp   # stdio server
```
