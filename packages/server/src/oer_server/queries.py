"""Query layer — pure functions over an open connection, spanning all attached
databases (core + optional ncsa add-on, D11). The FastMCP tool wrappers in
server.py stay thin; tests target these functions directly.
"""

import re
import sqlite3

import numpy as np

from oer_shared.db import attached_schemas
from oer_shared.models import ChunkResult, SourceInfo, SourceInventory, StandardAlignment

_SCHEMA_LABELS = {"main": "core", "ncsa": "ncsa", "ap": "ap"}


def _fts_match(query: str) -> str | None:
    """Sanitize a free-text query into a safe FTS5 MATCH expression (OR of
    quoted terms — recall-oriented; BM25 floats multi-term matches up)."""
    terms = re.findall(r"\w+", query.lower())
    if not terms:
        return None
    return " OR ".join(f'"{t}"' for t in terms)


def _has_assessment_columns(conn, schema) -> bool:
    """True if this schema's chunks table carries the assessment columns.
    Old DBs built before the assessment feature lack them (query_only server
    can't migrate); callers skip the item lookup for such schemas."""
    cols = {r["name"] for r in conn.execute(f"PRAGMA {schema}.table_info(chunks)")}
    return "exam_series" in cols


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
            item_type=row["item_type"],
            dok_level=row["dok_level"],
            answer_key=row["answer_key"],
            exam_series=row["exam_series"],
            exam_year=row["exam_year"],
            difficulty=row["difficulty"],
            item_generation=row["item_generation"],
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


def _keyword_hits(conn, schema, match, filters, params) -> list[str]:
    """Chunk IDs from FTS5, BM25-ranked, honoring filters. Best first."""
    where = " AND ".join(["c.stale = 0", *filters])
    rows = conn.execute(
        f"""SELECT c.id
            FROM {schema}.chunks_fts f
            JOIN {schema}.chunks c ON c.rowid = f.rowid
            WHERE f.chunks_fts MATCH ? AND {where}
            ORDER BY bm25(f.chunks_fts) ASC
            LIMIT 50""",
        (match, *params),
    ).fetchall()
    return [r["id"] for r in rows]


def _semantic_hits(conn, schema, qvec, filters, params) -> list[str]:
    """Chunk IDs by cosine to the query vector, honoring filters. Best first.

    Uses the in-memory normalized matrix from embed_cache; the per-call SQL
    is a cheap metadata-only filter query (no vector BLOBs read each time).
    """
    from .embed_cache import get_matrix

    ids, mat, _ = get_matrix(conn, schema)
    if len(ids) == 0:
        return []

    # Get the allowed chunk IDs after applying filters (no vector I/O).
    where = " AND ".join(["c.stale = 0", *filters])
    allowed_rows = conn.execute(
        f"""SELECT e.chunk_id
            FROM {schema}.chunk_embeddings e
            JOIN {schema}.chunks c ON c.id = e.chunk_id
            WHERE {where}""",
        tuple(params),
    ).fetchall()
    if not allowed_rows:
        return []

    allowed_set = {r["chunk_id"] for r in allowed_rows}
    mask = np.array([cid in allowed_set for cid in ids], dtype=bool)
    if not mask.any():
        return []

    restricted_mat = mat[mask]
    restricted_ids = [ids[i] for i, m in enumerate(mask) if m]

    qv = qvec / (np.linalg.norm(qvec) + 1e-9)
    sims = restricted_mat @ qv
    order = np.argsort(-sims)[:50]
    return [restricted_ids[i] for i in order]


def _rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal-rank fusion of several ranked ID lists → one merged ranking."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda c: scores[c], reverse=True)


