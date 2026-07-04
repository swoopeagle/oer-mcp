"""Shared PDF text extraction for assessment adapters.

Two extractors:
  extract_pdf_text        — fast pypdf path (AP FRQ; PDFs with correct ToUnicode maps)
  extract_pdf_text_mathpi — pdfminer.six font-aware path for NYSED Regents exams,
                            whose Mathematical Pi fonts carry *wrong* ToUnicode
                            maps ('+' extracts as '1', '−' as '2', '=' as '5', …).
                            Characters are remapped per (font, glyph) so equations
                            come out readable; unmapped glyphs pass through.

Both need ingestion-only deps: `uv add pypdf pdfminer.six --package oer-ingestion --dev`.
"""

from __future__ import annotations

import io

# (font-name substring after the subset prefix, extracted char) → real char.
# Built empirically from 2025 Algebra I / Geometry / Algebra II exams — the
# Mathematical Pi LT Std family maps operators onto digit code points.
_MATHPI_REMAP: dict[tuple[str, str], str] = {
    ("MathematicalPiLTStd-1", "1"): "+",
    ("MathematicalPiLTStd-1", "2"): "−",
    ("MathematicalPiLTStd-1", "5"): "=",
    ("MathematicalPiLTStd-1", "#"): "≤",
    ("MathematicalPiLTStd-1", ","): "<",
    ("MathematicalPiLTStd-1", "."): ">",
    ("MathematicalPiLTStd-1", "6"): "±",
    ("MathematicalPiLTStd-1", "`"): "∞",
    ("MathematicalPiLTStd-1", "9"): "′",
    ("MathematicalPiLTStd-3", ">"): "≅",
    ("MathematicalPiLTStd-3", ","): "∼",
    ("MathematicalPiLTStd-5", "?"): "≠",
    ("MathematicalPiLTStd-6", "/"): "∠",
    ("MathematicalPiLTStd-6", "n"): "△",
}


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract plain text from a PDF via pypdf (fast; trusts the ToUnicode map)."""
    try:
        import pypdf  # type: ignore
    except ImportError:
        raise RuntimeError(
            "pypdf is required for PDF ingestion. "
            "Run: uv add pypdf --package oer-ingestion --dev"
        )
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def extract_pdf_text_mathpi(pdf_bytes: bytes) -> str:
    """Extract text with per-character font inspection, remapping Mathematical Pi
    glyphs to their real symbols. Slower than pypdf (~seconds per exam)."""
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTChar, LTTextContainer, LTTextLine
    except ImportError:
        raise RuntimeError(
            "pdfminer.six is required for Regents ingestion. "
            "Run: uv add pdfminer.six --package oer-ingestion --dev"
        )

    out_lines: list[str] = []
    for page in extract_pages(io.BytesIO(pdf_bytes)):
        for el in page:
            if not isinstance(el, LTTextContainer):
                continue
            for line in el:
                if not isinstance(line, LTTextLine):
                    continue
                chars: list[str] = []
                for ch in line:
                    if not isinstance(ch, LTChar):
                        continue
                    t = ch.get_text()
                    font = (ch.fontname or "").split("+")[-1]
                    if font.startswith("MathematicalPi"):
                        t = _MATHPI_REMAP.get((font, t), t)
                    chars.append(t)
                text = "".join(chars).rstrip()
                if text:
                    out_lines.append(text)
    return "\n".join(out_lines)
