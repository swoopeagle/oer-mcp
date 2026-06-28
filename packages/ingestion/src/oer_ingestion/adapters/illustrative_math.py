"""Illustrative Mathematics adapter — IM K-12 Math, First Edition (CC BY 4.0).

The First Edition (© 2019–2021) is the permissively-licensed one: CC BY 4.0,
so its content lands in the *core* DB and grows the permissive default (unlike
OpenStax math 2e and Khan, which are NC-SA → ncsa). The later v.360 edition is
CC BY-NC and is deliberately NOT ingested.

Source is server-rendered HTML at im.kendallhunt.com (curriculum.illustrative
mathematics.org 301-redirects there). Structure:

  course index : /MS/teachers/{course}/index.html      (course 1,2,3 = Gr 6,7,8)
  unit index   : /MS/teachers/{course}/{unit}/index.html
  lesson       : /MS/teachers/{course}/{unit}/{lesson}/index.html
  practice     : /MS/teachers/{course}/{unit}/{lesson}/practice.html

Each lesson page carries CCSS alignment in three labelled blocks:
  "Addressing"        — the standards the lesson directly teaches  → publisher_guide
  "Building On"       — prerequisite standards                     → context (skipped)
  "Building Towards"  — downstream standards                       → context (skipped)

Only "Addressing" becomes a publisher_guide alignment (confidence tier 3, above
llm_verified) — the first source in the corpus to carry real publisher CCSS tags.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
from lxml import html as lxml_html

from oer_shared.models import ContentChunk, StandardAlignment

from .base import RawContent, SourceAdapter, ValidationResult

BASE = "https://im.kendallhunt.com"
LICENSE = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"

# MS courses → grade. (K5 and HS use different path roots; MS first per the spike.)
MS_COURSE_GRADE = {"1": "6", "2": "7", "3": "8"}

_CCSS_RE = re.compile(r"^[K0-9]+\.[A-Z]{1,3}(\.[A-Z])?(\.[0-9]+)?(\.[a-z])?$")


def _to_ccss_id(short: str) -> str | None:
    """IM short form → StandardGraph id. SG omits the cluster letter and does not
    carry lowercase sub-parts, so both are dropped:
        '6.G.A.1'    → 'CCSS.MATH.6.G.1'
        '7.EE.B.3'   → 'CCSS.MATH.7.EE.3'
        '8.EE.C.7.a' → 'CCSS.MATH.8.EE.7'   (cluster + sub-part dropped)
        '3.G.A'      → None   (cluster header; SG has no leaf for it)
    """
    short = short.strip()
    if not _CCSS_RE.match(short):
        return None
    parts = short.split(".")
    # drop cluster letter (lone single uppercase segment after the domain)
    if len(parts) >= 4 and len(parts[2]) == 1 and parts[2].isalpha():
        parts = [parts[0], parts[1], *parts[3:]]
    elif len(parts) == 3 and parts[2].isalpha():
        return None  # cluster-level header (e.g. '3.G.A')
    # drop trailing lowercase sub-part (SG has no sub-part leaves)
    if parts and len(parts[-1]) == 1 and parts[-1].islower():
        parts = parts[:-1]
    if len(parts) < 3:
        return None  # nothing more specific than grade.domain
    return "CCSS.MATH." + ".".join(parts)


class IllustrativeMathAdapter(SourceAdapter):
    source_id = "illustrative-math"

    def __init__(self, courses: list[str] | None = None, *,
                 timeout: float = 30.0, max_lessons: int | None = None):
        # default: all three MS courses (grades 6-8)
        self.courses = courses or list(MS_COURSE_GRADE)
        self.timeout = timeout
        self.max_lessons = max_lessons
        self._meta: dict[str, dict] = {}  # key → {title, grade, course, unit, lesson, url}

    # ── crawl helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def _child_indices(payload: str, prefix: str) -> list[str]:
        """Return sorted numeric child segment ids linked under `prefix`."""
        doc = lxml_html.fromstring(payload)
        seen: set[str] = set()
        pat = re.compile(rf"^{re.escape(prefix)}(\d+)/")
        for a in doc.xpath("//a/@href"):
            m = pat.match(a)
            if m:
                seen.add(m.group(1))
        return sorted(seen, key=int)

    def _get(self, client: httpx.Client, path: str) -> str | None:
        try:
            r = client.get(BASE + path, follow_redirects=True)
            if r.status_code != 200 or "doesn't exist" in r.text[:1000]:
                return None
            return r.text
        except httpx.HTTPError:
            return None

    # ── Stage 1: fetch (crawl course → unit → lesson) ─────────────────────────
    def fetch(self) -> list[RawContent]:
        now = datetime.now(timezone.utc).isoformat()
        raw: list[RawContent] = []
        with httpx.Client(timeout=self.timeout, headers={"User-Agent": "oer-mcp/0.1"}) as client:
            for course in self.courses:
                grade = MS_COURSE_GRADE.get(course, "")
                cidx = self._get(client, f"/MS/teachers/{course}/index.html")
                if not cidx:
                    continue
                units = self._child_indices(cidx, f"/MS/teachers/{course}/")
                for unit in units:
                    uidx = self._get(client, f"/MS/teachers/{course}/{unit}/index.html")
                    if not uidx:
                        continue
                    lessons = self._child_indices(uidx, f"/MS/teachers/{course}/{unit}/")
                    for lesson in lessons:
                        path = f"/MS/teachers/{course}/{unit}/{lesson}/index.html"
                        payload = self._get(client, path)
                        if not payload:
                            continue
                        key = f"ms-{course}-{unit}-{lesson}"
                        self._meta[key] = {
                            "grade": grade, "course": course,
                            "unit": unit, "lesson": lesson,
                            "url": BASE + path,
                        }
                        raw.append(RawContent(source_id=self.source_id, key=key,
                                              url=BASE + path, fetched_at=now,
                                              payload=payload))
                        if self.max_lessons and len(raw) >= self.max_lessons:
                            return raw
        return raw

    def catalog(self) -> dict:
        return {
            "source": {
                "id": self.source_id,
                "full_name": "Illustrative Mathematics",
                "license": LICENSE, "license_url": LICENSE_URL,
                "base_url": BASE,
            },
            "books": [{
                "id": "im-ms-math", "source_id": self.source_id,
                "title": "Illustrative Mathematics 6–8 Math (First Edition)",
                "subject": "mathematics", "grade_band": "6-8",
                "license": LICENSE, "url": BASE + "/MS/index.html",
            }],
        }

    # ── parse helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def _standards(doc) -> dict[str, list[str]]:
        """{label: [ccss_id,...]} for each im-c-hero__underline block."""
        out: dict[str, list[str]] = {}
        for hdr in doc.xpath('//p[contains(@class,"im-c-hero__underline")]'):
            label = (hdr.text_content() or "").strip()
            ids: list[str] = []
            ul = hdr.getnext()
            while ul is not None and ul.tag != "ul":
                ul = ul.getnext()
            if ul is not None:
                for a in ul.xpath('.//a'):
                    cid = _to_ccss_id(a.text_content())
                    if cid:
                        ids.append(cid)
            if ids:
                out[label] = ids
        return out

    @staticmethod
    def _lesson_text(doc) -> str:
        """Concatenate readable text from im-c-content blocks (warm-up, activities,
        synthesis). Nav/menu chrome is excluded by class scoping."""
        parts: list[str] = []
        for blk in doc.xpath('//*[contains(@class,"im-c-content")]'):
            txt = re.sub(r"\s+", " ", blk.text_content()).strip()
            if len(txt) >= 40:
                parts.append(txt)
        # de-dup consecutive identical blocks (nested content divs)
        seen: set[str] = set()
        uniq = [p for p in parts if not (p in seen or seen.add(p))]
        return "\n\n".join(uniq)

    @staticmethod
    def _title(doc, meta: dict) -> str:
        """Structured, predictable title. IM teacher pages expose only a generic
        'Lesson N' h1, so encode grade/unit/lesson and append the first activity
        heading (e.g. '5.1: A Parallelogram…') when present for searchability."""
        base = f"IM Grade {meta['grade']}, Unit {meta['unit']}, Lesson {meta['lesson']}"
        for h in doc.xpath('//*[contains(@class,"hero__heading")]'):
            t = re.sub(r"\s+", " ", h.text_content()).strip()
            t = re.sub(r"\s*\(\d+\s*minutes?\)\s*$", "", t)  # drop "(10 minutes)"
            if t and len(t) < 100:
                return f"{base}: {t}"
        return base

    # ── Stage 2: parse → one exposition chunk per lesson + publisher tags ──────
    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        chunks: list[ContentChunk] = []
        for item in raw:
            meta = self._meta.get(item.key, {})
            doc = lxml_html.fromstring(item.payload)
            text = self._lesson_text(doc)
            if not text or len(text.split()) < 30:
                continue
            title = self._title(doc, meta)
            stds = self._standards(doc)
            aligns = [
                StandardAlignment(
                    standard_id=sid, standard_system="ccss",
                    alignment_score=0.95, alignment_source="publisher_guide",
                    coverage_notes="IM lesson directly addresses this standard.",
                )
                for sid in stds.get("Addressing", [])
            ]
            attribution = (
                f"Illustrative Mathematics 6–8 Math, {title}, {LICENSE} "
                f"(© Illustrative Mathematics, im.kendallhunt.com)"
            )
            chunks.append(ContentChunk(
                id=f"im-{item.key}-expo",
                book_id="im-ms-math",
                source_id=self.source_id,
                title=title,
                content=text,
                content_type="exposition",
                chapter=f"Unit {meta.get('unit')}",
                section=f"Lesson {meta.get('lesson')}",
                grade_band="6-8",
                word_count=len(text.split()),
                source_url=item.url,
                attribution=attribution,
                standard_alignments=aligns,
            ))
        return chunks

    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        errors = [f"{c.id}: empty content" for c in chunks if not c.content.strip()]
        errors += [f"{c.id}: empty attribution" for c in chunks if not c.attribution]
        if not chunks:
            errors.append("no chunks produced")
        with_std = sum(1 for c in chunks if c.standard_alignments)
        n_pub = sum(len(c.standard_alignments) for c in chunks)
        return ValidationResult(
            ok=not errors, errors=errors,
            warnings=[] if with_std else ["no chunks carry publisher standards"],
            stats={"total": len(chunks), "with_publisher_std": with_std,
                   "publisher_alignments": n_pub},
        )