def search_content(
    conn: sqlite3.Connection,
    query: str,
    *,
    embed_query=None,  # callable(str)->np.ndarray | None; None or failure → keyword-only (D13)
    standard_id: str | None = None,
    source: str | None = None,
    grade_band: str | None = None,
    content_type: str | None = None,
    limit: int = 5,
    include_content: bool = False,
) -> dict:
    """Hybrid keyword + semantic search across attached DBs. Falls back to
    FTS5-only when no embedder is available (D13), flagging search_mode."""
    match = _fts_match(query)
    if match is None:
        return {"query": query, "results": [], "search_mode": "empty_query"}

    filters: list[str] = []
    params: list = []
    if source:
        filters.append("c.source_id = ?"); params.append(source)
    if grade_band:
        filters.append("c.grade_band = ?"); params.append(grade_band)
    if content_type:
        filters.append("c.content_type = ?"); params.append(content_type)
    if standard_id:
        filters.append(
            "EXISTS (SELECT 1 FROM standard_alignments a "
            "WHERE a.chunk_id = c.id AND a.standard_id = ? AND a.stale = 0)"
        )
        params.append(standard_id)

    qvec = None
    if embed_query is not None:
        try:
            qvec = embed_query(query)
        except Exception:
            qvec = None  # graceful degradation (D13)
    mode = "hybrid" if qvec is not None else "keyword_fallback"

    merged: list[str] = []
    by_id: dict[str, sqlite3.Row] = {}
    for schema in attached_schemas(conn):
        # standard_alignments lives in each schema; qualify the EXISTS subquery
        sfilters = [
            f.replace("standard_alignments", f"{schema}.standard_alignments")
            for f in filters
        ]
        rankings = [_keyword_hits(conn, schema, match, sfilters, params)]
        if qvec is not None:
            rankings.append(_semantic_hits(conn, schema, qvec, sfilters, params))
        ids = _rrf(rankings)
        for cid in ids:
            row = conn.execute(
                f"SELECT * FROM {schema}.chunks WHERE id = ?", (cid,)
            ).fetchone()
            by_id[cid] = row
        merged.extend(ids)

    # de-dup preserving best fused order, then cap
    seen, ordered = set(), []
    for cid in _rrf([merged]) if len(attached_schemas(conn)) > 1 else merged:
        if cid not in seen:
            seen.add(cid); ordered.append(cid)

    results = []
    for cid in ordered[:limit]:
        row = by_id[cid]
        results.append(
            ChunkResult(
                chunk_id=row["id"], source=row["source_id"], title=row["title"],
                content_type=row["content_type"], grade_band=row["grade_band"],
                content=row["content"] if include_content else None,
                source_url=row["source_url"], attribution=row["attribution"],
                item_type=row["item_type"],
                dok_level=row["dok_level"],
                answer_key=row["answer_key"],
                exam_series=row["exam_series"],
                exam_year=row["exam_year"],
                difficulty=row["difficulty"],
                item_generation=row["item_generation"],
            ).model_dump()
        )
    return {"query": query, "search_mode": mode, "results": results}


# Confidence hierarchy (PRD §10, D20): human > publisher_guide > llm_verified >
# embedding, then by score. Applied as an ORDER BY key across attached schemas.
_SOURCE_RANK = (
    "CASE a.alignment_source WHEN 'human' THEN 4 WHEN 'publisher_guide' THEN 3 "
    "WHEN 'llm_verified' THEN 2 ELSE 1 END"
)


