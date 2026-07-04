"""NAEP adapter — National Assessment of Educational Progress released items.

Source: NAEP Questions Tool — https://www.nationsreportcard.gov/nqt/
License: Public domain (U.S. federal government work, 17 U.S.C. § 105)
DB: oer_core.db

Endpoints (reverse-engineered from the NQT SPA, 2026-07; all sessionless):
  POST /nqt/api/queryresults/getTabular            item catalog w/ metadata
  GET  /nqt/api/queryresults/GetItem?tableID=N     item HTML (text lives in the
                                                   screenshot's alt attribute for
                                                   image-rendered items)
  GET  /nqt/api/queryresults/GetItemScoreGuide?tableID=N   answer key HTML
  POST /nqt/api/queryresults/GetItemPerformanceData        choice-level national
                                                   distributions; the starred
                                                   choice's percent → difficulty

Each item carries national percent-correct data — a real-world difficulty signal
unavailable from any other source in the corpus. NAEP cognitive complexity
(Low/Moderate/High) maps to DOK 1/2/3. No CCSS tags → embedding alignment.

Chunk ID: "naep-gr{grade}-{tableID}"
Book ID:  "naep-math-gr{grade}"
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import httpx

from oer_shared.models import ContentChunk

from .base import RawContent, SourceAdapter, ValidationResult

LICENSE = "Public Domain"
LICENSE_URL = "https://nces.ed.gov/nationsreportcard/about/"

_API = "https://www.nationsreportcard.gov/nqt/api/queryresults"

GRADES = [4, 8, 12]
_GRADE_BAND = {4: "K-5", 8: "6-8", 12: "9-12"}

# NAEP assessment years available in the NQT (from the querypanel payload).
YEARS = [2024, 2022, 2017, 2013, 2011, 2009, 2007, 2005, 2003, 1996, 1992, 1990]

_COMPLEXITY_TO_DOK = {"low": 1, "moderate": 2, "high": 3}

_ITEM_TYPE_MAP = {
    "mc": "multiple_choice",
    "sr": "multiple_choice",       # selected response
    "scr": "constructed_response",
    "ecr": "constructed_response",
    "cr": "constructed_response",
}

_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
}

_TAG_RE = re.compile(r"<[^>]+>")
_ALT_RE = re.compile(r'alt="([^"]+)"')


def _catalog_body(grades: list[int], years: list[int]) -> dict:
    """Minimal getTabular payload the server accepts (verified 2026-07)."""
    return {
        "SubjectCode": "MAT",
        "GradeStr": ",".join(str(g) for g in grades),
        "SystemID": "1",
        "SubjectGradeInfo": [{
            "subject": "MAT", "label": "Mathematics", "ndeSystemID": "1",
            "ndeSystem": "NDEMAIN", "isSelected": True,
            "gradeList": [
                {"cohort": i + 1, "grade": str(g), "gradeLabel": f"Grade {g}",
                 "isSelected": True, "isAge": False, "numMCItems": 0}
                for i, g in enumerate(grades)
            ],
        }],
        "YearsInfo": [
            {"year": y, "sample": "R3" if y > 2000 else "R2", "tab": None,
             "yearSample": f"{y}{'R3' if y > 2000 else 'R2'}",
             "isSelected": True, "framework": 0}
            for y in years
        ],
    }


def _item_text(item_html: str) -> str:
    """Extract question text from GetItem HTML. Image-rendered items carry the
    full text in the screenshot's alt attribute; HTML items are stripped of tags."""
    alts = _ALT_RE.findall(item_html)
    best_alt = max(alts, key=len) if alts else ""
    if "QUESTION TEXT:" in best_alt:
        text = best_alt
        text = re.sub(r"^Screen shot of an interactive question\.\s*", "", text)
        text = text.replace("QUESTION TEXT:", "").strip()
        text = re.sub(r"\s*ANSWER CHOICES:\s*", "\n", text)
        return _unescape(text)
    # HTML-rendered item: strip tags
    text = _TAG_RE.sub(" ", item_html)
    return _unescape(re.sub(r"\s+", " ", text).strip())


def _unescape(s: str) -> str:
    import html
    return html.unescape(s.replace("\\r\\n", "\n")).strip()


def _answer_from_scoreguide(guide_html: str) -> str | None:
    text = _unescape(re.sub(r"\s+", " ", _TAG_RE.sub(" ", guide_html)).strip())
    return text[:500] if text else None


def _pct_correct(perf: dict) -> float | None:
    """National percent for the starred (correct) choice, as 0–1."""
    try:
        for series in perf["result"]["series"]:
            for dp in series["dataPoints"]:
                if "*" in (dp.get("AxisLabel") or ""):
                    return float(dp["YValues"][0]) / 100.0
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    return None


