"""Presentation-MathML → LaTeX, scoped to the element set OpenStax CNXML uses.

OpenStax modules carry no TeX annotations (verified S1), so math must be
converted from presentation MathML. The element frequency in a representative
module (m81285): mn, mrow, mfrac, mo, mi, mspace, mtext, mtd/mtr/mtable,
munder, menclose. This recursive converter covers that set; unknown elements
degrade to their concatenated child text rather than failing.
"""

from lxml import etree

ML = "http://www.w3.org/1998/Math/MathML"


def _q(elem) -> str:
    return etree.QName(elem).localname


# Operators/identifiers that have LaTeX command spellings.
_OP_MAP = {
    "−": "-", "–": "-", "×": r"\times ", "·": r"\cdot ", "÷": r"\div ",
    "≤": r"\le ", "≥": r"\ge ", "≠": r"\ne ", "≈": r"\approx ",
    "±": r"\pm ", "∞": r"\infty ", "→": r"\to ", "…": r"\ldots ",
    "∙": r"\cdot ", "π": r"\pi ", "°": r"^\circ ",
}


def _txt(elem) -> str:
    return (elem.text or "").strip()


def _children(elem):
    return [c for c in elem if isinstance(c.tag, str)]


def _convert(elem) -> str:
    tag = _q(elem)
    kids = _children(elem)

    if tag in ("math", "mrow", "mstyle", "semantics"):
        return "".join(_convert(c) for c in kids)
    if tag in ("mn", "mi"):
        t = _txt(elem)
        return _OP_MAP.get(t, t)
    if tag == "mo":
        t = _txt(elem)
        return _OP_MAP.get(t, t)
    if tag == "mtext":
        t = _txt(elem)
        return rf"\text{{{t}}}" if t else ""
    if tag == "mspace":
        return r"\ "
    if tag == "mfrac":
        if len(kids) == 2:
            return rf"\frac{{{_convert(kids[0])}}}{{{_convert(kids[1])}}}"
    if tag == "msup" and len(kids) == 2:
        return rf"{_wrap(kids[0])}^{{{_convert(kids[1])}}}"
    if tag == "msub" and len(kids) == 2:
        return rf"{_wrap(kids[0])}_{{{_convert(kids[1])}}}"
    if tag == "msubsup" and len(kids) == 3:
        return rf"{_wrap(kids[0])}_{{{_convert(kids[1])}}}^{{{_convert(kids[2])}}}"
    if tag == "msqrt":
        return rf"\sqrt{{{''.join(_convert(c) for c in kids)}}}"
    if tag == "mroot" and len(kids) == 2:
        return rf"\sqrt[{_convert(kids[1])}]{{{_convert(kids[0])}}}"
    if tag in ("munder", "mover", "munderover"):
        # Stretchy underlines etc. are layout sugar — keep the base operands.
        return "".join(_convert(c) for c in kids if _q(c) != "mspace")
    if tag == "menclose":
        return "".join(_convert(c) for c in kids)
    if tag == "mfenced":
        inner = ", ".join(_convert(c) for c in kids)
        return rf"{elem.get('open', '(')}{inner}{elem.get('close', ')')}"
    if tag == "mtable":
        rows = [
            " & ".join(_convert(td) for td in _children(tr))
            for tr in kids
            if _q(tr) == "mtr"
        ]
        return r"\begin{matrix}" + r" \\ ".join(rows) + r"\end{matrix}"
    if tag in ("mtr", "mtd"):
        return "".join(_convert(c) for c in kids)

    # Unknown element: fall back to concatenated child output / text.
    return "".join(_convert(c) for c in kids) if kids else _txt(elem)


def _wrap(elem) -> str:
    """Wrap a base in braces when it isn't a single token."""
    out = _convert(elem)
    return out if len(out) == 1 else f"{{{out}}}"


def mathml_to_latex(math_elem) -> str:
    """Convert one <m:math> element to an inline LaTeX string (no delimiters)."""
    return _convert(math_elem).strip()
