"""OpenStax adapter — CNXML source from github.com/openstax/osbooks-* repos.

Route verified in docs/spikes/S1-openstax-route.md:
  META-INF/books.xml → collections/{slug}.collection.xml → modules/{id}/index.cnxml

A module = one textbook section (e.g. "4.2 Visualize Fractions"). Its <content>
holds: optional `note[be-prepared]` prereq checks, several content <section>
subsections (prose + <example> worked examples), a `section[key-concepts]`
summary, and a `section[section-exercises]` block of grouped <exercise>s.

The splitter emits typed sub-chunks (D14) sharing the module ID prefix:
  -expo{n}   one per content subsection (prose, examples lifted out)
  -ex{n}     one per <example> (worked problem + solution)
  -summary   the key-concepts section
  -set{n}    one per labeled exercise group (Practice Makes Perfect, etc.)

License is read per-book from collection.xml md:license (2e = CC BY-NC-SA,
1e = CC BY — never assumed per source, S1).
"""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from lxml import etree

from oer_shared.models import ContentChunk, ContentType

from ..cnxml import NS, element_text, word_count
from .base import RawContent, SourceAdapter, ValidationResult

COL = "http://cnx.rice.edu/collxml"
MD = "http://cnx.rice.edu/mdml"
BC = "https://openstax.org/namespaces/book-container"
ALLNS = {**NS, "col": COL, "md": MD, "bc": BC}

CODELOAD = "https://codeload.github.com/openstax/{repo}/tar.gz/refs/heads/main"
PAGE_URL = "https://openstax.org/books/{slug}/pages/{page}"

_LICENSE_NAMES = {
    "by": "CC BY 4.0",
    "by-nc-sa": "CC BY-NC-SA 4.0",
    "by-nc-nd": "CC BY-NC-ND 4.0",
    "by-sa": "CC BY-SA 4.0",
}

# Per-discipline CNXML section @class conventions (verified against actual
# modules — math and social-studies books use different class names for the
# same structural roles, and social-studies exercise groups aren't nested
# inside a container the way math's "section-exercises" subsections are).
@dataclass
class ClassProfile:
    summary_class: str
    nested_exercise_class: str | None  # container whose <section> children get split out
    flat_exercise_classes: tuple[str, ...]  # standalone exercise-like sections

CLASS_PROFILES = {
    "math": ClassProfile("key-concepts", "section-exercises", ()),
    # Government, US History, Psychology, Economics — verified against actual modules.
    "social-studies": ClassProfile(
        "summary", None,
        ("review-questions", "critical-thinking", "problems", "self-check-questions"),
    ),
    # Sociology, World History — same structural roles, different class names.
    "social-studies-section": ClassProfile(
        "section-summary", None,
        ("review-questions", "critical-thinking", "check-understanding",
         "reflection-questions", "own-words", "section-quiz", "short-answer"),
    ),
}


def _q(elem) -> str:
    return etree.QName(elem).localname


@dataclass
class BookSpec:
    """One OpenStax book within a bundle repo."""

    repo: str  # "osbooks-prealgebra-bundle"
    slug: str  # "prealgebra-2e"
    grade_band: str | None = None
    subject: str = "mathematics"
    # CNXML uses different section @class names per discipline (math: "key-concepts"
    # / "section-exercises" nested groups; social studies: flat "summary" /
    # "review-questions" / "critical-thinking" sections). See ClassProfile below.
    class_profile: str = "math"


@dataclass
class _ModulePlace:
    """Where a module sits in the book tree — resolved from collection.xml."""

    module_id: str
    chapter_num: str | None
    chapter_title: str | None
    section_num: str | None  # section index within chapter
    book_title: str = ""
    license: str = ""


@dataclass
class _BookTree:
    slug: str
    title: str
    license: str
    subject: str = "mathematics"
    class_profile: str = "math"
    places: dict[str, _ModulePlace] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)


