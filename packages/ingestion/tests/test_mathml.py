from lxml import etree

from oer_ingestion.mathml import mathml_to_latex

M = "http://www.w3.org/1998/Math/MathML"


def _math(inner: str):
    return etree.fromstring(f'<math xmlns="{M}">{inner}</math>')


def test_fraction():
    assert mathml_to_latex(_math("<mfrac><mn>1</mn><mn>4</mn></mfrac>")) == r"\frac{1}{4}"


def test_arithmetic_with_operators():
    ml = "<mn>5</mn><mo>×</mo><mn>2</mn><mo>+</mo><mn>1</mn>"
    assert mathml_to_latex(_math(ml)) == r"5\times 2+1"


def test_superscript_braces_single_vs_multi():
    assert mathml_to_latex(_math("<msup><mi>x</mi><mn>2</mn></msup>")) == "x^{2}"
    assert (
        mathml_to_latex(_math("<msup><mrow><mn>10</mn></mrow><mn>3</mn></msup>"))
        == "{10}^{3}"
    )


def test_sqrt():
    assert mathml_to_latex(_math("<msqrt><mn>9</mn></msqrt>")) == r"\sqrt{9}"


def test_unknown_element_degrades_to_text():
    # an unsupported wrapper should still surface its child content
    assert mathml_to_latex(_math("<mpadded><mn>7</mn></mpadded>")) == "7"