def fetch_for_standard(
    conn: sqlite3.Connection,
    standard_id: str,
    *,
    source: str | None = None,
    content_type: str | None = None,
    dok_level: int | None = None,
    limit: int = 3,
    include_content: bool = True,
) -> dict:
    """Return OER chunks aligned to a StandardGraph standard ID, ranked by the
    confidence hierarchy then alignment score, spanning attached databases.

    Always returns a dict with 'standard_id', 'count', and 'results' keys.
    When no content is found, 'count' is 0, 'results' is [], and 'reason' /
    'available_sources' are included to explain the gap.
    """
    rows: list[tuple] = []
    for schema in attached_schemas(conn):
        clauses = ["a.standard_id = ?", "a.stale = 0", "c.stale = 0"]
        params: list = [standard_id]
        if source:
            clauses.append("c.source_id = ?")
            params.append(source)
        if content_type:
            clauses.append("c.content_type = ?")
            params.append(content_type)
        if dok_level is not None:
            clauses.append("c.content_type = 'assessment' AND c.dok_level = ?")
            params.append(dok_level)
        q = f"""
            SELECT c.id, c.source_id, c.title, c.content_type, c.grade_band,
                   c.content, c.source_url, c.attribution,
                   c.item_type, c.dok_level, c.answer_key,
                   c.exam_series, c.exam_year, c.difficulty, c.item_generation,
                   a.alignment_score, a.alignment_source, a.coverage_notes,
                   {_SOURCE_RANK} AS rank
            FROM {schema}.standard_alignments a
            JOIN {schema}.chunks c ON c.id = a.chunk_id
            WHERE {' AND '.join(clauses)}
        """
        rows.extend(conn.execute(q, params).fetchall())

    if not rows:
        sources = [s.id for s in list_sources(conn).sources]
        return {
            "standard_id": standard_id,
            "count": 0,
            "results": [],
            "reason": "No OER content aligned to this standard yet.",
            "available_sources": sources,
        }

    rows.sort(key=lambda r: (r["rank"], r["alignment_score"]), reverse=True)
    out = []
    for r in rows[:limit]:
        result = ChunkResult(
            chunk_id=r["id"],
            source=r["source_id"],
            title=r["title"],
            content_type=r["content_type"],
            grade_band=r["grade_band"],
            alignment_score=round(r["alignment_score"], 4),
            alignment_source=r["alignment_source"],
            coverage_notes=r["coverage_notes"],
            content=r["content"] if include_content else None,
            source_url=r["source_url"],
            attribution=r["attribution"],
            item_type=r["item_type"],
            dok_level=r["dok_level"],
            answer_key=r["answer_key"],
            exam_series=r["exam_series"],
            exam_year=r["exam_year"],
            difficulty=r["difficulty"],
            item_generation=r["item_generation"],
        )
        out.append(result.model_dump(exclude_none=False))
    return {"standard_id": standard_id, "count": len(out), "results": out}


_BAND_RANK = {"none": 0, "light": 1, "moderate": 2, "strong": 3}


def _cluster_standards(sg_conn, standard_id: str) -> list[tuple[str, str]]:
    """Authoritative (id, text) list for a standard or its cluster, from
    StandardGraph. Handles SG's inconsistent cluster-letter ID format: exact
    standard → its whole domain+cluster; otherwise prefix match (tolerating a
    trailing cluster letter like the '.A' in 'CCSS.MATH.6.RP.A')."""
    exact = sg_conn.execute(
        "SELECT domain, cluster FROM standards WHERE id = ? AND system = 'ccss'",
        (standard_id,),
    ).fetchone()
    if exact:
        rows = sg_conn.execute(
            "SELECT id, standard_text FROM standards WHERE system='ccss' "
            "AND domain = ? AND cluster = ? ORDER BY id",
            (exact["domain"], exact["cluster"]),
        ).fetchall()
        return [(r["id"], r["standard_text"]) for r in rows]
    prefix = standard_id
    parts = standard_id.split(".")
    if len(parts[-1]) == 1 and parts[-1].isupper():  # trailing cluster letter
        prefix = ".".join(parts[:-1])
    rows = sg_conn.execute(
        "SELECT id, standard_text FROM standards WHERE system='ccss' "
        "AND id LIKE ? ORDER BY id",
        (prefix + "%",),
    ).fetchall()
    return [(r["id"], r["standard_text"]) for r in rows]


