"""Query layer — pure functions over an open connection, spanning all attached
databases (core + optional ncsa add-on, D11). The FastMCP tool wrappers in
server.py stay thin; tests target these functions directly.
"""

import sqlite3

from oer_shared.db import attached_schemas
from oer_shared.models import ChunkResult, SourceInfo, SourceInventory, StandardAlignment

_SCHEMA_LABELS = {"main": "core", "ncsa": "ncsa"}


def _alignments_for(conn, schema, chunk_id) -> list[StandardAlignment]:
    rows = conn.execute(
        f"""SELECT standard_id, standard_system, alignment_score, alignment_source,
                   coverage_notes, verified_by_human
            FROM {schema}.standard_alignments
            WHERE chunk_id = ? AND stale = 0
            ORDER BY alignment_score DESC""",
        (chunk_id,),
    ).fetchall()
    return [
        StandardAlignment(
            standard_id=r["standard_id"],
            standard_system=r["standard_system"],
            alignment_score=r["alignment_score"],
            alignment_source=r["alignment_source"],
            coverage_notes=r["coverage_notes"],
            verified_by_human=bool(r["verified_by_human"]),
        )
        for r in rows
    ]


def get_chunk(
    conn: sqlite3.Connection, chunk_id: str, include_adjacent: bool = False
) -> dict:
    """Retrieve one chunk by ID, spanning attached databases. Returns a dict
    with the chunk's content, attribution, and standard alignments, or a
    structured not-found result."""
    for schema in attached_schemas(conn):
        row = conn.execute(
            f"SELECT *, rowid FROM {schema}.chunks WHERE id = ? AND stale = 0",
            (chunk_id,),
        ).fetchone()
        if row is None:
            continue
        result = ChunkResult(
            chunk_id=row["id"],
            source=row["source_id"],
            title=row["title"],
            content_type=row["content_type"],
            grade_band=row["grade_band"],
            content=row["content"],
            source_url=row["source_url"],
            attribution=row["attribution"],
        )
        payload = result.model_dump()
        payload["chapter"] = row["chapter"]
        payload["section"] = row["section"]
        payload["alignments"] = [
            a.model_dump() for a in _alignments_for(conn, schema, chunk_id)
        ]
        if include_adjacent:
            payload["adjacent"] = _adjacent(conn, schema, row)
        return payload
    return {"chunk_id": chunk_id, "result": "not_found"}


def _adjacent(conn, schema, row) -> dict:
    """Preceding/following chunk IDs within the same book, by rowid order."""
    prev = conn.execute(
        f"SELECT id FROM {schema}.chunks WHERE book_id=? AND rowid<? AND stale=0 "
        "ORDER BY rowid DESC LIMIT 1",
        (row["book_id"], row["rowid"]),
    ).fetchone()
    nxt = conn.execute(
        f"SELECT id FROM {schema}.chunks WHERE book_id=? AND rowid>? AND stale=0 "
        "ORDER BY rowid ASC LIMIT 1",
        (row["book_id"], row["rowid"]),
    ).fetchone()
    return {
        "previous": prev["id"] if prev else None,
        "next": nxt["id"] if nxt else None,
    }


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
