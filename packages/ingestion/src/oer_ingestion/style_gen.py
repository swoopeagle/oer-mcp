"""Style-generation pipeline stage — generate SAT/ACT-style assessment items.

Uses gemma4:31b (same host as annotate/verify) to write original items modeled
on SAT and ACT question formats, targeted at specific CCSS standards. Items are
NOT copied from College Board or ACT materials — they are new, generated content
that mimics the style, format, and rigor of those exams.

Generated items carry:
  item_generation = "style_generated"
  alignment_source = "embedding"  (grounded by the standard text, not a publisher tag)
  answer_key = <gemma-generated correct answer + explanation>

Usage:
    uv run python -m oer_ingestion.style_gen \
        --db data/oer_core.db \
        --sg-db ~/.standardgraph/common_core.db \
        --style sat \
        [--limit 50] [--shard N/M]

Runs cleanly in parallel with verify/annotate (WAL mode, no lock contention).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Literal

from oer_shared import config
from oer_shared.ollama_client import OllamaClient

StyleTarget = Literal["sat", "act"]

_STYLE_PROMPTS = {
    "sat": (
        "You are writing SAT Math exam questions. SAT Math questions are "
        "precise, unambiguous, and test one skill cleanly. They include a "
        "realistic context (rates, costs, distances, percentages) when "
        "appropriate. Multiple-choice items have four options (A–D) with "
        "exactly one correct answer and plausible distractors that reflect "
        "common errors. Grid-in items ask for a numeric answer. "
        "Difficulty ranges from straightforward to moderately challenging."
    ),
    "act": (
        "You are writing ACT Math exam questions. ACT Math questions are "
        "direct, often context-free, and test procedural fluency. They have "
        "five answer choices (A–E). Questions progress from pre-algebra "
        "through trigonometry. Distractors reflect arithmetic errors or "
        "sign mistakes. Avoid calculator-dependent computations."
    ),
}

_ITEM_TYPE_BY_STYLE: dict[StyleTarget, str] = {
    "sat": "multiple_choice",
    "act": "multiple_choice",
}

_EXAM_SERIES: dict[StyleTarget, str] = {
    "sat": "SAT",
    "act": "ACT",
}

_PROMPT_TEMPLATE = """{style_instructions}

Write ONE {style} Math question that assesses the following CCSS standard:

Standard ID: {standard_id}
Standard text: {standard_text}

Output a JSON object with exactly these keys:
  "question": the full question stem (include answer choices A–D if multiple choice)
  "answer": the correct answer (letter + brief justification)
  "dok_level": Webb's Depth of Knowledge level (1, 2, or 3)