def _best_alignment(conn, standard_id, source):
    """Best (score, source, chunk_id) for a standard across attached DBs."""
    best = None
    for schema in attached_schemas(conn):
        clause = "a.standard_id = ? AND a.stale = 0 AND c.stale = 0"
        params = [standard_id]
        if source:
            clause += " AND c.source_id = ?"
            params.append(source)
        row = conn.execute(
            f"""SELECT a.alignment_score, a.alignment_source, a.chunk_id
                FROM {schema}.standard_alignments a
                JOIN {schema}.chunks c ON c.id = a.chunk_id
                WHERE {clause}
                ORDER BY a.alignment_score DESC LIMIT 1""",
            params,
        ).fetchone()
        if row and (best is None or row["alignment_score"] > best["alignment_score"]):
            best = row
    return best


def check_coverage(
    conn: sqlite3.Connection,
    standard_id: str,
    *,
    sg_db_path=None,
    source: str | None = None,
) -> dict:
    """Report how completely indexed OER content covers a standard or cluster.
    Uses StandardGraph (read-only) to enumerate the cluster's standards so that
    zero-coverage gaps are surfaced; without it, reports only standards that
    have alignments and flags that gap detection is unavailable."""
    import sqlite3 as _sql
    from pathlib import Path

    from oer_shared.coverage import coverage_band

    standards: list[tuple[str, str | None]]
    gap_detection = "full"
    if sg_db_path and Path(sg_db_path).exists():
        sg = _sql.connect(f"file:{sg_db_path}?mode=ro", uri=True)
        sg.row_factory = _sql.Row
        standards = _cluster_standards(sg, standard_id)
        sg.close()
        if not standards:
            return {"standard_id": standard_id, "result": "unknown_standard"}
    else:
        # degraded: enumerate only standards that already have alignments
        gap_detection = "unavailable_without_standardgraph"
        ids = set()
        for schema in attached_schemas(conn):
            for r in conn.execute(
                f"SELECT DISTINCT standard_id FROM {schema}.standard_alignments "
                "WHERE standard_id LIKE ? AND stale = 0",
                (standard_id.rstrip(".") + "%",),
            ).fetchall():
                ids.add(r["standard_id"])
        standards = [(sid, None) for sid in sorted(ids)]

    sub_reports, gaps = [], []
    worst_covered = None
    for sid, text in standards:
        best = _best_alignment(conn, sid, source)
        if best is None:
            band = "none"
            entry = {"id": sid, "coverage": band, "best_chunk": None, "alignment_score": None}
        else:
            band = coverage_band(best["alignment_score"], best["alignment_source"])
            entry = {
                "id": sid, "coverage": band,
                "best_chunk": best["chunk_id"],
                "alignment_score": round(best["alignment_score"], 4),
                "alignment_source": best["alignment_source"],
            }
        if text is not None:
            entry["text"] = text
        sub_reports.append(entry)
        if band == "none":
            gaps.append(sid)
        else:
            r = _BAND_RANK[band]
            worst_covered = r if worst_covered is None else min(worst_covered, r)

    if not sub_reports:
        overall = "none"
    elif all(s["coverage"] == "none" for s in sub_reports):
        overall = "none"
    else:
        overall = {v: k for k, v in _BAND_RANK.items()}[worst_covered]

    return {
        "standard_id": standard_id,
        "standards_checked": len(sub_reports),
        "sub_standards": sub_reports,
        "overall_coverage": overall,
        "gaps": gaps,
        "gap_detection": gap_detection,
        "sources_checked": [s.id for s in list_sources(conn).sources]
        if source is None else [source],
    }


