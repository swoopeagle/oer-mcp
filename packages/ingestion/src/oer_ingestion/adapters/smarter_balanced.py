"""Smarter Balanced adapter — SBAC sample item bank (CC BY 4.0).

Source: https://sampleitems.smarterbalanced.org/
Items are pre-tagged with CCSS standards by the publisher → publisher_guide tier.
Covers grades 3–8 and HS (grade 11) for Math.

Access: The sample items site exposes a JSON API (XHR-style, needs Accept/XHR headers)
at /BrowseItems/search. The search endpoint returns all metadata inline:
  - commonCoreStandardId + ccssDescription
  - depthOfKnowledge
  - interactionTypeCode/Label
  - domain, claim, target
  - grade

Item rendered content is served via external QTI viewer (not extractable). We store
the publisher metadata and a link to view the live item — valuable for coverage
analysis and crosswalk population.

Chunk ID: "sbac-gr{grade}-{itemKey}"
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

_BASE = "https://sampleitems.smarterbalanced.org"
_SEARCH_PATH = "/BrowseItems/search"

GRADES = [3, 4, 5, 6, 7, 8, 11]

_GRADE_BAND = {
    **{g: "K-5" for g in [3, 4, 5]},
    **{g: "6-8" for g in [6, 7, 8]},
    11: "9-12",
}

_ITEM_TYPE_MAP = {
    "mc": "multiple_choice",
    "ms": "multiple_choice",
    "sa": "constructed_response",
    "wer": "constructed_response",
    "er": "constructed_response",
    "te": "constructed_response",
    "eq": "constructed_response",
    "gi": "performance_task",
    "sim": "performance_task",
    "mi": "constructed_response",
    "ti": "constructed_response",
    "htq": "constructed_response",
}

_HEADERS = {
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
}


def _ccss_id(short: str) -> str | None:
    """SBAC standard tag → StandardGraph ID.

    SBAC uses bare forms like '3.OA.8', '6.RP.3', '8.EE.1', 'F-IF.4'.
    SG format: K-5 keeps cluster letter, 6-8 drops it, HS keeps it.
    """
    if not short or not short.strip():
        return None
    short = short.strip()

    # HS format: e.g. "F-IF.4" or "A-SSE.3"
    if re.match(r"^[A-Z]-[A-Z]{1,4}\.", short):
        parts = short.split("-", 1)
        domain_letter = parts[0]
        rest = parts[1]
        return f"CCSS.MATH.HS{domain_letter}.{rest}"

    parts = short.split(".")
    if len(parts) < 3:
        return None

    grade_str = parts[0]
    try:
        grade = int(grade_str) if grade_str != "K" else 0
    except ValueError:
        return None

    if grade <= 5:
        return "CCSS.MATH." + short
    else:
        # 6-8: drop cluster letter if present (single uppercase char in position 2)
        if len(parts) >= 4 and len(parts[2]) == 1 and parts[2].isupper():
            stripped = [parts[0], parts[1], *parts[3:]]
            return "CCSS.MATH." + ".".join(stripped)
        return "CCSS.MATH." + short


class SmarterBalancedAdapter(SourceAdapter):
    source_id = "smarter-balanced"

    def __init__(self, grades: list[int] | None = None, *,
                 timeout: float = 30.0, max_items: int | None = None):
        self.grades = grades or GRADES
        self.timeout = timeout
        self.max_items = max_items
        self._items: list[dict] = []

    def catalog(self) -> dict:
        return {
            "source": {
                "id": self.source_id,
                "full_name": "Smarter Balanced Assessment Consortium (SBAC) Sample Items",
                "license": LICENSE, "license_url": LICENSE_URL,
                "base_url": _BASE,
            },
            "books": [
                {
                    "id": f"sbac-math-gr{g}",
                    "source_id": self.source_id,
                    "title": f"Smarter Balanced Math — Grade {g if g != 11 else '11 (HS)'}",
                    "subject": "mathematics",
                    "grade_band": _GRADE_BAND[g],
                    "license": LICENSE,
                    "url": f"{_BASE}/BrowseItems",
                }
                for g in self.grades
            ],
        }

    def fetch(self) -> list[RawContent]:
        """Fetch all math items from SBAC search API (single request returns all)."""
        now = datetime.now(timezone.utc).isoformat()
        raw: list[RawContent] = []
        self._items = []

        with httpx.Client(timeout=self.timeout, headers=_HEADERS) as client:
            # The SBAC search returns all grades in one response regardless of
            # the grade param, so just fetch once with grade=3 and filter client-side
            try:
                resp = client.get(
                    _BASE + _SEARCH_PATH,
                    params={"subject": "MATH", "grade": "3"},
                )
                if resp.status_code != 200:
                    print(f"[sbac] search: HTTP {resp.status_code}")
                    return raw
                data = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                print(f"[sbac] search error: {e}")
                return raw

            items = data if isinstance(data, list) else data.get("items", [])
            # Filter to math items in our target grades
            grade_set = set(self.grades)
            math_items = []
            for item in items:
                if item.get("subjectCode") != "MATH":
                    continue
                # Map SBAC's grade field to actual grade number
                label = item.get("gradeLabel", "")
                grade_num = _parse_grade_label(label)
                if grade_num and grade_num in grade_set:
                    item["_grade"] = grade_num
                    math_items.append(item)

            print(f"[sbac] {len(math_items)} math items across grades {sorted(grade_set)}")

            for item in math_items:
                item_key = item.get("itemKey")
                bank_key = item.get("bankKey", 200)
                if not item_key:
                    continue
                self._items.append(item)
                raw.append(RawContent(
                    source_id=self.source_id,
                    key=f"{bank_key}-{item_key}",
                    url=f"{_BASE}/Item/Details/{bank_key}-{item_key}",
                    fetched_at=now,
                    payload="",
                ))
                if self.max_items and len(raw) >= self.max_items:
                    break

        return raw

    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        chunks: list[ContentChunk] = []

        for item in self._items:
            grade = item.get("_grade", 0)
            bank_key = item.get("bankKey", 200)
            item_key = item.get("itemKey")
            if not item_key:
                continue

            grade_band = _GRADE_BAND.get(grade, "9-12")

            # Interaction type
            raw_type = (item.get("interactionTypeCode") or "").lower()
            item_type = _ITEM_TYPE_MAP.get(raw_type, "constructed_response")
            interaction_label = item.get("interactionTypeLabel") or raw_type.upper()

            # Standard
            std_raw = item.get("commonCoreStandardId") or ""
            ccss_id = _ccss_id(std_raw)
            ccss_desc = item.get("ccssDescription") or ""

            # DOK
            dok_raw = item.get("depthOfKnowledge")
            try:
                dok = int(dok_raw) if dok_raw else None
            except (TypeError, ValueError):
                dok = None

            # Claim/target
            claim_label = item.get("claimLabel") or ""
            target_desc = item.get("targetDescription") or ""
            domain = item.get("domain") or ""

            # Build content
            parts = [
                f"Smarter Balanced Grade {grade} Mathematics Assessment Item",
                f"Type: {interaction_label}",
            ]
            if std_raw:
                parts.append(f"Standard: CCSS.MATH.Content.{std_raw}")
            if ccss_desc:
                parts.append(f"Standard Description: {ccss_desc}")
            if dok:
                parts.append(f"Depth of Knowledge: Level {dok}")
            if domain:
                parts.append(f"Domain: {domain}")
            if claim_label:
                parts.append(f"Claim: {claim_label}")
            if target_desc:
                parts.append(f"Target: {target_desc}")
            parts.append(
                f"\nView item: {_BASE}/Item/Details/{bank_key}-{item_key}"
            )

            content = "\n".join(parts)

            # Alignments
            aligns = []
            if ccss_id:
                aligns.append(StandardAlignment(
                    standard_id=ccss_id, standard_system="ccss",
                    alignment_score=0.95, alignment_source="publisher_guide",
                    coverage_notes=(
                        f"SBAC item {item_key} aligned by publisher. "
                        f"DOK {dok or '?'}, {interaction_label}."
                    ),
                ))

            title = f"SBAC Grade {grade} Math: {interaction_label} (Item {item_key})"
            attribution = (
                f"Smarter Balanced Assessment Consortium, Mathematics Grade {grade} "
                f"Sample Item {item_key}. {LICENSE} "
                f"(© Smarter Balanced, sampleitems.smarterbalanced.org)"
            )

            chunks.append(ContentChunk(
                id=f"sbac-gr{grade}-{item_key}",
                book_id=f"sbac-math-gr{grade}",
                source_id=self.source_id,
                title=title,
                content=content,
                content_type="assessment",
                grade_band=grade_band,
                word_count=len(content.split()),
                source_url=f"{_BASE}/Item/Details/{bank_key}-{item_key}",
                attribution=attribution,
                standard_alignments=aligns,
                item_type=item_type,
                dok_level=dok,
                answer_key=None,
                exam_series=f"Smarter Balanced Grade {grade}",
                exam_year=None,
                difficulty=None,
                item_generation="released",
            ))
        return chunks

    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        errors = [f"{c.id}: empty content" for c in chunks if not c.content.strip()]
        if not chunks:
            errors.append("no chunks produced — verify SBAC API connectivity")
        with_std = sum(1 for c in chunks if c.standard_alignments)
        with_dok = sum(1 for c in chunks if c.dok_level is not None)
        no_std = len(chunks) - with_std
        return ValidationResult(
            ok=not errors, errors=errors,
            warnings=[f"{no_std} items missing standard alignment"] if no_std else [],
            stats={
                "total": len(chunks),
                "with_publisher_std": with_std,
                "with_dok": with_dok,
                "missing_std": no_std,
            },
        )


def _parse_grade_label(label: str) -> int | None:
    """'Grade 3' → 3, 'High School' → 11, etc."""
    if "high school" in label.lower():
        return 11
    m = re.search(r"Grade\s+(\d+)", label, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None
