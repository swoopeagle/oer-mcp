"""NAEP adapter — National Assessment of Educational Progress released items.

Source: NCES Questions Tool — https://nces.ed.gov/nationsreportcard/nqt/
License: Public domain (U.S. federal government work, 17 U.S.C. § 105)
Volume: ~1,500 released math items across grades 4, 8, and 12
DB: oer_core.db (public domain)

Each item carries national percent-correct data — a real-world difficulty signal
unavailable from any other source in the corpus. DOK level is inferred from NAEP's
own cognitive complexity classification (Low/Medium/High → DOK 1/2/3).

The NCES Questions Tool has a JSON API used by its search interface. The endpoint
below returns items in JSON; CCSS alignment is NOT publisher-tagged on NAEP items
(NAEP predates widespread CCSS adoption) so items land as embedding alignment only
after the align stage.

Chunk ID: "naep-{grade}-{block}-{position}"
Book ID:  "naep-math-gr{grade}"
DB:       oer_core.db
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from oer_shared.models import ContentChunk

from .base import RawContent, SourceAdapter, ValidationResult

LICENSE = "Public Domain"
LICENSE_URL = "https://nces.ed.gov/nationsreportcard/about/"

# NAEP Questions Tool API — verified against nces.ed.gov/nationsreportcard/nqt/
# TODO: confirm exact params by inspecting XHR in browser dev tools on the NQT site.
_API_BASE = "https://nces.ed.gov/nationsreportcard"
_SEARCH_PATH = "/api/v1/questions/search"

GRADES = [4, 8, 12]
_GRADE_BAND = {4: "K-5", 8: "6-8", 12: "9-12"}

# NAEP cognitive complexity → Webb's DOK
_COG_TO_DOK = {"low": 1, "medium": 2, "high": 3}

_ITEM_TYPE_MAP = {
    "multiple choice": "multiple_choice",
    "mc": "multiple_choice",
    "short constructed response": "constructed_response",
    "extended constructed response": "constructed_response",
    "scr": "constructed_response",
    "ecr": "constructed_response",
}


class NAEPAdapter(SourceAdapter):
    source_id = "naep"

    def __init__(self, grades: list[int] | None = None, *,
                 timeout: float = 30.0, max_items: int | None = None):
        self.grades = grades or GRADES
        self.timeout = timeout
        self.max_items = max_items
        self._meta: dict[str, dict] = {}

    def catalog(self) -> dict:
        return {
            "source": {
                "id": self.source_id,
                "full_name": "National Assessment of Educational Progress (NAEP) Released Items",
                "license": LICENSE, "license_url": LICENSE_URL,
                "base_url": "https://nces.ed.gov/nationsreportcard/nqt/",
            },
            "books": [
                {
                    "id": f"naep-math-gr{g}",
                    "source_id": self.source_id,
                    "title": f"NAEP Mathematics — Grade {g} Released Items",
                    "subject": "mathematics",
                    "grade_band": _GRADE_BAND[g],
                    "license": LICENSE,
                    "url": "https://nces.ed.gov/nationsreportcard/nqt/",
                }
                for g in self.grades
            ],
        }

    def fetch(self) -> list[RawContent]:
        now = datetime.now(timezone.utc).isoformat()
        raw: list[RawContent] = []
        with httpx.Client(timeout=self.timeout,
                          headers={"User-Agent": "oer-mcp/0.1 (educator tool)"}) as client:
            for grade in self.grades:
                page = 0
                while True:
                    # TODO: verify exact params after inspecting NQT network traffic.
                    # Likely params: subject, grade, type (released), page, pageSize.
                    resp = client.get(
                        _API_BASE + _SEARCH_PATH,
                        params={
                            "subject": "mathematics",
                            "grade": grade,
                            "status": "released",
                            "page": page,
                            "pageSize": 50,
                        },
                    )
                    if resp.status_code != 200:
                        print(f"[naep] grade {grade} page {page}: HTTP {resp.status_code}")
                        break
                    data = resp.json()
                    items = data.get("items") or data.get("questions") or []
                    if not items:
                        break
                    for item in items:
                        key = str(item.get("questionId") or item.get("id") or "")
                        if not key:
                            continue
                        item["_grade"] = grade
                        self._meta[key] = item
                        raw.append(RawContent(
                            source_id=self.source_id,
                            key=key,
                            url=f"https://nces.ed.gov/nationsreportcard/nqt/Search#{key}",
                            fetched_at=now,
                            payload=resp.text,
                        ))
                        if self.max_items and len(raw) >= self.max_items:
                            return raw
                    total = data.get("total", 0)
                    if (page + 1) * 50 >= total:
                        break
                    page += 1
        return raw

    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        chunks: list[ContentChunk] = []
        seen: set[str] = set()

        for item in raw:
            meta = self._meta.get(item.key)
            if not meta or item.key in seen:
                continue
            seen.add(item.key)

            grade = meta.get("_grade", 4)
            grade_band = _GRADE_BAND.get(grade, "K-5")

            # Item text: NAEP items have stem + answer choices for MC
            stem = meta.get("questionText") or meta.get("stem") or meta.get("content") or ""
            choices = meta.get("answerChoices") or meta.get("choices") or []
            if choices and isinstance(choices, list):
                choices_text = "\n".join(
                    f"{c.get('label','')}) {c.get('text','')}"
                    for c in choices if isinstance(c, dict)
                )
                text = f"{stem}\n\n{choices_text}".strip() if choices_text else stem
            else:
                text = stem.strip()

            if not text or len(text.split()) < 5:
                continue

            raw_type = (meta.get("itemType") or meta.get("type") or "").lower()
            item_type = _ITEM_TYPE_MAP.get(raw_type, "constructed_response")

            # Correct answer
            answer = meta.get("correctAnswer") or meta.get("answerKey") or ""
            scoring = meta.get("scoringGuide") or meta.get("rubric") or ""
            answer_key = "; ".join(p for p in [answer, scoring] if p) or None

            # Difficulty: NAEP reports % correct nationally
            pct_correct = meta.get("percentCorrect") or meta.get("difficulty")
            try:
                difficulty = float(pct_correct) / 100.0 if pct_correct else None
            except (TypeError, ValueError):
                difficulty = None

            # DOK from NAEP cognitive complexity
            cog = (meta.get("cognitiveComplexity") or "").lower()
            dok = _COG_TO_DOK.get(cog)

            # Year
            year = meta.get("year") or meta.get("assessmentYear")
            try:
                year = int(str(year)[:4]) if year else None
            except (TypeError, ValueError):
                year = None

            block = meta.get("block") or "?"
            pos = meta.get("position") or meta.get("itemNumber") or item.key
            title = f"NAEP Grade {grade} Math Item {block}-{pos}"
            attribution = (
                f"National Assessment of Educational Progress (NAEP), "
                f"Mathematics Grade {grade}, {year or 'released'}. "
                f"Public Domain. National Center for Education Statistics, "
                f"U.S. Department of Education. nces.ed.gov/nationsreportcard"
            )

            chunks.append(ContentChunk(
                id=f"naep-gr{grade}-{item.key}",
                book_id=f"naep-math-gr{grade}",
                source_id=self.source_id,
                title=title,
                content=text,
                content_type="assessment",
                grade_band=grade_band,
                word_count=len(text.split()),
                source_url=item.url,
                attribution=attribution,
                item_type=item_type,
                dok_level=dok,
                answer_key=answer_key,
                exam_series=f"NAEP Grade {grade}",
                exam_year=year,
                difficulty=difficulty,
                item_generation="released",
            ))
        return chunks

    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        errors = [f"{c.id}: empty content" for c in chunks if not c.content.strip()]
        if not chunks:
            errors.append("no chunks produced — verify NAEP API endpoint and params")
        with_diff = sum(1 for c in chunks if c.difficulty is not None)
        return ValidationResult(
            ok=not errors, errors=errors, warnings=[],
            stats={
                "total": len(chunks),
                "with_difficulty": with_diff,
                "missing_difficulty": len(chunks) - with_diff,
            },
        )
