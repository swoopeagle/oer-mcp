"""AP Free-Response Questions adapter.

Source: College Board AP Students site
  https://apstudents.collegeboard.org/courses/{subject}/free-response-questions-by-year

License: © College Board. Educational use. Partitioned into oer_ap.db — not the
  core or NC-SA databases — so deployments can opt out cleanly. Attribution is
  surfaced in every response; do not reproduce without attribution.

Covers: AP Calculus AB, AP Calculus BC, AP Statistics, AP Precalculus.
  FRQs are posted as PDFs. This adapter fetches the year-index HTML to discover
  PDF URLs, then downloads each PDF and extracts text via pypdf.

Dependency: pip install pypdf (not in pyproject.toml by default — ingestion only,
  run `uv add pypdf --group dev` before running this adapter).

Chunk ID: "ap-{subject_slug}-{year}-q{n}"
Book ID:  "ap-{subject_slug}-frq"
DB:       oer_ap.db (College Board copyright — educational use)
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone

import httpx

from oer_shared.models import ContentChunk

from .base import RawContent, SourceAdapter, ValidationResult

LICENSE = "© College Board — Educational Use"
LICENSE_URL = "https://apstudents.collegeboard.org/"

_BASE = "https://apstudents.collegeboard.org"
# Year range to ingest. College Board typically posts 10+ years of FRQs.
_YEARS = list(range(2015, 2025))

AP_SUBJECTS = {
    "ap-calculus-ab": {
        "slug": "calculus-ab",
        "title": "AP Calculus AB",
        "grade_band": "9-12",
        "exam_series": "AP Calculus AB",
    },
    "ap-calculus-bc": {
        "slug": "calculus-bc",
        "title": "AP Calculus BC",
        "grade_band": "9-12",
        "exam_series": "AP Calculus BC",
    },
    "ap-statistics": {
        "slug": "statistics",
        "title": "AP Statistics",
        "grade_band": "9-12",
        "exam_series": "AP Statistics",
    },
    "ap-precalculus": {
        "slug": "precalculus",
        "title": "AP Precalculus",
        "grade_band": "9-12",
        "exam_series": "AP Precalculus",
    },
}

_PDF_LINK_RE = re.compile(
    r'href="([^"]+(?:frq|free.response)[^"]*\.pdf)"',
    re.IGNORECASE,
)
_QUESTION_SPLIT_RE = re.compile(r"\n(?=(?:Question|Problem)\s+\d+\b)", re.IGNORECASE)


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract plain text from a PDF. Requires pypdf."""
    try:
        import pypdf  # type: ignore
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for page in reader.pages:
            t = page.extract_text() or ""
            parts.append(t)
        return "\n".join(parts)
    except ImportError:
        raise RuntimeError(
            "pypdf is required for AP FRQ ingestion. "
            "Run: uv add pypdf --group dev"
        )


def _split_questions(full_text: str, year: int, subject_slug: str) -> list[dict]:
    """Split a multi-question FRQ PDF into per-question chunks."""
    parts = _QUESTION_SPLIT_RE.split(full_text)
    out = []
    for i, part in enumerate(parts):
        part = part.strip()
        if len(part.split()) < 20:
            continue
        # First part may be cover page — skip if it lacks question content
        if i == 0 and not re.search(r"\d+\s*points?", part, re.IGNORECASE):
            continue
        q_num = i if i > 0 else 1
        # Attempt to read question number from text
        m = re.match(r"(?:Question|Problem)\s+(\d+)", part, re.IGNORECASE)
        if m:
            q_num = int(m.group(1))
        out.append({"q_num": q_num, "text": part})
    return out


