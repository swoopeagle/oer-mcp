"""One-shot: move CC-BY-NC-SA OpenStax books from core → ncsa so the default
core DB is truly CC-BY-only (honors D11). Idempotent-ish: only moves books
still present in core whose license contains 'NC'. Chunk/book IDs are unique
text (slug-prefixed) so there is no collision with ncsa's Khan rows; the
autoincrement standard_alignments.id is dropped on copy so ncsa assigns fresh
ids. FK cascade cleans core dependents on book delete; FTS triggers keep both
indexes in sync.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CORE = ROOT / "data" / "oer_core.db"
NCSA = ROOT / "data" / "oer_ncsa.db"

# alignment columns minus the autoincrement id
ALIGN_COLS = ("chunk_id, standard_id, standard_system, alignment_score, "
              "alignment_source, coverage_notes, verified_by_human, "
              "flagged_for_review, stale, created_at")


def counts(con, schema="main"):
    q = lambda s: con.execute(s).fetchone()[0]
    return {
        "books": q(f"SELECT COUNT(*) FROM {schema}.books"),
        "chunks": q(f"SELECT COUNT(*) FROM {schema}.chunks"),
        "embeddings": q(f"SELECT COUNT(*) FROM {schema}.chunk_embeddings"),
        "alignments": q(f"SELECT COUNT(*) FROM {schema}.standard_alignments"),
        "fts": q(f"SELECT COUNT(*) FROM {schema}.chunks_fts"),
    }


def main() -> int:
    con = sqlite3.connect(CORE)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute(f"ATTACH DATABASE '{NCSA}' AS ncsa")

    # books to move: openstax + license has NC
    movers = [r[0] for r in con.execute(
        "SELECT id FROM main.books WHERE source_id='openstax' AND license LIKE '%NC%'"
    ).fetchall()]
    if not movers:
        print("nothing to move (already re-split?)")
        return 0
    print("moving books:", movers)
    ids = ",".join("?" * len(movers))

    n_chunks = con.execute(
        f"SELECT COUNT(*) FROM main.chunks WHERE book_id IN ({ids})", movers).fetchone()[0]
    n_align = con.execute(
        f"SELECT COUNT(*) FROM main.standard_alignments WHERE chunk_id IN "
        f"(SELECT id FROM main.chunks WHERE book_id IN ({ids}))", movers).fetchone()[0]
    print(f"  → {n_chunks} chunks, {n_align} alignments to move")

    before_core = counts(con, "main")
    before_ncsa = counts(con, "ncsa")

    try:
        con.execute("BEGIN")
        # source row (openstax) into ncsa if missing
        con.execute("INSERT OR IGNORE INTO ncsa.sources "
                    "SELECT * FROM main.sources WHERE id='openstax'")
        # books
        con.execute(f"INSERT INTO ncsa.books "
                    f"SELECT * FROM main.books WHERE id IN ({ids})", movers)
        # chunks (ordered by rowid to preserve in-book adjacency); FTS trigger fires
        con.execute(f"INSERT INTO ncsa.chunks "
                    f"SELECT * FROM main.chunks WHERE book_id IN ({ids}) ORDER BY rowid",
                    movers)
        # embeddings
        con.execute(f"INSERT INTO ncsa.chunk_embeddings SELECT * FROM main.chunk_embeddings "
                    f"WHERE chunk_id IN (SELECT id FROM main.chunks WHERE book_id IN ({ids}))",
                    movers)
        # alignments (drop autoincrement id → ncsa assigns fresh)
        con.execute(
            f"INSERT INTO ncsa.standard_alignments ({ALIGN_COLS}) "
            f"SELECT {ALIGN_COLS} FROM main.standard_alignments "
            f"WHERE chunk_id IN (SELECT id FROM main.chunks WHERE book_id IN ({ids}))",
            movers)
        # delete from core — cascade removes chunks/embeddings/alignments + FTS delete trigger
        con.execute(f"DELETE FROM main.books WHERE id IN ({ids})", movers)
        con.execute("COMMIT")
    except Exception as e:
        con.execute("ROLLBACK")
        print("ROLLED BACK:", e)
        return 1

    after_core = counts(con, "main")
    after_ncsa = counts(con, "ncsa")

    print("\n            core(before→after)        ncsa(before→after)")
    for k in before_core:
        print(f"  {k:11} {before_core[k]:>6} → {after_core[k]:<6}     "
              f"{before_ncsa[k]:>6} → {after_ncsa[k]:<6}")

    # invariants
    ok = True
    if after_core["chunks"] != before_core["chunks"] - n_chunks:
        ok = False; print("  ✗ core chunk delta wrong")
    if after_ncsa["chunks"] != before_ncsa["chunks"] + n_chunks:
        ok = False; print("  ✗ ncsa chunk delta wrong")
    # FTS must equal chunks in both
    for label, c in (("core", after_core), ("ncsa", after_ncsa)):
        if c["fts"] != c["chunks"]:
            ok = False; print(f"  ✗ {label} FTS desync: fts={c['fts']} chunks={c['chunks']}")
    # integrity + orphan checks
    for schema in ("main", "ncsa"):
        ic = con.execute(f"PRAGMA {schema}.integrity_check").fetchone()[0]
        if ic != "ok":
            ok = False; print(f"  ✗ {schema} integrity_check: {ic}")
        orphans = con.execute(
            f"SELECT COUNT(*) FROM {schema}.chunks c "
            f"LEFT JOIN {schema}.books b ON b.id=c.book_id WHERE b.id IS NULL").fetchone()[0]
        if orphans:
            ok = False; print(f"  ✗ {schema} has {orphans} orphan chunks")

    # core should now be CC-BY only
    core_lic = con.execute("SELECT DISTINCT license FROM main.books").fetchall()
    print("\n  core licenses now:", [r[0] for r in core_lic])

    con.close()
    print("\n", "✓ ALL CHECKS PASSED" if ok else "✗ CHECKS FAILED — investigate")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