class NAEPAdapter(SourceAdapter):
    source_id = "naep"

    def __init__(self, grades: list[int] | None = None,
                 years: list[int] | None = None, *,
                 timeout: float = 30.0, max_items: int | None = None,
                 delay: float = 0.15):
        self.grades = grades or GRADES
        self.years = years or YEARS
        self.timeout = timeout
        self.max_items = max_items
        self.delay = delay
        self._meta: dict[str, dict] = {}

    def catalog(self) -> dict:
        return {
            "source": {
                "id": self.source_id,
                "full_name": "National Assessment of Educational Progress (NAEP) Released Items",
                "license": LICENSE, "license_url": LICENSE_URL,
                "base_url": "https://www.nationsreportcard.gov/nqt/",
            },
            "books": [
                {
                    "id": f"naep-math-gr{g}",
                    "source_id": self.source_id,
                    "title": f"NAEP Mathematics — Grade {g} Released Items",
                    "subject": "mathematics",
                    "grade_band": _GRADE_BAND[g],
                    "license": LICENSE,
                    "url": "https://www.nationsreportcard.gov/nqt/",
                }
                for g in self.grades
            ],
        }

    def fetch(self) -> list[RawContent]:
        now = datetime.now(timezone.utc).isoformat()
        raw: list[RawContent] = []
        with httpx.Client(timeout=self.timeout, headers=_HEADERS) as client:
            resp = client.post(_API + "/getTabular",
                               json=_catalog_body(self.grades, self.years))
            resp.raise_for_status()
            grid = resp.json().get("gridItemsList", [])
            print(f"[naep] catalog: {len(grid)} items")

            for i, item in enumerate(grid):
                table_id = item.get("itemTableID")
                if not table_id:
                    continue
                detail: dict = {"grid": item}

                try:
                    r = client.get(f"{_API}/GetItem", params={"tableID": table_id})
                    if r.status_code == 200:
                        detail["item"] = r.json()
                except (httpx.HTTPError, ValueError):
                    pass
                try:
                    r = client.get(f"{_API}/GetItemScoreGuide",
                                   params={"tableID": table_id})
                    if r.status_code == 200:
                        detail["scoreguide"] = r.text
                except httpx.HTTPError:
                    pass
                try:
                    r = client.post(f"{_API}/GetItemPerformanceData", json={
                        "itemTableID": int(table_id), "ndeSystemId": "1",
                        "subjectCode": "MAT", "jurisdictionsSelected": "NT",
                        "output": 0, "showStandardError": False,
                        "statistics": ["MN", "RP"], "variablesSelected": "TOTAL",
                    })
                    if r.status_code == 200:
                        detail["perf"] = r.json()
                except (httpx.HTTPError, ValueError):
                    pass

                self._meta[str(table_id)] = detail
                raw.append(RawContent(
                    source_id=self.source_id, key=str(table_id),
                    url=f"https://www.nationsreportcard.gov/nqt/{table_id}",
                    fetched_at=now, payload="",
                ))
                if (i + 1) % 100 == 0:
                    print(f"[naep] fetched {i + 1}/{len(grid)} item details")
                if self.max_items and len(raw) >= self.max_items:
                    break
                if self.delay:
                    time.sleep(self.delay)
        return raw

    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        chunks: list[ContentChunk] = []
        for rc in raw:
            detail = self._meta.get(rc.key)
            if not detail:
                continue
            grid = detail["grid"]
            grade = grid.get("gradeAsInt") or 4
            year = grid.get("yearAsInt")
            block = grid.get("blockID") or "?"
            qnum = grid.get("questionNum") or "?"
            desc = grid.get("description") or ""

            item_html = (detail.get("item") or {}).get("itemHTML", "")
            text = _item_text(item_html) if item_html else ""
            if not text or len(text.split()) < 5:
                # Fall back to the catalog description so coverage survives
                # items whose content is purely graphical.
                text = desc
            if not text or len(text.split()) < 3:
                continue

            raw_type = (grid.get("type") or "").lower()
            item_type = _ITEM_TYPE_MAP.get(raw_type, "constructed_response")
            dok = _COMPLEXITY_TO_DOK.get((grid.get("complexity") or "").lower())
            answer = _answer_from_scoreguide(detail.get("scoreguide", ""))
            difficulty = _pct_correct(detail.get("perf", {}))
            content_area = grid.get("contentArea") or ""

            body = f"{desc}\n\n{text}" if desc and desc not in text else text
            if content_area:
                body += f"\n\nContent area: {content_area}"

            attribution = (
                f"National Assessment of Educational Progress (NAEP), "
                f"Mathematics Grade {grade}, {year}, Block {block} Question {qnum}. "
                f"Public Domain. National Center for Education Statistics, "
                f"U.S. Department of Education. nationsreportcard.gov"
            )
            chunks.append(ContentChunk(
                id=f"naep-gr{grade}-{rc.key}",
                book_id=f"naep-math-gr{grade}",
                source_id=self.source_id,
                title=f"NAEP Grade {grade} ({year}): {desc[:80]}",
                content=body,
                content_type="assessment",
                grade_band=_GRADE_BAND.get(grade, "K-5"),
                word_count=len(body.split()),
                source_url="https://www.nationsreportcard.gov/nqt/searchquestions",
                attribution=attribution,
                item_type=item_type,
                dok_level=dok,
                answer_key=answer,
                exam_series=f"NAEP Grade {grade}",
                exam_year=year,
                difficulty=difficulty,
                item_generation="released",
            ))
        return chunks

    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        errors = [f"{c.id}: empty content" for c in chunks if not c.content.strip()]
        if not chunks:
            errors.append("no chunks produced — verify NQT API endpoints")
        with_diff = sum(1 for c in chunks if c.difficulty is not None)
        with_answer = sum(1 for c in chunks if c.answer_key)
        with_dok = sum(1 for c in chunks if c.dok_level)
        return ValidationResult(
            ok=not errors, errors=errors, warnings=[],
            stats={
                "total": len(chunks),
                "with_difficulty": with_diff,
                "with_answer": with_answer,
                "with_dok": with_dok,
            },
        )
