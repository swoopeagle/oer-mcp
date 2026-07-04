"""OpenMiddle adapter — DOK-3 open-ended math problems (CC BY-NC-SA 4.0).

Source: https://www.openmiddle.com/
License: CC BY-NC-SA 4.0 → content lands in oer_ncsa.db
Volume: ~400 problems across K-12, each tagged with CCSS standard and DOK level.
Each problem is a fill-in-the-blank challenge requiring strategic thinking.

Structure:
  categories: /category/{grade-slug}/{domain-slug}/
  problems:   /{problem-slug}/

Each problem page carries:
  - Directions (the problem statement)
  - Hint / Answer (solution guidance)
  - rel=tag links: CCSS standard ID, DOK level, author
  - meta keywords: same info as comma-separated keywords
  - article class: category-{grade} for grade extraction
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
from lxml import html as lxml_html

from oer_shared.models import ContentChunk, StandardAlignment

from .base import RawContent, SourceAdapter, ValidationResult

BASE = "https://www.openmiddle.com"
LICENSE = "CC BY-NC-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
UA = "oer-mcp/0.1 (educational content indexing)"

GRADE_CATEGORIES = [
    "kindergarten",
    "grade-1", "grade-2", "grade-3", "grade-4", "grade-5",
    "grade-6", "grade-7", "grade-8",
    "high-school-algebra", "high-school-functions",
    "high-school-geometry", "high-school-number-and-quantity",
    "high-school-statistics-and-probability",
]

_GRADE_BAND = {
    "kindergarten": "K-5",
    "grade-1": "K-5", "grade-2": "K-5", "grade-3": "K-5",
    "grade-4": "K-5", "grade-5": "K-5",
    "grade-6": "6-8", "grade-7": "6-8", "grade-8": "6-8",
}

_GRADE_NUM = {
    "kindergarten": "K", "grade-1": "1", "grade-2": "2", "grade-3": "3",
    "grade-4": "4", "grade-5": "5", "grade-6": "6", "grade-7": "7",
    "grade-8": "8",
}

_CCSS_RE = re.compile(
    r"^(?:[K0-9]+\.[A-Z]{1,4}(?:\.[A-Z0-9]+)*"
    r"|[A-Z]-[A-Z]{1,4}(?:\.[A-Z0-9]+)*)$"
)

_DOK_RE = re.compile(r"DOK\s*(\d)", re.IGNORECASE)


def _parse_standard(tag: str) -> str | None:
    """Convert an OpenMiddle tag to a CCSS ID if it looks like a standard."""
    tag = tag.strip()
    if not _CCSS_RE.match(tag):
        return None
    if tag[0].isdigit() or tag[0] == "K":
        return "CCSS.MATH." + tag
    # HS format: A-SSE.3 → CCSS.MATH.HSA.SSE.3 (but keep cluster letter)
    # G-GPE.1 → CCSS.MATH.HSG.GPE.1
    # F-IF.1 → CCSS.MATH.HSF.IF.1
    # N-Q.1 → CCSS.MATH.HSN.Q.1
    # S-ID.1 → CCSS.MATH.HSS.ID.1
    parts = tag.split("-", 1)
    if len(parts) == 2:
        domain_letter = parts[0]
        rest = parts[1]
        return f"CCSS.MATH.HS{domain_letter}.{rest}"
    return None


def _parse_dok(tag: str) -> int | None:
    m = _DOK_RE.search(tag)
    return int(m.group(1)) if m else None


class OpenMiddleAdapter(SourceAdapter):
    source_id = "open-middle"

    def __init__(self, *, timeout: float = 30.0, max_problems: int | None = None,
                 grades: list[str] | None = None):
        self.timeout = timeout
        self.max_problems = max_problems
        self.grades = grades or GRADE_CATEGORIES
        self._meta: dict[str, dict] = {}

    def _get(self, client: httpx.Client, url: str) -> str | None:
        try:
            r = client.get(url, follow_redirects=True)
            if r.status_code != 200:
                return None
            return r.text
        except httpx.HTTPError:
            return None

    def fetch(self) -> list[RawContent]:
        now = datetime.now(timezone.utc).isoformat()
        raw: list[RawContent] = []
        seen_urls: set[str] = set()

        with httpx.Client(timeout=self.timeout, headers={"User-Agent": UA}) as client:
            for grade_cat in self.grades:
                url = f"{BASE}/category/{grade_cat}/"
                page_html = self._get(client, url)
                if not page_html:
                    continue
                problem_urls = self._extract_problem_urls(page_html, grade_cat)
                # Also check subcategory pages
                doc = lxml_html.fromstring(page_html)
                sub_links = doc.xpath(f'//a[contains(@href,"/category/{grade_cat}/")]/@href')
                for sub_url in set(sub_links):
                    sub_html = self._get(client, sub_url)
                    if sub_html:
                        problem_urls.extend(self._extract_problem_urls(sub_html, grade_cat))

                for prob_url in problem_urls:
                    if prob_url in seen_urls:
                        continue
                    seen_urls.add(prob_url)
                    payload = self._get(client, prob_url)
                    if not payload:
                        continue
                    slug = prob_url.rstrip("/").split("/")[-1]
                    key = f"om-{slug}"
                    self._meta[key] = {
                        "url": prob_url,
                        "grade_cat": grade_cat,
                    }
                    raw.append(RawContent(
                        source_id=self.source_id, key=key,
                        url=prob_url, fetched_at=now, payload=payload,
                    ))
                    if self.max_problems and len(raw) >= self.max_problems:
                        return raw
        return raw

    @staticmethod
    def _extract_problem_urls(page_html: str, grade_cat: str) -> list[str]:
        doc = lxml_html.fromstring(page_html)
        urls: list[str] = []
        for art in doc.xpath("//article"):
            links = art.xpath('.//h2//a/@href')
            for href in links:
                if href.startswith(BASE) or href.startswith("/"):
                    full = href if href.startswith("http") else BASE + href
                    urls.append(full)
        return urls

    def catalog(self) -> dict:
        return {
            "source": {
                "id": self.source_id,
                "full_name": "Open Middle",
                "license": LICENSE, "license_url": LICENSE_URL,
                "base_url": BASE,
            },
            "books": [{
                "id": "open-middle-math", "source_id": self.source_id,
                "title": "Open Middle Math Problems (K-12)",
                "subject": "mathematics", "grade_band": None,
                "license": LICENSE, "url": BASE,
            }],
        }

    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        chunks: list[ContentChunk] = []
        for item in raw:
            meta = self._meta.get(item.key, {})
            doc = lxml_html.fromstring(item.payload)

            articles = doc.xpath("//article")
            if not articles:
                continue
            art = articles[0]
            art_classes = art.get("class", "")

            # Title
            title_el = doc.xpath('//meta[@property="og:title"]/@content')
            title = title_el[0].replace(" | Open Middle®", "").strip() if title_el else item.key

            # Grade from article class
            grade_cat = meta.get("grade_cat", "")
            grade_from_class = re.findall(
                r"category-(grade-\d+|kindergarten|high-school[^\s]*)", art_classes
            )
            if grade_from_class:
                grade_cat = grade_from_class[0]

            grade_band = _GRADE_BAND.get(grade_cat, "9-12")
            grade_num = _GRADE_NUM.get(grade_cat, "HS")

            # Content: extract directions and hint/answer
            text = re.sub(r"\s+", " ", art.text_content()).strip()
            directions_match = re.search(
                r"Directions?:?\s*(.*?)(?:Hint|Answer|Source|Use this problem|Print)",
                text, re.IGNORECASE
            )
            directions = directions_match.group(1).strip() if directions_match else ""

            hint_match = re.search(
                r"(?:Hint|Answer)\s*(.*?)(?:Source|Use this problem|Print|Embedded)",
                text, re.IGNORECASE
            )
            hint = hint_match.group(1).strip() if hint_match else ""

            if not directions or len(directions) < 10:
                continue

            content = f"Directions: {directions}"
            if hint:
                content += f"\n\nAnswer/Hint: {hint}"

            # Tags: standards and DOK
            rel_tags = doc.xpath('//a[@rel="tag"]/text()')
            meta_kw = doc.xpath('//meta[@name="keywords"]/@content')
            all_tags = list(rel_tags)
            if meta_kw:
                all_tags.extend(t.strip() for t in meta_kw[0].split(","))
            all_tags = list(dict.fromkeys(all_tags))  # dedupe preserving order

            standards: list[str] = []
            dok: int | None = None
            author: str | None = None
            for tag in all_tags:
                sid = _parse_standard(tag)
                if sid:
                    standards.append(sid)
                elif _DOK_RE.search(tag):
                    dok = _parse_dok(tag)
                elif not any(c.isdigit() for c in tag) and tag not in (
                    "Open Middle", "Illustrative Mathematics"
                ):
                    if author is None:
                        author = tag

            aligns = [
                StandardAlignment(
                    standard_id=sid, standard_system="ccss",
                    alignment_score=0.95, alignment_source="publisher_guide",
                    coverage_notes="OpenMiddle problem tagged by author to this standard.",
                )
                for sid in standards
            ]

            attribution = (
                f"Open Middle, \"{title}\""
                f"{', by ' + author if author else ''}, {LICENSE}"
            )

            chunks.append(ContentChunk(
                id=item.key,
                book_id="open-middle-math",
                source_id=self.source_id,
                title=f"Open Middle: {title} (Grade {grade_num})",
                content=content,
                content_type="exercise_set",
                chapter=None,
                section=None,
                grade_band=grade_band,
                word_count=len(content.split()),
                source_url=meta.get("url", item.url),
                attribution=attribution,
                standard_alignments=aligns,
                dok_level=dok,
                item_type="constructed_response",
            ))
        return chunks

    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        errors = [f"{c.id}: empty content" for c in chunks if not c.content.strip()]
        if not chunks:
            errors.append("no chunks produced")
        with_std = sum(1 for c in chunks if c.standard_alignments)
        with_dok = sum(1 for c in chunks if c.dok_level)
        return ValidationResult(
            ok=not errors, errors=errors, warnings=[],
            stats={"total": len(chunks), "with_standards": with_std,
                   "with_dok": with_dok},
        )
