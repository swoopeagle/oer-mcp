"""CNXML text extraction — flatten mixed CNXML prose to plain text with inline
math rendered as $...$ LaTeX. Used by the OpenStax typed sub-chunk splitter.
"""

from lxml import etree

from .mathml import ML, mathml_to_latex

CN = "http://cnx.rice.edu/cnxml"
NS = {"c": CN, "m": ML}

# Block-level CNXML elements that should be separated by blank lines in output.
_BLOCK = {"para", "item", "title", "caption", "entry", "row"}
# Elements whose subtree we drop entirely from prose text.
_DROP = {"media", "image", "figure", "labeled-item"}


def _q(elem) -> str:
    return etree.QName(elem).localname


def _walk(elem, parts: list[str]) -> None:
    tag = _q(elem)
    if tag == "math" and elem.tag == f"{{{ML}}}math":
        latex = mathml_to_latex(elem)
        if latex:
            parts.append(f"${latex}$")
        if elem.tail and elem.tail.strip():
            parts.append(elem.tail)
        return
    if tag in _DROP:
        if elem.tail and elem.tail.strip():
            parts.append(elem.tail)
        return

    if elem.text and elem.text.strip():
        parts.append(elem.text)
    for child in elem:
        if not isinstance(child.tag, str):
            continue
        _walk(child, parts)
    if tag in _BLOCK:
        parts.append("\n")
    if elem.tail and elem.tail.strip():
        parts.append(elem.tail)


def element_text(elem) -> str:
    """Plain-text rendering of a CNXML element subtree with inline LaTeX math."""
    parts: list[str] = []
    _walk(elem, parts)
    text = "".join(parts)
    # Collapse runs of spaces/newlines but keep paragraph breaks.
    lines = [" ".join(line.split()) for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def word_count(text: str) -> int:
    return len(text.split())
