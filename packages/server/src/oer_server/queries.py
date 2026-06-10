"""Query layer — pure functions over an open connection, spanning all attached
databases (core + optional ncsa add-on, D11). The FastMCP tool wrappers in
server.py stay thin; tests target these functions directly.
"""

import sqlite3

from oer_shared.db import attached_schemas
from oer_shared.models import SourceInfo, SourceInventory

_SCHEMA_LABELS = {"main": "core", "ncsa": "ncsa"}


def list_sources(conn: sqlite3.Connection) -> SourceInventory:
    sources: list[SourceInfo] = []
    total_chunks = 0
    total_aligned = 0
    schemas = attached_schemas(conn)
    for schema in schemas:
        rows = conn.execute(
            f"""
            SELECT s.id, s.full_name, s.license, s.last_indexed,
                   (SELECT COUNT(*) FROM {schema}.books b
                     WHERE b.source_id = s.id)                       AS books_indexed,
                   (SELECT COUNT(*) FROM {schema}.chunks c
                     WHERE c.source_id = s.id AND c.stale = 0)       AS chunks_indexed
            FROM {schema}.sources s
            ORDER BY s.id
            """
        ).fetchall()
        for r in rows:
            bands = [
                b["grade_band"]
                for b in conn.execute(
                    f"""
                    SELECT DISTINCT grade_band FROM {schema}.books
                    WHERE source_id = ? AND grade_band IS NOT NULL
                    ORDER BY grade_band
                    """,
                    (r["id"],),
                ).fetchall()
            ]
            sources.append(
                SourceInfo(
                    id=r["id"],
                    full_name=r["full_name"],
                    books_indexed=r["books_indexed"],
                    chunks_indexed=r["chunks_indexed"],
                    grade_bands=bands,
                    license=r["license"],
                    last_indexed=r["last_indexed"],
                )
            )
        total_chunks += conn.execute(
            f"SELECT COUNT(*) FROM {schema}.chunks WHERE stale = 0"
        ).fetchone()[0]
        total_aligned += conn.execute(
            f"SELECT COUNT(*) FROM {schema}.standard_alignments WHERE stale = 0"
        ).fetchone()[0]
    return SourceInventory(
        sources=sources,
        total_chunks=total_chunks,
        total_standards_aligned=total_aligned,
        databases_attached=[_SCHEMA_LABELS[s] for s in schemas],
    )