def map_to_assessments(
    conn: sqlite3.Connection,
    standard_id: str,
    *,
    include_items: bool = True,
    items_per_exam: int = 2,
) -> dict:
    """Report how a standard maps to high-stakes exams. Returns:
    - crosswalk: which exam series test this standard and at what skill domain
    - items: available assessment chunks per exam (released or style-generated)
    - gaps: exam series in the crosswalk that have no items in the corpus yet
    Spans all attached databases (core + ncsa + ap)."""
    # Crosswalk lives in main only (reference data, not content). The seed stores
    # CCSS cluster/grade *prefixes* (e.g. "CCSS.MATH.8.EE", "CCSS.MATH.8") so a
    # leaf standard maps to every exam that tests its cluster or grade. Match the
    # standard itself plus each ancestor prefix, trimming trailing dot-components:
    # 8.EE.1 → {8.EE.1, 8.EE, 8, ...}, so it picks up the 8.EE cluster row
    # (SAT/ACT/NAEP) and the grade-8 row (Smarter Balanced Grade 8).
    parts = standard_id.split(".")
    candidates = [".".join(parts[:i]) for i in range(len(parts), 0, -1)]
    placeholders = ",".join("?" * len(candidates))
    xwalk_rows = conn.execute(
        f"SELECT exam_series, skill_domain, notes, source_url "
        f"FROM main.exam_crosswalks WHERE standard_id IN ({placeholders}) "
        f"ORDER BY exam_series",
        candidates,
    ).fetchall()

    crosswalk = [
        {
            "exam_series": r["exam_series"],
            "skill_domain": r["skill_domain"],
            "notes": r["notes"],
            "source_url": r["source_url"],
        }
        for r in xwalk_rows
    ]
    crosswalk_exams = {r["exam_series"] for r in xwalk_rows}

    # Collect assessment items aligned to this standard, grouped by exam_series.
    items_by_exam: dict[str, list[dict]] = {}
    items_available = False
    for schema in attached_schemas(conn):
        if not _has_assessment_columns(conn, schema):
            continue  # DB predates assessment columns — no items to serve here.
        items_available = True
        rows = conn.execute(
            f"""SELECT c.id, c.source_id, c.title, c.content_type, c.grade_band,
                       c.content, c.source_url, c.attribution,
                       c.item_type, c.dok_level, c.answer_key,
                       c.exam_series, c.exam_year, c.difficulty, c.item_generation,
                       a.alignment_score, a.alignment_source, a.coverage_notes,
                       {_SOURCE_RANK} AS rank
                FROM {schema}.standard_alignments a
                JOIN {schema}.chunks c ON c.id = a.chunk_id
                WHERE a.standard_id = ? AND a.stale = 0 AND c.stale = 0
                  AND c.content_type = 'assessment' AND c.exam_series IS NOT NULL
                ORDER BY rank DESC, a.alignment_score DESC""",
            (standard_id,),
        ).fetchall()
        for r in rows:
            series = r["exam_series"]
            bucket = items_by_exam.setdefault(series, [])
            if len(bucket) < items_per_exam:
                chunk = ChunkResult(
                    chunk_id=r["id"], source=r["source_id"], title=r["title"],
                    content_type=r["content_type"], grade_band=r["grade_band"],
                    alignment_score=round(r["alignment_score"], 4),
                    alignment_source=r["alignment_source"],
                    coverage_notes=r["coverage_notes"],
                    content=r["content"] if include_items else None,
                    source_url=r["source_url"], attribution=r["attribution"],
                    item_type=r["item_type"], dok_level=r["dok_level"],
                    answer_key=r["answer_key"] if include_items else None,
                    exam_series=r["exam_series"], exam_year=r["exam_year"],
                    difficulty=r["difficulty"], item_generation=r["item_generation"],
                )
                bucket.append(chunk.model_dump(exclude_none=False))

    # Exams in crosswalk but no items yet = gaps.
    gaps = sorted(crosswalk_exams - set(items_by_exam))

    return {
        "standard_id": standard_id,
        "crosswalk": crosswalk,
        "items_by_exam": items_by_exam,
        "gaps": gaps,
        "crosswalk_coverage": "full" if crosswalk else "unavailable",
        # "ready" once any attached DB carries assessment columns; "no_item_store"
        # on legacy DBs so callers can distinguish "no items yet" from "can't serve".
        "items_status": "ready" if items_available else "no_item_store",
    }


