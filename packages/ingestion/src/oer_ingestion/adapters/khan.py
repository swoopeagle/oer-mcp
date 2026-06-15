"""Khan Academy adapter — Kolibri / Learning Equality channel (D16, Spike S2).

Khan's own site is fully bot-walled; acquisition is via Learning Equality's
published Kolibri channel DB + CDN instead of scraping:
  channel DB:  https://studio.learningequality.org/content/databases/{channel_id}.sqlite3
  CDN files:   https://studio.learningequality.org/content/storage/{c0}/{c1}/{checksum}.{ext}
  channel_id:  c9d7f950ab6b5a1199e3d6c10d7f0103  (Khan Academy, English - US curriculum)

Phase 1 scope: video transcripts (VTT, CC BY-NC-SA) → exposition chunks.
Perseus exercises are reference-only pending a licensing decision (see S2).
No CCSS tags in the export → embedding-only alignment.

Implementation lands in M3.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

import httpx

from oer_shared.models import ContentChunk

from ..vtt import vtt_to_text
from .base import RawContent, SourceAdapter, ValidationResult

CHANNEL_ID = "c9d7f950ab6b5a1199e3d6c10d7f0103"  # Khan Academy, English - US curriculum
CHANNEL_DB_URL = f"https://studio.learningequality.org/content/databases/{CHANNEL_ID}.sqlite3"
CDN = "https://studio.learningequality.org/content/storage/{a}/{b}/{checksum}.{ext}"
LICENSE = "CC BY-NC-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"


def _cdn_url(checksum: str, ext: str = "vtt") -> str:
    return CDN.format(a=checksum[0], b=checksum[1], checksum=checksum, ext=ext)


def _grade_band(title: str) -> str | None:
    """Map a Khan 'Math by grade' topic title to an OpenStax-style band."""
    t = title.lower()
    if "kindergarten" in t:
        return "K-5"
    m = re.search(r"(\d+)(?:st|nd|rd|th)\s+grade", t)
    if m:
        g = int(m.group(1))
        return "K-5" if g <= 5 else ("6-8" if g <= 8 else "9-12")
    if any(k in t for k in ("high school", "algebra", "geometry", "trigonometry",
                            "precalculus", "calculus", "statistics")):
        return "9-12"
    return None


class KhanAcademyAdapter(SourceAdapter):
    source_id = "khan-academy"

    def __init__(self, channel_db: str, *, cdn_timeout: float = 30.0,
                 max_videos: int | None = None):
        self.channel_db = channel_db
        self.cdn_timeout = cdn_timeout
        self.max_videos = max_videos
        self._meta: dict[str, dict] = {}  # node_id → {title, grade_band, source_url}

    # ── grade map: descend each 'Math by grade' grade topic, tag descendants ──
    def _grade_for_nodes(self, ch: sqlite3.Connection) -> dict[str, str]:
        rows = ch.execute(
            "SELECT id, parent_id, title, kind FROM content_contentnode"
        ).fetchall()
        children: dict[str, list[str]] = {}
        title = {}
        for r in rows:
            children.setdefault(r["parent_id"], []).append(r["id"])
            title[r["id"]] = r["title"]
        mbg = next((r["id"] for r in rows
                    if r["title"] == "Math by grade" and r["kind"] == "topic"), None)
        grade_of: dict[str, str] = {}
        if mbg is None:
            return grade_of
        for grade_topic in children.get(mbg, []):
            band = _grade_band(title.get(grade_topic, ""))
            if not band:
                continue
            stack = [grade_topic]  # descend, tagging all descendants with this band
            while stack:
                nid = stack.pop()
                grade_of.setdefault(nid, band)
                stack.extend(children.get(nid, []))
        return grade_of

    # ── Stage 1: fetch ────────────────────────────────────────────────────────
    def fetch(self) -> list[RawContent]:
        ch = sqlite3.connect(f"file:{self.channel_db}?mode=ro", uri=True)
        ch.row_factory = sqlite3.Row
        grade_of = self._grade_for_nodes(ch)
        rows = ch.execute(
            """
            WITH RECURSIVE tree(id) AS (
              SELECT id FROM content_contentnode WHERE title='Math' AND kind='topic'
              UNION SELECT cn.id FROM content_contentnode cn JOIN tree ON cn.parent_id=tree.id
            )
            SELECT cn.id, cn.content_id, cn.title, lf.id AS checksum
            FROM content_contentnode cn JOIN tree ON cn.id = tree.id
            JOIN content_file f ON f.contentnode_id = cn.id
            JOIN content_localfile lf ON lf.id = f.local_file_id
            WHERE cn.kind='video' AND f.preset='video_subtitle'
              AND lf.extension='vtt' AND f.lang_id='en'
            GROUP BY cn.id
            """
        ).fetchall()
        ch.close()

        # The same video appears as multiple node placements (grade branch +
        # topic courses). Dedupe by content_id, preferring a placement that
        # carries a grade so K-5/6-8/9-12 tagging survives.
        best: dict[str, sqlite3.Row] = {}
        for r in rows:
            cid = r["content_id"]
            cur = best.get(cid)
            if cur is None or (r["id"] in grade_of and cur["id"] not in grade_of):
                best[cid] = r
        rows = list(best.values())
        if self.max_videos:
            rows = rows[: self.max_videos]

        now = datetime.now(timezone.utc).isoformat()
        raw: list[RawContent] = []
        with httpx.Client(timeout=self.cdn_timeout) as client:
            for r in rows:
                url = _cdn_url(r["checksum"])
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                except httpx.HTTPError:
                    continue  # skip unfetchable transcript, keep going
                self._meta[r["id"]] = {
                    "title": r["title"],
                    "grade_band": grade_of.get(r["id"]),
                    "source_url": url,
                }
                raw.append(RawContent(source_id=self.source_id, key=r["id"],
                                      url=url, fetched_at=now, payload=resp.text))
        return raw

    def catalog(self) -> dict:
        return {
            "source": {
                "id": self.source_id, "full_name": "Khan Academy",
                "license": LICENSE, "license_url": LICENSE_URL,
                "base_url": "https://www.khanacademy.org",
            },
            "books": [{
                "id": "khan-academy-math", "source_id": self.source_id,
                "title": "Khan Academy Mathematics", "subject": "mathematics",
                "grade_band": None, "license": LICENSE,
                "url": "https://www.khanacademy.org/math",
            }],
        }

    # ── Stage 2: parse → one exposition chunk per video transcript (D16) ───────
    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        chunks: list[ContentChunk] = []
        for item in raw:
            meta = self._meta.get(item.key, {})
            text = vtt_to_text(item.payload)
            if not text or len(text.split()) < 20:  # skip near-empty transcripts
                continue
            title = meta.get("title") or item.key
            chunks.append(ContentChunk(
                id=f"khan-{item.key}",
                book_id="khan-academy-math",
                source_id=self.source_id,
                title=title,
                content=text,
                content_type="exposition",
                chapter=None, section=None,
                grade_band=meta.get("grade_band"),
                word_count=len(text.split()),
                source_url=meta.get("source_url") or item.url,
                attribution=f"Khan Academy, {title}, {LICENSE} (video transcript)",
            ))
        return chunks

    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        errors = [f"{c.id}: empty content" for c in chunks if not c.content.strip()]
        errors += [f"{c.id}: empty attribution" for c in chunks if not c.attribution]
        if not chunks:
            errors.append("no chunks produced")
        graded = sum(1 for c in chunks if c.grade_band)
        return ValidationResult(
            ok=not errors, errors=errors,
            warnings=[] if graded else ["no chunks carry a grade_band"],
            stats={"total": len(chunks), "graded": graded},
        )