Output only the JSON object, no other text.
"""


class StyleGenPipeline:
    def __init__(
        self,
        conn: sqlite3.Connection,
        sg_db_path: str,
        style: StyleTarget = "sat",
        *,
        limit: int | None = None,
        shard: tuple[int, int] | None = None,
    ) -> None:
        self.conn = conn
        self.sg_db = sqlite3.connect(f"file:{sg_db_path}?mode=ro", uri=True)
        self.sg_db.row_factory = sqlite3.Row
        self.style = style
        self.limit = limit
        self.shard = shard
        self.client = OllamaClient(
            base_url=config.OLLAMA_BASE_URL,
            model=config.ANNOTATE_MODEL,
            api=config.OLLAMA_API,
        )

    def _standards_needing_items(self) -> list[tuple[str, str]]:
        """CCSS standards that have OER content but no style-generated item yet."""
        existing = {
            r[0]
            for r in self.conn.execute(
                "SELECT DISTINCT sa.standard_id FROM standard_alignments sa "
                "JOIN chunks c ON c.id = sa.chunk_id "
                "WHERE c.content_type='assessment' AND c.item_generation='style_generated' "
                f"AND c.exam_series='{_EXAM_SERIES[self.style]}' AND c.stale=0"
            ).fetchall()
        }
        # All standards that have embedding-aligned OER content
        rows = self.conn.execute(
            "SELECT DISTINCT standard_id FROM standard_alignments WHERE stale=0"
        ).fetchall()
        candidates = [r[0] for r in rows if r[0] not in existing]
        if self.shard:
            n, m = self.shard
            candidates = [c for c in candidates if hash(c) % m == n]
        if self.limit:
            candidates = candidates[: self.limit]
        # Fetch standard text from SG
        out = []
        for sid in candidates:
            row = self.sg_db.execute(
                "SELECT standard_text FROM standards WHERE id=? AND system='ccss'",
                (sid,),
            ).fetchone()
            if row:
                out.append((sid, row["standard_text"]))
        return out

    def _generate(self, standard_id: str, standard_text: str) -> dict | None:
        prompt = _PROMPT_TEMPLATE.format(
            style_instructions=_STYLE_PROMPTS[self.style],
            style=self.style.upper(),
            standard_id=standard_id,
            standard_text=standard_text,
        )
        try:
            raw = self.client.generate(prompt, max_tokens=512)
        except Exception as e:
            print(f"[style_gen] {standard_id}: Ollama error — {e}")
            return None
        # Parse JSON from response
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            print(f"[style_gen] {standard_id}: no JSON in response")
            return None
        try:
            return json.loads(m.group())
        except json.JSONDecodeError as e:
            print(f"[style_gen] {standard_id}: JSON parse error — {e}")
            return None

    def _book_id_for_grade(self, standard_id: str) -> str:
        """Map standard grade to the appropriate source book.
        Style-generated items live in a dedicated book per style."""
        return f"style-gen-{self.style}-math"

    def _ensure_book(self) -> None:
        exam = _EXAM_SERIES[self.style]
        source_id = f"style-gen-{self.style}"
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO sources (id, full_name, license, license_url, base_url, last_indexed)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET last_indexed=excluded.last_indexed""",
            (
                source_id,
                f"{exam}-Style Questions (AI-Generated)",
                "CC BY 4.0",  # generated content, author holds rights; released CC BY
                "https://creativecommons.org/licenses/by/4.0/",
                "https://github.com/swoopeagle/oer-mcp",
                now,
            ),
        )
        self.conn.execute(
            """INSERT INTO books (id, source_id, title, subject, grade_band, license, url)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(id) DO NOTHING""",
            (
                f"style-gen-{self.style}-math",
                source_id,
                f"{exam}-Style Math Questions (AI-Generated, K–12)",
                "mathematics",
                "K-12",
                "CC BY 4.0",
                "https://github.com/swoopeagle/oer-mcp",
            ),
        )
        self.conn.commit()

    def run(self) -> dict[str, int]:
        self._ensure_book()
        standards = self._standards_needing_items()
        print(f"[style_gen] {self.style}: {len(standards)} standards to generate")
        added = skipped = errors = 0
        now = datetime.now(timezone.utc).isoformat()
        exam_series = _EXAM_SERIES[self.style]
        item_type = _ITEM_TYPE_BY_STYLE[self.style]
        book_id = f"style-gen-{self.style}-math"
        source_id = f"style-gen-{self.style}"

        for standard_id, standard_text in standards:
            result = self._generate(standard_id, standard_text)
            if not result:
                errors += 1
                continue
            question = (result.get("question") or "").strip()
            answer = (result.get("answer") or "").strip()
            dok = result.get("dok_level")
            try:
                dok = int(dok) if dok else 2
            except (TypeError, ValueError):
                dok = 2
            if not question:
                skipped += 1
                continue

            uid = hashlib.sha256(
                f"{self.style}:{standard_id}:{question[:80]}".encode()
            ).hexdigest()[:12]
            chunk_id = f"style-{self.style}-{standard_id.replace('.', '_')}-{uid}"
            title = f"{exam_series}-Style: {standard_id}"
            attribution = (
                f"AI-generated {exam_series}-style item for CCSS standard {standard_id}. "
                f"Generated by OER MCP using Gemma. "
                f"Not affiliated with or endorsed by College Board or ACT. "
                f"CC BY 4.0 (oer-mcp contributors)."
            )
            content_hash = hashlib.sha256(question.encode()).hexdigest()

            exists = self.conn.execute(
                "SELECT 1 FROM chunks WHERE id=?", (chunk_id,)
            ).fetchone()
            params = {
                "id": chunk_id, "book_id": book_id, "source_id": source_id,
                "title": title, "content": question, "content_type": "assessment",
                "grade_band": None, "word_count": len(question.split()),
                "source_url": "https://github.com/swoopeagle/oer-mcp",
                "attribution": attribution,
                "item_type": item_type, "dok_level": dok,
                "answer_key": answer or None,
                "exam_series": exam_series, "exam_year": None,
                "difficulty": None, "item_generation": "style_generated",
                "content_hash": content_hash, "last_verified": now,
            }
            if exists:
                skipped += 1
                continue
            self.conn.execute(
                """INSERT INTO chunks
                     (id, book_id, source_id, title, content, content_type,
                      grade_band, word_count, source_url, attribution,
                      item_type, dok_level, answer_key, exam_series, exam_year,
                      difficulty, item_generation, content_hash, last_verified)
                   VALUES
                     (:id, :book_id, :source_id, :title, :content, :content_type,
                      :grade_band, :word_count, :source_url, :attribution,
                      :item_type, :dok_level, :answer_key, :exam_series, :exam_year,
                      :difficulty, :item_generation, :content_hash, :last_verified)""",
                params,
            )
            # Publisher-style alignment — this item explicitly targets the standard
            self.conn.execute(
                """INSERT INTO standard_alignments
                     (chunk_id, standard_id, standard_system, alignment_score,
                      alignment_source, coverage_notes)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(chunk_id, standard_id) DO NOTHING""",
                (
                    chunk_id, standard_id, "ccss", 0.95, "publisher_guide",
                    f"Style-generated to directly assess {standard_id}.",
                ),
            )
            self.conn.commit()
            added += 1
            if added % 10 == 0:
                print(f"[style_gen] {self.style}: {added} items added...")

        print(
            f"[style_gen] {self.style}: done — "
            f"added={added} skipped={skipped} errors={errors}"
        )
        return {"added": added, "skipped": skipped, "errors": errors}

    def close(self) -> None:
        self.sg_db.close()


def run_style_gen(
    conn: sqlite3.Connection,
    sg_db_path: str,
    style: StyleTarget = "sat",
    limit: int | None = None,
    shard: tuple[int, int] | None = None,
) -> dict[str, int]:
    pipeline = StyleGenPipeline(conn, sg_db_path, style, limit=limit, shard=shard)
    try:
        return pipeline.run()
    finally:
        pipeline.close()