class OpenStaxAdapter(SourceAdapter):
    source_id = "openstax"

    def __init__(self, books: list[BookSpec], *, timeout: float = 60.0):
        self.books = books
        self.timeout = timeout
        self._trees: dict[str, _BookTree] = {}  # slug → tree
        self._module_cnxml: dict[str, str] = {}  # module_id → raw cnxml

    # ── Stage 1: fetch ────────────────────────────────────────────────────────
    def fetch(self) -> list[RawContent]:
        now = datetime.now(timezone.utc).isoformat()
        raw: list[RawContent] = []
        repos = {b.repo for b in self.books}
        repo_blobs = {repo: self._download_repo(repo) for repo in repos}

        for spec in self.books:
            members = repo_blobs[spec.repo]
            tree = self._parse_collection(members, spec)
            self._trees[spec.slug] = tree
            for mid in tree.order:
                cnxml = members.get(f"modules/{mid}/index.cnxml")
                if cnxml is None:
                    continue
                self._module_cnxml[mid] = cnxml
                raw.append(
                    RawContent(
                        source_id=self.source_id,
                        key=f"{spec.slug}:{mid}",
                        url=PAGE_URL.format(slug=spec.slug, page=mid),
                        fetched_at=now,
                        payload=cnxml,
                    )
                )
        return raw

    def _download_repo(self, repo: str) -> dict[str, str]:
        """Download a bundle repo tarball once; return {relpath: text}."""
        url = CODELOAD.format(repo=repo)
        resp = httpx.get(url, timeout=self.timeout, follow_redirects=True)
        resp.raise_for_status()
        members: dict[str, str] = {}
        with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tf:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                rel = m.name.split("/", 1)[1] if "/" in m.name else m.name
                if rel.startswith(("META-INF/", "collections/")) or (
                    rel.startswith("modules/") and rel.endswith("index.cnxml")
                ):
                    f = tf.extractfile(m)
                    if f is not None:
                        members[rel] = f.read().decode("utf-8")
        return members

    def _parse_collection(self, members: dict[str, str], spec: BookSpec) -> _BookTree:
        container = etree.fromstring(members["META-INF/books.xml"].encode())
        href = None
        for book in container.findall(f"{{{BC}}}book"):
            if book.get("slug") == spec.slug:
                href = book.get("href")
                break
        if href is None:
            raise ValueError(f"book slug {spec.slug!r} not in {spec.repo} books.xml")
        col_path = href.replace("../", "")
        col = etree.fromstring(members[col_path].encode())

        title_el = col.find(f".//{{{MD}}}title")
        lic_el = col.find(f".//{{{MD}}}license")
        lic_url = lic_el.get("url", "") if lic_el is not None else ""
        lic = _LICENSE_NAMES.get(_license_code(lic_url), lic_url)
        tree = _BookTree(
            slug=spec.slug,
            title=(title_el.text if title_el is not None else spec.slug),
            license=lic,
            subject=spec.subject,
            class_profile=spec.class_profile,
        )

        content = col.find(f"{{{COL}}}content")
        chapter_idx = 0
        for sub in content.findall(f"{{{COL}}}subcollection"):
            chapter_idx += 1
            ch_title_el = sub.find(f"{{{MD}}}title")
            ch_title = ch_title_el.text if ch_title_el is not None else None
            sec_idx = 0
            for mod in sub.findall(f".//{{{COL}}}module"):
                sec_idx += 1
                mid = mod.get("document")
                tree.places[mid] = _ModulePlace(
                    module_id=mid,
                    chapter_num=str(chapter_idx),
                    chapter_title=ch_title,
                    section_num=str(sec_idx),
                    book_title=tree.title,
                    license=tree.license,
                )
                tree.order.append(mid)
        # front-matter modules directly under content (preface etc.) — index 0
        for mod in content.findall(f"{{{COL}}}module"):
            mid = mod.get("document")
            tree.places.setdefault(
                mid,
                _ModulePlace(mid, None, None, None, tree.title, tree.license),
            )
            tree.order.append(mid)
        return tree

    def catalog(self) -> dict:
        """Source + book metadata for the loader (call after fetch()).

        OpenStax licenses are per-book (S1), so book rows carry their own
        license; the source row records the predominant/default license.
        """
        books = []
        for spec in self.books:
            tree = self._trees[spec.slug]
            books.append(
                {
                    "id": f"openstax-{spec.slug}",
                    "source_id": self.source_id,
                    "title": tree.title,
                    "subject": tree.subject,
                    "grade_band": spec.grade_band,
                    "license": tree.license,
                    "url": f"https://openstax.org/details/books/{spec.slug}",
                }
            )
        return {
            "source": {
                "id": self.source_id,
                "full_name": "OpenStax",
                "license": books[0]["license"] if books else "CC BY-NC-SA 4.0",
                "license_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
                "base_url": "https://openstax.org",
            },
            "books": books,
        }

    # ── Stage 2: parse → typed sub-chunks (D14) ───────────────────────────────
    def parse(self, raw: list[RawContent]) -> list[ContentChunk]:
        chunks: list[ContentChunk] = []
        for item in raw:
            slug, mid = item.key.split(":", 1)
            tree = self._trees[slug]
            place = tree.places.get(mid)
            if place is None or place.chapter_num is None:
                continue  # skip front matter / unplaced modules in v1
            profile = CLASS_PROFILES[tree.class_profile]
            chunks.extend(self._split_module(slug, mid, item.payload, place, item.url, profile))
        return chunks

    def _split_module(
        self, slug: str, mid: str, cnxml: str, place: _ModulePlace, url: str,
        profile: ClassProfile,
    ) -> list[ContentChunk]:
        doc = etree.fromstring(cnxml.encode())
        content = doc.find("c:content", NS)
        title_el = doc.find("c:title", NS)
        mod_title = (title_el.text or "").strip() if title_el is not None else mid
        if content is None:
            return []

        out: list[ContentChunk] = []
        prefix = f"openstax-{slug}-{mid}"
        ch, sec = place.chapter_num, place.section_num
        sec_label = f"{ch}.{sec}" if ch and sec else (ch or "")

        def mk(suffix: str, title: str, body: str, ctype: ContentType):
            body = body.strip()
            if not body:
                return
            out.append(
                ContentChunk(
                    id=f"{prefix}-{suffix}",
                    book_id=f"openstax-{slug}",
                    source_id=self.source_id,
                    title=title,
                    content=body,
                    content_type=ctype,
                    chapter=ch,
                    section=sec,
                    grade_band=None,  # set per book at load time
                    word_count=word_count(body),
                    source_url=url,
                    attribution=(
                        f"OpenStax {place.book_title}, "
                        f"{('Section ' + sec_label + ': ') if sec_label else ''}"
                        f"{mod_title}, {place.license}"
                    ),
                )
            )

        expo_n = ex_n = set_n = 0
        for section in content.findall("c:section", NS):
            cls = section.get("class")
            stitle_el = section.find("c:title", NS)
            stitle = (stitle_el.text or "").strip() if stitle_el is not None else ""

            if cls == profile.summary_class:
                mk("summary", f"{mod_title} — Key Concepts",
                   element_text(section), "summary")
                continue
            if profile.nested_exercise_class and cls == profile.nested_exercise_class:
                for grp in section.findall("c:section", NS):
                    set_n += 1
                    gt_el = grp.find("c:title", NS)
                    gt = (gt_el.text or "").strip() if gt_el is not None else "Exercises"
                    mk(f"set{set_n}", f"{mod_title} — {gt}",
                       element_text(grp), "exercise_set")
                continue
            if cls in profile.flat_exercise_classes:
                set_n += 1
                mk(f"set{set_n}", f"{mod_title} — {stitle or cls.replace('-', ' ').title()}",
                   element_text(section), "exercise_set")
                continue

            # content subsection: lift <example>s out as worked_example chunks,
            # keep the remaining prose as one exposition chunk.
            examples = section.findall("c:example", NS)
            for exmpl in examples:
                ex_n += 1
                mk(f"ex{ex_n}", f"{mod_title} — Example {ex_n}",
                   element_text(exmpl), "worked_example")
                exmpl.getparent().remove(exmpl)
            expo_n += 1
            etitle = f"{mod_title}: {stitle}" if stitle else mod_title
            mk(f"expo{expo_n}", etitle, element_text(section), "exposition")

        return out

    # ── Stage validation ──────────────────────────────────────────────────────
    def validate(self, chunks: list[ContentChunk]) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        by_type: dict[str, int] = {}
        for c in chunks:
            by_type[c.content_type] = by_type.get(c.content_type, 0) + 1
            if not c.attribution:
                errors.append(f"{c.id}: empty attribution")
            if not c.content.strip():
                errors.append(f"{c.id}: empty content")
        if not chunks:
            errors.append("no chunks produced")
        if by_type.get("exposition", 0) == 0:
            warnings.append("no exposition chunks — splitter may be misparsing")
        return ValidationResult(
            ok=not errors,
            errors=errors,
            warnings=warnings,
            stats={"total": len(chunks), **by_type},
        )


def _license_code(url: str) -> str:
    # ".../licenses/by-nc-sa/4.0/" → "by-nc-sa"
    parts = [p for p in url.split("/") if p]
    for i, p in enumerate(parts):
        if p == "licenses" and i + 1 < len(parts):
            return parts[i + 1]
    return ""
