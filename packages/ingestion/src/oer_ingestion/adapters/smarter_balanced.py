"""Smarter Balanced adapter — SBAC sample item bank (CC BY 4.0).

Source: https://sampleitems.smarterbalanced.org/
Items are pre-tagged with CCSS standards by the publisher → publisher_guide tier.
Covers grades 3–8 and HS (grade 11) for ELA and Math; we ingest Math only.

Access: public JSON API backed by the SBAC Digital Library. The sample items site
exposes a REST API without authentication for released sample items. Full item bank
(~20k items) requires an educator account and the Digital Library API at
https://digitallibrary.smarterbalanced.org/ — see TODO below.

Chunk ID: "sbac-{grade}-{item_key}-{item_type}"
Book ID:  "sbac-math-gr{grade}"
DB:       oer_core.db (CC BY 4.0)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from oer_shared.models import ContentChunk, StandardAlignment

from .base import RawContent, SourceAdapter, ValidationResult

LICENSE = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"

# TODO: verify exact API endpoint after manual inspection of network traffic on
# https://sampleitems.smarterbalanced.org/BrowseItems. The URL below is the
# documented public search endpoint; params may need adjustment.
_API_BASE = "https://sampleitems.smarterbalanced.org"
_SEARCH_PATH = "/api/items/search"

GRADES = [3, 4, 5, 6, 7, 8, 11]  # 11 = HS

_ITEM_TYPE_MAP = {
    "mc": "multiple_choice",
    "ms": "multiple_choice",   # multi-select → closest fit
    "sa": "constructed_response",
    "wer": "constructed_response",
    "er": "constructed_response",
    "te": "constructed_response",
    "eq": "constructed_response",
    "gi": "performance_task",
    "sim": "performance_task",
}

_GRADE_BAND = {
    **{g: "K-5" for g in [3, 4, 5]},
    **{g: "6-8" for g in [6, 7, 8]},
    11: "9-12",
}


def _ccss_id(short: str) -> str | None:
    """SBAC CCSS tag → StandardGraph ID.
    SBAC uses forms like 'CCSS.Math.Content.6.RP.A.3' or '6.RP.A.3'."""
    short = re.sub(r"^CCSS\.Math\.Content\.", "", short).strip()
    parts = short.split(".")
    # drop cluster letter (single uppercase after the domain)
    if len(parts) >= 4 and len(parts[2]) == 1 and parts[2].isalpha():
        parts = [parts[0], parts[1], *parts[3:]]
    elif len(parts) == 3 and parts[2].isalpha():
        return None  # cluster-level header
    # drop trailing lowercase sub-part
    if parts and len(parts[-1]) == 1 and parts[-1].islower():
        parts = parts[:-1]
    if len(parts) < 3:
        return None
    return "CCSS.MATH." + ".".join(parts)


class SmarterBalancedAdapter(SourceAdapter):
    source_id = "smarter-balanced"

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
                "full_name": "Smarter Balanced Assessment Consortium (SBAC) Sample Items",
                "license": LICENSE, "license_url": LICENSE_URL,
                "base_url": _API_BASE,
            },
            "books": [
                {
                    "id": f"sbac-math-gr{g}",
                    "source_id": self.source_id,
                    "title": f"Smarter Balanced Math — Grade {g if g != 11 else '11 (HS)'}",
                    "subject": "mathematics",
                    "grade_band": _GRADE_BAND[g],
                    "license": LICENSE,
                    "url": f"{_API_BASE}/BrowseItems",
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
                    # TODO: verify exact params after inspecting network traffic.
                    # Common SBAC API params: subject, grade, page, pageSize.
                    resp = client.get(
                        _API_BASE + _SEARCH_PATH,
                        params={
                            "subject": "MATH",
                            "grade": grade,
                            "page": page,
                            "pageSize": 50,
                        },
                    )
                    if resp.status_code != 200:
                        print(f"[sbac] grade {grade} page {page}: HTTP {resp.status_code}")
                        break
                    data = resp.json()
                    items = data.get("items") or data.get("results") or []
                    if not items:
                        break
                    for item in items:
                        key = str(item.get("itemKey") or item.get("id") or "")
                        if not key:
                            continue
                        item["_grade"] = grade
                        self._meta[key] = item
                        raw.append(RawContent(
                            source_id=self.source_id,
                            key=key,
                            url=f"{_API_BASE}/Item/Show?bankKey=187&itemKey={key}",
                            fetched_at=now,
                            payload=resp.text,  # store raw page JSON
                        ))
                        if self.max_items and len(raw) >= self.max_items:
                            return raw
                    # pagination
                    total = data.get("total", 0)
                    if (page + 1) * 50 >= total:
                        break
                    page += 1
        return raw

    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        import json
        chunks: list[ContentChunk] = []
        seen: set[str] = set()

        for item in raw:
            meta = self._meta.get(item.key)
            if not meta or item.key in seen:
                continue
            seen.add(item.key)

            grade = meta.get("_grade", 0)
            grade_band = _GRADE_BAND.get(grade, "9-12")
            raw_type = (meta.get("interactionType") or meta.get("type") or "").lower()
            item_type = _ITEM_TYPE_MAP.get(raw_type, "constructed_response")

            # Item content: SBAC items have stimulus + question stem
            stimulus = meta.get("stimulusContent") or meta.get("stimulus") or ""
            stem = meta.get("itemContent") or meta.get("content") or ""
            text = "\n\n".join(p for p in [stimulus, stem] if p).strip()
            if not text or len(text.split()) < 5:
                continue

            # Answer key: SBAC releases answer keys for many item types
            answer = meta.get("answerKey") or meta.get("correctAnswer") or ""

            # Difficulty: SBAC provides difficulty band
            diff_raw = meta.get("difficulty") or meta.get("depthOfKnowledge") or 0
            try:
                difficulty = float(diff_raw) / 4.0 if diff_raw else None
            except (TypeError, ValueError):
                difficulty = None

            dok = meta.get("depthOfKnowledge")
            try:
                dok = int(dok) if dok else None
            except (TypeError, ValueError):
                dok = None

            # Standards
            std_list = meta.get("standards") or meta.get("alignedStandards") or []
            if isinstance(std_list, str):
                std_list = [std_list]
            aligns = []
            for s in std_list:
                cid = _ccss_id(str(s))
                if cid:
                    aligns.append(StandardAlignment(
                        standard_id=cid, standard_system="ccss",
                        alignment_score=0.95, alignment_source="publisher_guide",
                        coverage_notes="SBAC item tagged to this standard by publisher.",
                    ))

            title = f"SBAC Grade {grade} Math Item {item.key}"
            attribution = (
                f"Smarter Balanced Assessment Consortium, Math Grade {grade} Sample Item "
                f"{item.key}. {LICENSE} (© Smarter Balanced Assessment Consortium, "
                f"sampleitems.smarterbalanced.org)"
            )
            chunks.append(ContentChunk(
                id=f"sbac-gr{grade}-{item.key}-{item_type[:4]}",
                book_id=f"sbac-math-gr{grade}",
                source_id=self.source_id,
                title=title,
                content=text,
                content_type="assessment",
                grade_band=grade_band,
                word_count=len(text.split()),
                source_url=item.url,
                attribution=attribution,
                standard_alignments=aligns,
                item_type=item_type,
                dok_level=dok,
                answer_key=answer or None,
                exam_series=f"Smarter Balanced Grade {grade}",
                exam_year=meta.get("year") or meta.get("releaseYear"),
                difficulty=difficulty,
                item_generation="released",
            ))
        return chunks

    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        errors = [f"{c.id}: empty content" for c in chunks if not c.content.strip()]
        errors += [f"{c.id}: empty attribution" for c in chunks if not c.attribution]
        if not chunks:
            errors.append("no chunks produced — verify SBAC API endpoint and params")
        with_std = sum(1 for c in chunks if c.standard_alignments)
        no_dok = sum(1 for c in chunks if c.dok_level is None)
        return ValidationResult(
            ok=not errors, errors=errors,
            warnings=[f"{no_dok} items missing DOK level"] if no_dok else [],
            stats={
                "total": len(chunks),
                "with_publisher_std": with_std,
                "missing_dok": no_dok,
            },
        )