class APFRQAdapter(SourceAdapter):
    source_id = "ap-frq"

    def __init__(
        self,
        subjects: list[str] | None = None,
        years: list[int] | None = None,
        *,
        timeout: float = 60.0,
        max_questions: int | None = None,
    ):
        self.subjects = subjects or list(AP_SUBJECTS)
        self.years = years or _YEARS
        self.timeout = timeout
        self.max_questions = max_questions
        self._meta: dict[str, dict] = {}  # key → {subject, year, q_num, pdf_url}

    def catalog(self) -> dict:
        return {
            "source": {
                "id": self.source_id,
                "full_name": "AP Free-Response Questions (College Board)",
                "license": LICENSE,
                "license_url": LICENSE_URL,
                "base_url": _BASE,
            },
            "books": [
                {
                    "id": f"ap-{sid}-frq",
                    "source_id": self.source_id,
                    "title": f"{info['title']} Free-Response Questions",
                    "subject": "mathematics",
                    "grade_band": info["grade_band"],
                    "license": LICENSE,
                    "url": f"{_BASE}/courses/{info['slug']}/free-response-questions-by-year",
                }
                for sid, info in AP_SUBJECTS.items()
                if sid in self.subjects
            ],
        }

    def fetch(self) -> list[RawContent]:
        now = datetime.now(timezone.utc).isoformat()
        raw: list[RawContent] = []
        with httpx.Client(timeout=self.timeout,
                          headers={"User-Agent": "oer-mcp/0.1 (educator tool)",
                                   "Accept": "text/html,application/pdf"}) as client:
            for sid in self.subjects:
                info = AP_SUBJECTS.get(sid)
                if not info:
                    continue
                index_url = f"{_BASE}/courses/{info['slug']}/free-response-questions-by-year"
                try:
                    resp = client.get(index_url, follow_redirects=True)
                except httpx.HTTPError as e:
                    print(f"[ap-frq] {sid} index fetch failed: {e}")
                    continue
                if resp.status_code != 200:
                    print(f"[ap-frq] {sid} index: HTTP {resp.status_code}")
                    continue

                # Find PDF links on the index page
                pdf_urls = _PDF_LINK_RE.findall(resp.text)
                for pdf_path in pdf_urls:
                    # Filter to years we want
                    year_match = re.search(r"(20\d{2})", pdf_path)
                    if not year_match:
                        continue
                    year = int(year_match.group(1))
                    if year not in self.years:
                        continue
                    pdf_url = pdf_path if pdf_path.startswith("http") else _BASE + pdf_path
                    try:
                        pdf_resp = client.get(pdf_url, follow_redirects=True)
                    except httpx.HTTPError as e:
                        print(f"[ap-frq] {sid} {year} PDF fetch failed: {e}")
                        continue
                    if pdf_resp.status_code != 200:
                        continue
                    key = f"{sid}-{year}"
                    self._meta[key] = {
                        "subject_id": sid,
                        "subject_info": info,
                        "year": year,
                        "pdf_url": pdf_url,
                    }
                    raw.append(RawContent(
                        source_id=self.source_id,
                        key=key,
                        url=pdf_url,
                        fetched_at=now,
                        payload=pdf_resp.content.decode("latin-1"),  # PDF binary as latin-1
                    ))
                    if self.max_questions and len(raw) >= self.max_questions:
                        return raw
        return raw

    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        chunks: list[ContentChunk] = []
        for item in raw:
            meta = self._meta.get(item.key)
            if not meta:
                continue
            sid = meta["subject_id"]
            info = meta["subject_info"]
            year = meta["year"]
            pdf_url = meta["pdf_url"]

            try:
                pdf_bytes = item.payload.encode("latin-1")
                full_text = _extract_pdf_text(pdf_bytes)
            except Exception as e:
                print(f"[ap-frq] {item.key} PDF parse failed: {e}")
                continue

            questions = _split_questions(full_text, year, sid)
            for q in questions:
                text = q["text"]
                q_num = q["q_num"]
                chunk_id = f"ap-{sid}-{year}-q{q_num}"
                title = f"{info['title']} {year} Free-Response Question {q_num}"
                attribution = (
                    f"{info['title']} {year} Free-Response Questions. "
                    f"© {year} College Board. Used for educational purposes. "
                    f"apstudents.collegeboard.org"
                )
                chunks.append(ContentChunk(
                    id=chunk_id,
                    book_id=f"ap-{sid}-frq",
                    source_id=self.source_id,
                    title=title,
                    content=text,
                    content_type="assessment",
                    grade_band=info["grade_band"],
                    word_count=len(text.split()),
                    source_url=pdf_url,
                    attribution=attribution,
                    item_type="constructed_response",  # AP FRQs are always CR
                    dok_level=3,  # AP FRQs are consistently DOK 3-4
                    answer_key=None,  # scoring guidelines posted separately; not ingested
                    exam_series=info["exam_series"],
                    exam_year=year,
                    difficulty=None,  # no national % correct for AP FRQs
                    item_generation="released",
                ))
        return chunks

    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        errors = [f"{c.id}: empty content" for c in chunks if not c.content.strip()]
        if not chunks:
            errors.append(
                "no chunks produced — verify PDF fetch (pypdf installed?), "
                "URL patterns on apstudents.collegeboard.org may have changed"
            )
        by_subject: dict[str, int] = {}
        for c in chunks:
            by_subject[c.exam_series or "?"] = by_subject.get(c.exam_series or "?", 0) + 1
        return ValidationResult(
            ok=not errors, errors=errors, warnings=[],
            stats={"total": len(chunks), **by_subject},
        )