def get_learning_path(
    conn: sqlite3.Connection,
    standard_id: str,
    *,
    sg_db_path=None,
    depth: int = 1,
    content_per_standard: int = 2,
    include_content: bool = False,
) -> dict:
    """Return a prerequisite-aware content path for a standard, grounded in OER.

    BFS-walks StandardGraph's prerequisite graph up to `depth` levels and
    attaches ranked OER content per rung, bottom-up (deepest prereqs first,
    target standard last). Surfaces prerequisite_gaps: standards in the path
    with no content in the corpus.

    Degrades gracefully when StandardGraph is unavailable (returns just the
    target standard's content with sg_available=False).
    """
    import sqlite3 as _sql
    from collections import deque
    from pathlib import Path

    from oer_shared.coverage import coverage_band

    # ── Step 1: resolve prerequisites from StandardGraph ────────────────────
    sg_available = False
    path_standards: dict[str, tuple[str | None, int]] = {}  # id → (text, distance)

    if sg_db_path and Path(sg_db_path).exists():
        sg = _sql.connect(f"file:{sg_db_path}?mode=ro", uri=True)
        sg.row_factory = _sql.Row

        target_row = sg.execute(
            "SELECT id, standard_text FROM standards WHERE id = ? AND system = 'ccss'",
            (standard_id,),
        ).fetchone()
        if target_row is None:
            sg.close()
            return {"standard_id": standard_id, "result": "unknown_standard"}

        sg_available = True
        visited: set[str] = {standard_id}
        queue: deque[tuple[str, int]] = deque([(standard_id, 0)])

        while queue:
            current_id, current_depth = queue.popleft()
            row = sg.execute(
                "SELECT standard_text FROM standards WHERE id = ? AND system = 'ccss'",
                (current_id,),
            ).fetchone()
            text = row["standard_text"] if row else None
            path_standards[current_id] = (text, current_depth)

            if current_depth < depth:
                prereqs = sg.execute(
                    "SELECT target_id FROM standard_relationships "
                    "WHERE source_id = ? AND relationship = 'prerequisite' AND system = 'ccss'",
                    (current_id,),
                ).fetchall()
                for prereq_row in prereqs:
                    pid = prereq_row["target_id"]
                    if pid not in visited:
                        visited.add(pid)
                        queue.append((pid, current_depth + 1))

        sg.close()
    else:
        # Degraded: just the target standard, no prereq walk.
        path_standards = {standard_id: (None, 0)}

    # ── Step 2: sort bottom-up (highest distance first, target last) ─────────
    sorted_path = sorted(
        path_standards.items(),
        key=lambda kv: (-kv[1][1], kv[0]),  # (-distance, id) for stable tie-break
    )

    # ── Step 3: attach OER content and coverage per standard ─────────────────
    path = []
    prerequisite_gaps: list[str] = []

    for sid, (text, distance) in sorted_path:
        # Best alignment for coverage band.
        best = _best_alignment(conn, sid, None)
        band = coverage_band(best["alignment_score"], best["alignment_source"]) if best else "none"

        # Collect ranked content from all schemas.
        all_rows: list = []
        for schema in attached_schemas(conn):
            clauses = ["a.standard_id = ?", "a.stale = 0", "c.stale = 0"]
            params: list = [sid]
            q = f"""
                SELECT c.id, c.source_id, c.title, c.content_type, c.grade_band,
                       c.content, c.source_url, c.attribution,
                       c.item_type, c.dok_level, c.answer_key,
                       c.exam_series, c.exam_year, c.difficulty, c.item_generation,
                       a.alignment_score, a.alignment_source, a.coverage_notes,
                       {_SOURCE_RANK} AS rank
                FROM {schema}.standard_alignments a
                JOIN {schema}.chunks c ON c.id = a.chunk_id
                WHERE {' AND '.join(clauses)}
            """
            all_rows.extend(conn.execute(q, params).fetchall())

        all_rows.sort(key=lambda r: (r["rank"], r["alignment_score"]), reverse=True)
        content = [
            ChunkResult(
                chunk_id=r["id"], source=r["source_id"], title=r["title"],
                content_type=r["content_type"], grade_band=r["grade_band"],
                alignment_score=round(r["alignment_score"], 4),
                alignment_source=r["alignment_source"],
                coverage_notes=r["coverage_notes"],
                content=r["content"] if include_content else None,
                source_url=r["source_url"], attribution=r["attribution"],
                item_type=r["item_type"], dok_level=r["dok_level"],
                answer_key=r["answer_key"],
                exam_series=r["exam_series"], exam_year=r["exam_year"],
                difficulty=r["difficulty"], item_generation=r["item_generation"],
            ).model_dump(exclude_none=False)
            for r in all_rows[:content_per_standard]
        ]

        path.append({
            "standard_id": sid,
            "text": text,
            "distance": distance,
            "is_target": (sid == standard_id),
            "content": content,
            "coverage": band,
        })
        if band == "none":
            prerequisite_gaps.append(sid)

    return {
        "standard_id": standard_id,
        "sg_available": sg_available,
        "depth": depth,
        "path": path,
        "prerequisite_gaps": prerequisite_gaps,
    }


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


