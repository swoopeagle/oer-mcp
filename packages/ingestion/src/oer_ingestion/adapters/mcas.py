"""MCAS adapter — Massachusetts released MCAS math items (Cognia Item Library).

Source: https://mcas.cognia.org/item-catalog/
License: © Massachusetts DESE. DESE grants permission to copy for non-commercial
         educational purposes → partitioned into oer_state.db alongside NY Regents.

Endpoints (eMetric/Cognia item catalog, verified 2026-07; sessionless JSON):
  GET /item-catalog/items?Subject=Math&Grade={g}&page={n}   catalog, 10/page
  GET /item-catalog/items/{ItemID}                          full item

Each item carries publisher standards in MA-framework notation ('7.NS.A.2' —
CCSS-derived) plus full Lighthouse item content: question prompts are URL-encoded
HTML/MathML in `prompt` fields, answer choices in `distractors[].content`, and the
correct choice id in `ScoringRubric.ScoreGroups[].RubricStates[]`.

Chunk ID: "mcas-gr{grade}-{ItemID}"
Book ID:  "mcas-math-gr{grade}"
DB:       oer_state.db
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from datetime import datetime, timezone

import httpx

from oer_shared.models import ContentChunk, StandardAlignment

from .base import RawContent, SourceAdapter, ValidationResult

LICENSE = "© Massachusetts DESE — non-commercial educational use permitted"
LICENSE_URL = "https://www.doe.mass.edu/mcas/"

_BASE = "https://mcas.cognia.org/item-catalog"

GRADES = ["3", "4", "5", "6", "7", "8", "10"]
_GRADE_BAND = {
    "3": "K-5", "4": "K-5", "5": "K-5",
    "6": "6-8", "7": "6-8", "8": "6-8",
    "10": "9-12",
}

_ITEM_TYPE_MAP = {
    "sr": "multiple_choice",
    "cr": "constructed_response",
    "sa": "constructed_response",
    "es": "constructed_response",
}

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
}

_TAG_RE = re.compile(r"<[^>]+>")


def _decode_html(encoded: str) -> str:
    """URL-encoded Lighthouse HTML/MathML fragment → plain text."""
    text = _TAG_RE.sub(" ", urllib.parse.unquote(encoded))
    return re.sub(r"\s+", " ", text).strip()


def _extract_content(item_content_json: str) -> tuple[str, list[tuple[str, str]]]:
    """Walk the Lighthouse content tree → (prompt_text, [(choice_id, choice_text)]).

    Prompts are `prompt` fields anywhere in the tree (STYLE nodes never carry
    them); choices are `distractors` lists with per-choice `id` and `content`.
    """
    try:
        tree = json.loads(item_content_json)
    except (ValueError, TypeError):
        return "", []
    prompts: list[str] = []
    choices: list[tuple[str, str]] = []

    def walk(node):
        if isinstance(node, dict):
            for key in ("prompt", "html"):
                p = node.get(key)
                if isinstance(p, str) and p and node.get("tag") != "STYLE":
                    t = _decode_html(p)
                    if t and len(t) > 2:
                        prompts.append(t)
            d = node.get("distractors")
            if isinstance(d, list):
                for opt in d:
                    if isinstance(opt, dict) and opt.get("content"):
                        cid = str(opt.get("letter") or opt.get("id") or "")
                        choices.append((cid, _decode_html(str(opt["content"]))))
            for v in node.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(tree)
    return "\n\n".join(dict.fromkeys(prompts)), choices


def _answer_from_rubric(rubric_json, choices: list[tuple[str, str]]) -> str | None:
    """ScoringRubric → answer text. MC: match RubricStates id against choices."""
    if not rubric_json:
        return None
    try:
        rubric = json.loads(rubric_json) if isinstance(rubric_json, str) else rubric_json
    except (ValueError, TypeError):
        return None
    guide = (rubric.get("HumanScoringGuide") or "").strip()
    ids: list[str] = []
    for sg in rubric.get("ScoreGroups", []):
        for rs in sg.get("RubricStates", []):
            rid = rs.get("id") or rs.get("val")
            if rid:
                ids.append(str(rid))
    if ids:
        by_id = dict(choices)
        parts = [f"({i}) {by_id[i]}" if i in by_id else f"({i})" for i in ids]
        return "Correct: " + "; ".join(parts)
    if guide:
        return _TAG_RE.sub(" ", guide)[:500].strip()
    return None


def _ccss_id(ma_name: str) -> str | None:
    """MA framework standard name → StandardGraph CCSS ID (best effort).

    '7.NS.A.2' → CCSS.MATH.7.NS.2 (6-8 drop cluster letter)
    '3.MD.A.1' → CCSS.MATH.3.MD.A.1 (K-5 keep)
    'G-SRT.B.5' / 'A1.A-REI.A.1' → CCSS.MATH.HSG.SRT.B.5 (HS; course prefix dropped)
    """
    name = ma_name.strip()
    if not name:
        return None
    # Drop MA HS course prefixes like 'A1.', 'G.', 'M1.' before a letter-hyphen domain
    m = re.match(r"^(?:[A-Z]{1,2}\d?\.)?([A-Z])-([A-Z]{1,4})\.(.+)$", name)
    if m:
        return f"CCSS.MATH.HS{m.group(1)}.{m.group(2)}.{m.group(3)}"
    m = re.match(r"^([K1-9]|1[0-2])\.([A-Z]{1,4})\.([A-Z])\.(\d+[a-z]?)$", name)
    if m:
        grade, domain, cluster, leaf = m.groups()
        try:
            g = 0 if grade == "K" else int(grade)
        except ValueError:
            return None
        if g <= 5:
            return f"CCSS.MATH.{grade}.{domain}.{cluster}.{leaf}"
        return f"CCSS.MATH.{grade}.{domain}.{leaf}"
    m = re.match(r"^([K1-9]|1[0-2])\.([A-Z]{1,4})\.(\d+[a-z]?)$", name)
    if m:
        return f"CCSS.MATH.{m.group(1)}.{m.group(2)}.{m.group(3)}"
    return None


class MCASAdapter(SourceAdapter):
    source_id = "mcas"

    def __init__(self, grades: list[str] | None = None, *,
                 timeout: float = 30.0, max_items: int | None = None,
                 delay: float = 0.15):
        self.grades = [str(g) for g in (grades or GRADES)]
        self.timeout = timeout
        self.max_items = max_items
        self.delay = delay
        self._meta: dict[str, dict] = {}

    def catalog(self) -> dict:
        return {
            "source": {
                "id": self.source_id,
                "full_name": "MCAS Released Items (Massachusetts DESE)",
                "license": LICENSE, "license_url": LICENSE_URL,
                "base_url": _BASE,
            },
            "books": [
                {
                    "id": f"mcas-math-gr{g}",
                    "source_id": self.source_id,
                    "title": f"MCAS Mathematics — Grade {g} Released Items",
                    "subject": "mathematics",
                    "grade_band": _GRADE_BAND[g],
                    "license": LICENSE,
                    "url": f"{_BASE}/?Subject=Math&Grade={g}",
                }
                for g in self.grades
            ],
        }

    def fetch(self) -> list[RawContent]:
        now = datetime.now(timezone.utc).isoformat()
        raw: list[RawContent] = []
        with httpx.Client(timeout=self.timeout, headers=_HEADERS) as client:
            for grade in self.grades:
                page = 1
                while True:
                    try:
                        r = client.get(f"{_BASE}/items", params={
                            "Subject": "Math", "Grade": grade, "page": page,
                        })
                        r.raise_for_status()
                        data = r.json()
                    except (httpx.HTTPError, ValueError) as e:
                        print(f"[mcas] grade {grade} page {page}: {e}")
                        break
                    items = data.get("items", [])
                    if not items:
                        break
                    for entry in items:
                        item_id = entry.get("ItemID")
                        if not item_id or item_id in self._meta:
                            continue
                        try:
                            d = client.get(f"{_BASE}/items/{item_id}")
                            detail = d.json() if d.status_code == 200 else entry
                        except (httpx.HTTPError, ValueError):
                            detail = entry
                        detail["_grade"] = grade
                        self._meta[item_id] = detail
                        raw.append(RawContent(
                            source_id=self.source_id, key=item_id,
                            url=f"{_BASE}/?itemID={item_id}&Subject=Math&Grade={grade}",
                            fetched_at=now, payload="",
                        ))
                        if self.max_items and len(raw) >= self.max_items:
                            return raw
                        if self.delay:
                            time.sleep(self.delay)
                    total = data.get("totalItems", 0)
                    if page * 10 >= total:
                        break
                    page += 1
                print(f"[mcas] grade {grade}: {sum(1 for m in self._meta.values() if m.get('_grade') == grade)} items")
        return raw

    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        chunks: list[ContentChunk] = []
        for rc in raw:
            meta = self._meta.get(rc.key)
            if not meta:
                continue
            grade = meta.get("_grade", "?")
            year = meta.get("Year")
            desc = meta.get("Description") or ""
            category = meta.get("ReportingCategory") or ""
            raw_type = (meta.get("ItemType") or "").lower()
            item_type = _ITEM_TYPE_MAP.get(raw_type, "constructed_response")

            prompt, choices = _extract_content(meta.get("ItemContent") or "")
            body = prompt
            if choices:
                body += "\n" + "\n".join(f"({cid}) {ct}" for cid, ct in choices)
            if not body.strip() or len(body.split()) < 5:
                body = desc
            if not body.strip():
                continue
            if desc and desc not in body:
                body = f"{desc}\n\n{body}"
            if category:
                body += f"\n\nReporting category: {category}"

            answer = _answer_from_rubric(meta.get("ScoringRubric"), choices)

            aligns = []
            for std in meta.get("Standards") or []:
                name = std.get("Name") or ""
                cid = _ccss_id(name)
                if cid:
                    aligns.append(StandardAlignment(
                        standard_id=cid, standard_system="ccss",
                        alignment_score=0.95, alignment_source="publisher_guide",
                        coverage_notes=(
                            f"MCAS item {rc.key} tagged by MA DESE to framework "
                            f"standard {name}."
                        ),
                    ))

            attribution = (
                f"Massachusetts Comprehensive Assessment System (MCAS), "
                f"Mathematics Grade {grade}, {year}, Item {meta.get('ItemNumber', '?')} "
                f"({rc.key}). © Massachusetts DESE; reproduced for non-commercial "
                f"educational purposes. mcas.cognia.org"
            )
            chunks.append(ContentChunk(
                id=f"mcas-gr{grade}-{rc.key}",
                book_id=f"mcas-math-gr{grade}",
                source_id=self.source_id,
                title=f"MCAS Grade {grade} ({year}): {desc[:80]}",
                content=body,
                content_type="assessment",
                grade_band=_GRADE_BAND.get(grade, "9-12"),
                word_count=len(body.split()),
                source_url=rc.url,
                attribution=attribution,
                standard_alignments=aligns,
                item_type=item_type,
                dok_level=None,
                answer_key=answer,
                exam_series=f"MCAS Grade {grade}",
                exam_year=year,
                difficulty=None,
                item_generation="released",
            ))
        return chunks

    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        errors = [f"{c.id}: empty content" for c in chunks if not c.content.strip()]
        if not chunks:
            errors.append("no chunks produced — verify mcas.cognia.org API")
        with_std = sum(1 for c in chunks if c.standard_alignments)
        with_answer = sum(1 for c in chunks if c.answer_key)
        return ValidationResult(
            ok=not errors, errors=errors,
            warnings=[f"{len(chunks) - with_std} items without standard alignment"]
            if len(chunks) - with_std else [],
            stats={
                "total": len(chunks),
                "with_publisher_std": with_std,
                "with_answer": with_answer,
            },
        )
