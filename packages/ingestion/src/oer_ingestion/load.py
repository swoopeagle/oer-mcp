"""Stage 3 — load chunks into a database; Stage 1 snapshot writing (PRD §11).

Idempotent: upserts sources/books/chunks by primary key. Chunks use an
explicit UPDATE-else-INSERT (not INSERT OR REPLACE) so the FTS5 delete/insert
triggers stay in sync. Grade band is stamped onto chunks from their book.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from oer_shared.models import ContentChunk

from .adapters.base import RawContent


def write_snapshots(
    raw: list[RawContent], snapshot_root: str | Path, *, ext: str = "xml"
) -> dict[str, str]:
    """Persist raw fetched payloads before chunking. Returns {key: path}.
    Snapshot writing is not optional (PRD §11)."""
    root = Path(snapshot_root)
    paths: dict[str, str] = {}
    for item in raw:
        date = item.fetched_at[:10]
        safe_key = item.key.replace(":", "__").replace("/", "_")
        dest = root / item.source_id / date / f"{safe_key}.{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(item.payload, encoding="utf-8")
        paths[item.key] = str(dest)
    return paths


def load_catalog(conn: sqlite3.Connection, catalog: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    s = catalog["source"]
    conn.execute(
        """INSERT INTO sources (id, full_name, license, license_url, base_url, last_indexed)
           VALUES (:id, :full_name, :license, :license_url, :base_url, :last_indexed)
           ON CONFLICT(id) DO UPDATE SET
             full_name=excluded.full_name, license=excluded.license,
             license_url=excluded.license_url, base_url=excluded.base_url,
             last_indexed=excluded.last_indexed""",
        {**s, "last_indexed": now},
    )
    for b in catalog["books"]:
        conn.execute(
            """INSERT INTO books (id, source_id, title, subject, grade_band, license, url)
               VALUES (:id, :source_id, :title, :subject, :grade_band, :license, :url)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, grade_band=excluded.grade_band,
                 license=excluded.license, url=excluded.url""",
            b,
        )
    conn.commit()


def load_chunks(
    conn: sqlite3.Connection,
    chunks: list[ContentChunk],
    *,
    snapshot_paths: dict[str, str] | None = None,
) -> dict[str, int]:
    """Upsert chunks. Returns {'added', 'updated'} counts."""
    now = datetime.now(timezone.utc).isoformat()
    grade_by_book = {
        r["id"]: r["grade_band"]
        for r in conn.execute("SELECT id, grade_band FROM books").fetchall()
    }
    added = updated = 0
    for c in chunks:
        content_hash = hashlib.sha256(c.content.encode()).hexdigest()
        grade = c.grade_band or grade_by_book.get(c.book_id)
        snap = None
        if snapshot_paths:
            # chunk id prefix is openstax-{slug}-{module}; map back to fetch key
            snap = _snapshot_for(c, snapshot_paths)
        exists = conn.execute("SELECT 1 FROM chunks WHERE id=?", (c.id,)).fetchone()
        params = {
            "id": c.id, "book_id": c.book_id, "source_id": c.source_id,
            "title": c.title, "content": c.content, "content_type": c.content_type,
            "chapter": c.chapter, "section": c.section, "grade_band": grade,
            "word_count": c.word_count, "source_url": c.source_url,
            "attribution": c.attribution, "snapshot_path": snap,
            "content_hash": content_hash, "last_verified": now,
            # assessment-only (None for non-assessment chunks)
            "item_type": c.item_type, "dok_level": c.dok_level,
            "answer_key": c.answer_key, "exam_series": c.exam_series,
            "exam_year": c.exam_year, "difficulty": c.difficulty,
            "item_generation": c.item_generation,
        }
        if exists:
            conn.execute(
                """UPDATE chunks SET book_id=:book_id, source_id=:source_id,
                     title=:title, content=:content, content_type=:content_type,
                     chapter=:chapter, section=:section, grade_band=:grade_band,
                     word_count=:word_count, source_url=:source_url,
                     attribution=:attribution, snapshot_path=:snapshot_path,
                     content_hash=:content_hash, last_verified=:last_verified,
                     item_type=:item_type, dok_level=:dok_level,
                     answer_key=:answer_key, exam_series=:exam_series,
                     exam_year=:exam_year, difficulty=:difficulty,
                     item_generation=:item_generation, stale=0
                   WHERE id=:id""",
                params,
            )
            updated += 1
        else:
            conn.execute(
                """INSERT INTO chunks (id, book_id, source_id, title, content,
                     content_type, chapter, section, grade_band, word_count,
                     source_url, attribution, snapshot_path, content_hash, last_verified,
                     item_type, dok_level, answer_key, exam_series, exam_year,
                     difficulty, item_generation)
                   VALUES (:id, :book_id, :source_id, :title, :content,
                     :content_type, :chapter, :section, :grade_band, :word_count,
                     :source_url, :attribution, :snapshot_path, :content_hash,
                     :last_verified, :item_type, :dok_level, :answer_key,
                     :exam_series, :exam_year, :difficulty, :item_generation)""",
                params,
            )
            added += 1
    conn.commit()
    return {"added": added, "updated": updated}


def load_alignments(conn: sqlite3.Connection, chunks: list[ContentChunk]) -> dict[str, int]:
    """Persist chunk-level standard_alignments (e.g. IM publisher_guide CCSS tags).
    Upserts on UNIQUE(chunk_id, standard_id); a higher-confidence source overwrites
    a weaker one but never the reverse, and human-verified rows are never touched."""
    _RANK = {"embedding": 1, "llm_verified": 2, "publisher_guide": 3, "human": 4}
    added = updated = 0
    for c in chunks:
        for a in c.standard_alignments:
            row = conn.execute(
                "SELECT alignment_source, verified_by_human FROM standard_alignments "
                "WHERE chunk_id=? AND standard_id=?", (c.id, a.standard_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO standard_alignments
                         (chunk_id, standard_id, standard_system, alignment_score,
                          alignment_source, coverage_notes, verified_by_human)
                       VALUES (?,?,?,?,?,?,?)""",
                    (c.id, a.standard_id, a.standard_system, a.alignment_score,
                     a.alignment_source, a.coverage_notes, int(a.verified_by_human)),
                )
                added += 1
            else:
                existing_src, human = row[0], row[1]
                if human:  # never override a human decision
                    continue
                if _RANK.get(a.alignment_source, 0) >= _RANK.get(existing_src, 0):
                    conn.execute(
                        """UPDATE standard_alignments
                             SET standard_system=?, alignment_score=?, alignment_source=?,
                                 coverage_notes=?, flagged_for_review=0, stale=0
                           WHERE chunk_id=? AND standard_id=?""",
                        (a.standard_system, a.alignment_score, a.alignment_source,
                         a.coverage_notes, c.id, a.standard_id),
                    )
                    updated += 1
    conn.commit()
    return {"added": added, "updated": updated}


def _snapshot_for(chunk: ContentChunk, snapshot_paths: dict[str, str]) -> str | None:
    # chunk.id = "openstax-{slug}-{module}-{suffix}"; fetch key = "{slug}:{module}"
    for key, path in snapshot_paths.items():
        slug, mid = key.split(":", 1)
        if chunk.id.startswith(f"openstax-{slug}-{mid}-"):
            return path
    return None


def record_run(
    conn: sqlite3.Connection,
    source_id: str,
    counts: dict[str, int],
    *,
    warnings: list[str] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO pipeline_runs
             (run_date, source_id, chunks_fetched, chunks_added, warnings, completed)
           VALUES (?, ?, ?, ?, ?, 1)""",
        (
            datetime.now(timezone.utc).isoformat(),
            source_id,
            counts.get("added", 0) + counts.get("updated", 0),
            counts.get("added", 0),
            json.dumps(warnings or []),
        ),
    )
    conn.commit()