_ALL_TOOLS = [
    "fetch_for_standard",
    "search_content",
    "get_chunk",
    "check_coverage",
    "list_sources",
    "map_to_assessments",
    "get_learning_path",
    "get_capabilities",
]


def get_capabilities(conn: sqlite3.Connection) -> dict:
    """Return a live self-describing manifest of this server's corpus and tools.

    Enumerates sources, standard systems, content types, exam series, grade
    bands, alignment sources, and available tools from the attached databases.
    Intended as a discovery call so machine clients can configure themselves
    before issuing queries.
    """
    from oer_shared.coverage import _BANDS

    schemas = attached_schemas(conn)
    inventory = list_sources(conn)

    sources = [
        {
            "id": s.id,
            "full_name": s.full_name,
            "chunks": s.chunks_indexed,
            "grade_bands": s.grade_bands,
            "license": s.license,
        }
        for s in inventory.sources
    ]

    standard_systems: list[str] = []
    exam_series: list[str] = []
    grade_bands: list[str] = []
    for schema in schemas:
        for row in conn.execute(
            f"SELECT DISTINCT standard_system FROM {schema}.standard_alignments WHERE stale=0"
        ).fetchall():
            if row[0] and row[0] not in standard_systems:
                standard_systems.append(row[0])

        for row in conn.execute(
            f"SELECT DISTINCT exam_series FROM {schema}.chunks WHERE exam_series IS NOT NULL AND stale=0"
        ).fetchall():
            if row[0] and row[0] not in exam_series:
                exam_series.append(row[0])

        for row in conn.execute(
            f"SELECT DISTINCT grade_band FROM {schema}.books WHERE grade_band IS NOT NULL"
        ).fetchall():
            if row[0] and row[0] not in grade_bands:
                grade_bands.append(row[0])

    return {
        "databases_attached": [_SCHEMA_LABELS[s] for s in schemas],
        "sources": sources,
        "standard_systems": sorted(standard_systems),
        "content_types": ["exposition", "worked_example", "exercise_set", "summary", "assessment"],
        "exam_series": sorted(exam_series),
        "grade_bands": sorted(grade_bands),
        "alignment_sources": ["human", "publisher_guide", "llm_verified", "embedding"],
        "alignment_confidence_bands": {
            src: {"strong": t[0], "moderate": t[1], "light": t[2]}
            for src, t in _BANDS.items()
        },
        "tools": _ALL_TOOLS,
        "total_chunks": inventory.total_chunks,
        "total_alignments": inventory.total_standards_aligned,
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
