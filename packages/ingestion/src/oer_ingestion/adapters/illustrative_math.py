"""Illustrative Mathematics adapter — IM K-12 Math, First Edition (CC BY 4.0).

The First Edition (© 2019–2021) is the permissively-licensed one: CC BY 4.0,
so its content lands in the *core* DB and grows the permissive default (unlike
OpenStax math 2e and Khan, which are NC-SA → ncsa). The later v.360 edition is
CC BY-NC and is deliberately NOT ingested.

Source is server-rendered HTML at im.kendallhunt.com (curriculum.illustrative
mathematics.org 301-redirects there). Three path families:

  K-5:  /k5/teachers/{grade-name}/unit-{n}/lesson-{n}/preparation.html
  MS:   /MS/teachers/{course}/index.html      (course 1,2,3 = Gr 6,7,8)
  HS:   /HS/teachers/{course}/{unit}/{lesson}/index.html  (course 1-4)

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

# MS courses → grade. (K5 and HS use different path roots.)
MS_COURSE_GRADE = {"1": "6", "2": "7", "3": "8"}

# HS courses → descriptive name (for catalog/title)
HS_COURSE_NAME = {"1": "Algebra 1", "2": "Geometry", "3": "Algebra 2",
                  "4": "Statistics & Probability"}

# K-5 grade slugs as they appear in URLs
K5_GRADES = ["kindergarten", "grade-1", "grade-2", "grade-3", "grade-4", "grade-5"]
K5_GRADE_BAND = {"kindergarten": "K", "grade-1": "1", "grade-2": "2",
                 "grade-3": "3", "grade-4": "4", "grade-5": "5"}

_CCSS_RE = re.compile(r"^[K0-9]+\.[A-Z]{1,3}(\.[A-Z])?(\.[0-9]+)?(\.[a-z])?$")
_HS_RE = re.compile(r"^HS[A-Z]-[A-Z]{1,4}\.[A-Z]\.\d+[a-z]?$")


def _to_ccss_id(short: str) -> str | None:
    """IM short form → StandardGraph id. SG behaviour is grade-dependent:
      K-5: keeps cluster letter   '3.MD.B.3'   → 'CCSS.MATH.3.MD.B.3'
      6-8: drops cluster letter   '6.G.A.1'    → 'CCSS.MATH.6.G.1'
      HS:  keeps cluster letter   'HSA-CED.A.2' → 'CCSS.MATH.HSA.CED.A.2'
    """
    short = short.strip()

    # HS format: 'HSA-CED.A.2' or 'HSS-ID.A.1'
    if _HS_RE.match(short):
        # drop trailing lowercase sub-part if present
        if short[-1].islower() and short[-2] == '.':
            short = short[:-2]
        return "CCSS.MATH." + short.replace("-", ".", 1)

    if not _CCSS_RE.match(short):
        return None
    parts = short.split(".")

    # determine grade to decide cluster-letter handling
    grade_str = parts[0]
    try:
        grade_num = int(grade_str) if grade_str != "K" else 0
    except ValueError:
        return None

    if grade_num <= 5:
        # K-5: SG keeps cluster letter — only drop trailing lowercase sub-part
        if parts and len(parts[-1]) == 1 and parts[-1].islower():
            parts = parts[:-1]
        if len(parts) < 3:
            return None
        # cluster-level (e.g. '3.MD.B') — allowed; fetch_for_standard does prefix match
        return "CCSS.MATH." + ".".join(parts)
    else:
        # 6-8: SG drops cluster letter
        if len(parts) >= 4 and len(parts[2]) == 1 and parts[2].isalpha():
            parts = [parts[0], parts[1], *parts[3:]]
        elif len(parts) == 3 and parts[2].isalpha():
            return None
        if parts and len(parts[-1]) == 1 and parts[-1].islower():
            parts = parts[:-1]
        if len(parts) < 3:
            return None
        return "CCSS.MATH." + ".".join(parts)


class IllustrativeMathAdapter(SourceAdapter):
    source_id = "illustrative-math"

    def __init__(self, courses: list[str] | None = None, *,
                 path_family: str = "ms",
                 timeout: float = 30.0, max_lessons: int | None = None):
        """path_family: 'ms' (grades 6-8), 'hs' (grades 9-12), or 'k5' (K-5)."""
        self.path_family = path_family
        self.timeout = timeout
        self.max_lessons = max_lessons
        self._meta: dict[str, dict] = {}

        if path_family == "k5":
            self.courses = courses or list(K5_GRADES)
        elif path_family == "hs":
            self.courses = courses or list(HS_COURSE_NAME)
        else:
            self.courses = courses or list(MS_COURSE_GRADE)

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

    @staticmethod
    def _k5_unit_lessons(payload: str, grade: str) -> list[tuple[str, str]]:
        """Extract (unit-num, lesson-num) pairs from a K-5 grade units page."""
        doc = lxml_html.fromstring(payload)
        results: list[tuple[str, str]] = []
        pat = re.compile(rf"/k5/teachers/{re.escape(grade)}/unit-(\d+)/lesson-(\d+)/")
        for a in doc.xpath("//a/@href"):
            m = pat.search(a)
            if m:
                results.append((m.group(1), m.group(2)))
        return results

    @staticmethod
    def _k5_units(payload: str, grade: str) -> list[str]:
        """Extract unit numbers from a K-5 grade page."""
        doc = lxml_html.fromstring(payload)
        seen: set[str] = set()
        pat = re.compile(rf"/k5/teachers/{re.escape(grade)}/unit-(\d+)/")
        for a in doc.xpath("//a/@href"):
            m = pat.search(a)
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

    # ── Stage 1: fetch ────────────────────────────────────────────────────────
    def fetch(self) -> list[RawContent]:
        now = datetime.now(timezone.utc).isoformat()
        raw: list[RawContent] = []
        with httpx.Client(timeout=self.timeout, headers={"User-Agent": "oer-mcp/0.1"}) as client:
            if self.path_family == "k5":
                raw = self._fetch_k5(client, now)
            elif self.path_family == "hs":
                raw = self._fetch_ms_hs(client, now, root="HS", grade_map=None)
            else:
                raw = self._fetch_ms_hs(client, now, root="MS",
                                        grade_map=MS_COURSE_GRADE)
        return raw

    def _fetch_ms_hs(self, client: httpx.Client, now: str, *,
                     root: str, grade_map: dict[str, str] | None) -> list[RawContent]:
        """Crawl MS or HS (same URL structure: /{root}/teachers/{course}/{unit}/{lesson}/index.html)."""
        raw: list[RawContent] = []
        for course in self.courses:
            grade = (grade_map or {}).get(course, "HS")
            cidx = self._get(client, f"/{root}/teachers/{course}/index.html")
            if not cidx:
                continue
            units = self._child_indices(cidx, f"/{root}/teachers/{course}/")
            for unit in units:
                uidx = self._get(client, f"/{root}/teachers/{course}/{unit}/index.html")
                if not uidx:
                    continue
                lessons = self._child_indices(uidx, f"/{root}/teachers/{course}/{unit}/")
                for lesson in lessons:
                    path = f"/{root}/teachers/{course}/{unit}/{lesson}/index.html"
                    payload = self._get(client, path)
                    if not payload:
                        continue
                    prefix = root.lower()
                    key = f"{prefix}-{course}-{unit}-{lesson}"
                    self._meta[key] = {
                        "grade": grade, "course": course,
                        "unit": unit, "lesson": lesson,
                        "url": BASE + path, "family": self.path_family,
                    }
                    raw.append(RawContent(source_id=self.source_id, key=key,
                                          url=BASE + path, fetched_at=now,
                                          payload=payload))
                    if self.max_lessons and len(raw) >= self.max_lessons:
                        return raw
        return raw

    def _fetch_k5(self, client: httpx.Client, now: str) -> list[RawContent]:
        """Crawl K-5: /k5/teachers/{grade}/unit-{n}/lesson-{n}/preparation.html"""
        raw: list[RawContent] = []
        for grade_slug in self.courses:
            grade_num = K5_GRADE_BAND.get(grade_slug, grade_slug)
            # Get units from the grade's units page
            units_page = self._get(client, f"/k5/teachers/{grade_slug}/units.html")
            if not units_page:
                continue
            units = self._k5_units(units_page, grade_slug)
            for unit in units:
                # Get lessons from unit page
                lessons_page = self._get(client,
                    f"/k5/teachers/{grade_slug}/unit-{unit}/lessons.html")
                if not lessons_page:
                    continue
                # Extract lesson numbers from links
                doc = lxml_html.fromstring(lessons_page)
                lesson_nums: list[str] = []
                pat = re.compile(
                    rf"/k5/teachers/{re.escape(grade_slug)}/unit-{re.escape(unit)}"
                    rf"/lesson-(\d+)/")
                seen: set[str] = set()
                for a in doc.xpath("//a/@href"):
                    m = pat.search(a)
                    if m and m.group(1) not in seen:
                        seen.add(m.group(1))
                        lesson_nums.append(m.group(1))
                lesson_nums.sort(key=int)

                for lesson in lesson_nums:
                    path = (f"/k5/teachers/{grade_slug}/unit-{unit}"
                            f"/lesson-{lesson}/preparation.html")
                    payload = self._get(client, path)
                    if not payload:
                        continue
                    key = f"k5-{grade_slug}-u{unit}-l{lesson}"
                    self._meta[key] = {
                        "grade": grade_num, "course": grade_slug,
                        "unit": unit, "lesson": lesson,
                        "url": BASE + path, "family": "k5",
                    }
                    raw.append(RawContent(source_id=self.source_id, key=key,
                                          url=BASE + path, fetched_at=now,
                                          payload=payload))
                    if self.max_lessons and len(raw) >= self.max_lessons:
                        return raw
        return raw

    def catalog(self) -> dict:
        source = {
            "id": self.source_id,
            "full_name": "Illustrative Mathematics",
            "license": LICENSE, "license_url": LICENSE_URL,
            "base_url": BASE,
        }
        if self.path_family == "k5":
            books = [{
                "id": "im-k5-math", "source_id": self.source_id,
                "title": "Illustrative Mathematics K–5 Math (First Edition)",
                "subject": "mathematics", "grade_band": "K-5",
                "license": LICENSE, "url": BASE + "/k5/curriculum.html",
            }]
        elif self.path_family == "hs":
            books = [{
                "id": "im-hs-math", "source_id": self.source_id,
                "title": "Illustrative Mathematics HS Math (First Edition)",
                "subject": "mathematics", "grade_band": "9-12",
                "license": LICENSE, "url": BASE + "/HS/index.html",
            }]
        else:
            books = [{
                "id": "im-ms-math", "source_id": self.source_id,
                "title": "Illustrative Mathematics 6–8 Math (First Edition)",
                "subject": "mathematics", "grade_band": "6-8",
                "license": LICENSE, "url": BASE + "/MS/index.html",
            }]
        return {"source": source, "books": books}

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
        """Structured, predictable title."""
        grade = meta.get('grade', '')
        family = meta.get('family', 'ms')
        if family == "hs":
            course_name = HS_COURSE_NAME.get(meta.get('course', ''), f"Course {meta.get('course')}")
            base = f"IM {course_name}, Unit {meta['unit']}, Lesson {meta['lesson']}"
        elif family == "k5":
            base = f"IM Grade {grade}, Unit {meta['unit']}, Lesson {meta['lesson']}"
        else:
            base = f"IM Grade {grade}, Unit {meta['unit']}, Lesson {meta['lesson']}"
        for h in doc.xpath('//*[contains(@class,"hero__heading")]'):
            t = re.sub(r"\s+", " ", h.text_content()).strip()
            t = re.sub(r"\s*\(\d+\s*minutes?\)\s*$", "", t)
            if t and len(t) < 100:
                return f"{base}: {t}"
        return base

    # ── Stage 2: parse → one exposition chunk per lesson + publisher tags ──────
    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        chunks: list[ContentChunk] = []
        grade_band_map = {"k5": "K-5", "ms": "6-8", "hs": "9-12"}
        book_id_map = {"k5": "im-k5-math", "ms": "im-ms-math", "hs": "im-hs-math"}
        label_map = {"k5": "K–5", "ms": "6–8", "hs": "HS"}

        for item in raw:
            meta = self._meta.get(item.key, {})
            family = meta.get("family", self.path_family)
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
            band_label = label_map.get(family, "6–8")
            attribution = (
                f"Illustrative Mathematics {band_label} Math, {title}, {LICENSE} "
                f"(© Illustrative Mathematics, im.kendallhunt.com)"
            )
            chunks.append(ContentChunk(
                id=f"im-{item.key}-expo",
                book_id=book_id_map.get(family, "im-ms-math"),
                source_id=self.source_id,
                title=title,
                content=text,
                content_type="exposition",
                chapter=f"Unit {meta.get('unit')}",
                section=f"Lesson {meta.get('lesson')}",
                grade_band=grade_band_map.get(family, "6-8"),
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
