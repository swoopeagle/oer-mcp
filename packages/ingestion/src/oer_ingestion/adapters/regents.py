"""NY Regents adapter — released Regents high school math exams.

Source: https://www.nysedregents.org/{algebraone,geometryre,algebratwo}/
License: © NYSED, with blanket permission for educational reproduction — not CC.
         Partitioned into oer_state.db so deployments can exclude it.

Each administration (Jan/Jun/Aug) posts a PDF family:
  {slug}-{M}{YYYY}-exam.pdf   the exam itself (what we ingest)
  …-sk.pdf                    scoring key — MC answers, parsed into answer_key
  …-rg.pdf / -mrs.pdf / -cc.pdf  rating guide / model responses / conversion (skipped)
  …-examlt.pdf                large-type edition (skipped)

Exam structure (all three courses): Part I = 24 multiple-choice questions;
Parts II–IV = constructed response (25–35/37). Question text is extracted with
the font-aware Mathematical Pi remap (see _pdf.extract_pdf_text_mathpi) because
NYSED's PDFs carry wrong ToUnicode maps for math operators.

Chunk ID: "regents-{slug}-{M}{YYYY}-q{n}"
Book ID:  "regents-{course_id}"
DB:       oer_state.db
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from oer_shared.models import ContentChunk

from .base import RawContent, SourceAdapter, ValidationResult
from ._pdf import extract_pdf_text, extract_pdf_text_mathpi

LICENSE = "© NYSED — educational use permitted"
LICENSE_URL = "https://www.nysed.gov/copyright-information"

_BASE = "https://www.nysedregents.org"

COURSES = {
    "algebra-i": {
        "dir": "algebraone", "slug": "algone", "title": "Algebra I",
        "exam_series": "NY Regents Algebra I",
    },
    "geometry": {
        "dir": "geometryre", "slug": "geom", "title": "Geometry",
        "exam_series": "NY Regents Geometry",
    },
    "algebra-ii": {
        "dir": "algebratwo", "slug": "algtwo", "title": "Algebra II",
        "exam_series": "NY Regents Algebra II",
    },
}

_MONTH_NAMES = {1: "January", 6: "June", 8: "August"}

# Lines to drop from extracted exam text (margin notes, footers, headers).
_NOISE_RES = [
    re.compile(r"^Use this space for\s*$"),
    re.compile(r"^computations\.?\s*$"),
    re.compile(r"^Use this space for computations\.?\s*$"),
    re.compile(r"^\s*\[\s*\d+\s*\]\s*(\[OVER\])?\s*$"),
    re.compile(r"^\s*\[OVER\]\s*$"),
    re.compile(r"^(Algebra I|Geometry|Algebra II)\s*[–—-]\s*(Jan|June|Aug)", re.I),
    re.compile(r"^GO RIGHT ON TO THE NEXT PAGE", re.I),
]

# Scoring key rows: "Algebra I June '25 7 1 MC 2" → q7 answer choice (1)
_SK_ROW_RE = re.compile(
    r"(?:Algebra I{1,2}|Geometry)\s+\w+\.?\s+['’]?\d{2}\s+(\d{1,2})\s+(\d)\s+MC\s+\d"
)


def _parse_admin(code: str) -> tuple[int, int]:
    """'62025' → (6, 2025); '12026' → (1, 2026); '82024' → (8, 2024)."""
    return int(code[:-4]), int(code[-4:])


class RegentsAdapter(SourceAdapter):
    source_id = "nysed-regents"

    def __init__(self, courses: list[str] | None = None,
                 years: list[int] | None = None, *,
                 timeout: float = 60.0, max_exams: int | None = None):
        self.courses = courses or list(COURSES)
        self.years = years or list(range(2015, 2027))
        self.timeout = timeout
        self.max_exams = max_exams
        self._meta: dict[str, dict] = {}  # raw key → course/admin/sk answers

    def catalog(self) -> dict:
        return {
            "source": {
                "id": self.source_id,
                "full_name": "New York State Regents Examinations (Released)",
                "license": LICENSE, "license_url": LICENSE_URL,
                "base_url": _BASE,
            },
            "books": [
                {
                    "id": f"regents-{cid}",
                    "source_id": self.source_id,
                    "title": f"NY Regents {info['title']} — Released Exams",
                    "subject": "mathematics",
                    "grade_band": "9-12",
                    "license": LICENSE,
                    "url": f"{_BASE}/{info['dir']}/",
                }
                for cid, info in COURSES.items()
                if cid in self.courses
            ],
        }

    def fetch(self) -> list[RawContent]:
        now = datetime.now(timezone.utc).isoformat()
        raw: list[RawContent] = []
        with httpx.Client(timeout=self.timeout, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}) as client:
            for cid in self.courses:
                info = COURSES.get(cid)
                if not info:
                    continue
                index_url = f"{_BASE}/{info['dir']}/"
                try:
                    resp = client.get(index_url)
                except httpx.HTTPError as e:
                    print(f"[regents] {cid} index fetch failed: {e}")
                    continue
                if resp.status_code != 200:
                    print(f"[regents] {cid} index: HTTP {resp.status_code}")
                    continue

                # Filename drift across years: 2025+ 'algone-62025-exam.pdf',
                # 2016-24 'algone62024-exam.pdf', plus '-examp'/'-exama' variants.
                # Large-type editions (-examlt, -exam-lt, -ltexam) never match.
                exam_paths = re.findall(
                    rf'href="([^"]*{info["slug"]}-?(\d{{5}})-exam[ap]?\.pdf)"',
                    resp.text,
                )
                for rel_path, admin in exam_paths:
                    month, year = _parse_admin(admin)
                    if year not in self.years:
                        continue
                    exam_url = rel_path if rel_path.startswith("http") \
                        else f"{_BASE}/{info['dir']}/{rel_path}"
                    try:
                        pdf = client.get(exam_url)
                    except httpx.HTTPError as e:
                        print(f"[regents] {cid} {admin} exam fetch failed: {e}")
                        continue
                    if pdf.status_code != 200 or pdf.content[:4] != b"%PDF":
                        print(f"[regents] {cid} {admin}: bad exam response")
                        continue

                    # Companion scoring key (best-effort)
                    sk_answers: dict[int, str] = {}
                    sk_url = re.sub(r"-exam[ap]?\.pdf$", "-sk.pdf", exam_url)
                    try:
                        sk = client.get(sk_url)
                        if sk.status_code == 200 and sk.content[:4] == b"%PDF":
                            sk_answers = self._parse_scoring_key(sk.content)
                    except httpx.HTTPError:
                        pass

                    key = f"{info['slug']}-{admin}"
                    self._meta[key] = {
                        "course_id": cid, "info": info,
                        "month": month, "year": year,
                        "exam_url": exam_url, "sk_answers": sk_answers,
                    }
                    raw.append(RawContent(
                        source_id=self.source_id, key=key,
                        url=exam_url, fetched_at=now,
                        payload=pdf.content.decode("latin-1"),
                    ))
                    print(f"[regents] fetched {key} "
                          f"({len(pdf.content)//1024} KB, {len(sk_answers)} MC answers)")
                    if self.max_exams and len(raw) >= self.max_exams:
                        return raw
        return raw

    @staticmethod
    def _parse_scoring_key(sk_bytes: bytes) -> dict[int, str]:
        """Extract MC answers from a scoring-key PDF: {question_num: choice}."""
        try:
            text = extract_pdf_text(sk_bytes)
        except Exception:
            return {}
        return {int(q): a for q, a in _SK_ROW_RE.findall(text)}

    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        chunks: list[ContentChunk] = []
        for item in raw:
            meta = self._meta.get(item.key)
            if not meta:
                continue
            try:
                text = extract_pdf_text_mathpi(item.payload.encode("latin-1"))
            except Exception as e:
                print(f"[regents] {item.key} PDF parse failed: {e}")
                continue
            questions = _split_questions(text)
            info = meta["info"]
            month, year = meta["month"], meta["year"]
            admin_label = f"{_MONTH_NAMES.get(month, month)} {year}"
            sk = meta["sk_answers"]

            for q_num, q_text in questions:
                is_mc = q_num <= 24
                answer = None
                if is_mc and q_num in sk:
                    answer = f"({sk[q_num]})"
                chunks.append(ContentChunk(
                    id=f"regents-{item.key}-q{q_num}",
                    book_id=f"regents-{meta['course_id']}",
                    source_id=self.source_id,
                    title=f"NY Regents {info['title']} {admin_label} — Question {q_num}",
                    content=q_text,
                    content_type="assessment",
                    grade_band="9-12",
                    word_count=len(q_text.split()),
                    source_url=meta["exam_url"],
                    attribution=(
                        f"New York State Regents Examination, {info['title']}, "
                        f"{admin_label}, Question {q_num}. © NYSED; reproduced for "
                        f"educational purposes. nysedregents.org"
                    ),
                    item_type="multiple_choice" if is_mc else "constructed_response",
                    dok_level=None,
                    answer_key=answer,
                    exam_series=info["exam_series"],
                    exam_year=year,
                    difficulty=None,
                    item_generation="released",
                ))
        return chunks

    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        errors = [f"{c.id}: empty content" for c in chunks if not c.content.strip()]
        if not chunks:
            errors.append("no chunks produced — verify nysedregents.org fetch")
        mc = sum(1 for c in chunks if c.item_type == "multiple_choice")
        with_answer = sum(1 for c in chunks if c.answer_key)
        by_series: dict[str, int] = {}
        for c in chunks:
            by_series[c.exam_series or "?"] = by_series.get(c.exam_series or "?", 0) + 1
        return ValidationResult(
            ok=not errors, errors=errors,
            warnings=([f"{mc - with_answer} MC items missing answer key"]
                      if mc - with_answer > 0 else []),
            stats={"total": len(chunks), "multiple_choice": mc,
                   "mc_with_answer": with_answer, **by_series},
        )


_Q_START_RE = re.compile(r"^\s{0,2}(\d{1,2})\s+(?=[A-Z(“\"])")
_PART_RE = re.compile(r"^Part\s+(I{1,3}V?|IV)\b")


def _split_questions(text: str) -> list[tuple[int, str]]:
    """Split extracted exam text into (question_number, question_text) pairs.

    Question starts are lines beginning with the next expected number — the
    monotonic sequence requirement rejects axis labels, table rows, and the
    reference sheet, which also start with digits.
    """
    lines = [ln for ln in text.split("\n")
             if not any(rx.match(ln) for rx in _NOISE_RES)]
    out: list[tuple[int, str]] = []
    cur_num = 0
    cur: list[str] = []
    for ln in lines:
        m = _Q_START_RE.match(ln)
        if m and int(m.group(1)) == cur_num + 1:
            if cur_num > 0:
                out.append((cur_num, "\n".join(cur).strip()))
            cur_num += 1
            cur = [ln.strip()]
        elif cur_num > 0:
            # Reference sheet / credits follow the last question; a "Part" header
            # between questions is kept out of the question body.
            if _PART_RE.match(ln.strip()):
                continue
            cur.append(ln.rstrip())
    if cur_num > 0:
        out.append((cur_num, "\n".join(cur).strip()))

    # Trim trailing reference-sheet noise on the final question: it follows the
    # "Tear Here" markers / "High School Math Reference Sheet" line.
    if out:
        n, t = out[-1]
        for marker in ("High School Math Reference Sheet", "Tear Here"):
            idx = t.find(marker)
            if idx > 0:
                t = t[:idx].rstrip()
        out[-1] = (n, t)

    # Drop fragments too short to be a real question.
    return [(n, t) for n, t in out if len(t.split()) >= 8]
