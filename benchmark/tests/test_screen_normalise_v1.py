"""Markup normaliser v1 (WO-D10-0G, decision 5H-11).

The four A0 texts below are SYNTHETIC: model outputs for a one-page test PDF made for the A0
smoke (receipts/d10-screen-v1/A0/out/, C2, C7, C8, C5b2). They hold no real document, no gold
and rank nothing. The other fixtures are constructed strings.
"""

from __future__ import annotations

import gc
import hashlib
import re
import time
from pathlib import Path
from typing import Any

import pytest

from benchmark.screen import normalise_v1 as n1
from benchmark.screen.critical_fields import gold_value, value_after_anchor

# SYNTHETIC (A0 smoke page, not a real document)
A0_C2 = (
    "## 합성 시험 페이지: 분기 운영 요약\n\n"
    "이 문서는 문자 인식 시험을 위해 만든 합성 페이지입니다.\n\n"
    "표와 수식과 금액이 한 페이지에 함께 들어 있습니다.\n\n"
    "This page was generated for an OCR smoke test and holds no real data.\n\n"
    "평균은 $x = (a + b) / 2$ 로 계산합니다.\n\n<table border=1><tr><td>항목</td><td>수량</td></tr>"
    "<tr><td>부품 A</td><td>12,345.67</td></tr></table>\n\n1,250,000원"
)
# SYNTHETIC (A0 smoke page, not a real document)
A0_C7 = (
    "# 합성 시험 페이지: 분기 운영 요약\n\n"
    "이 문서는 문자 인식 시험을 위해 만든 합성 페이지입니다.\n\n"
    "표와 수식과 금액이 한 페이지에 함께 들어 있습니다.\n\n"
    "This page was generated for an OCR smoke test and holds no real data.\n\n"
    "평균은 $x = (a + b) / 2$ 로 계산합니다.\n\n<table><thead><tr><td>항목</td><td>수량</td></tr>"
    "</thead><tbody><tr><td>부품 A</td><td>12,345.67</td></tr></tbody></table>\n\n1,250,000원"
)
# SYNTHETIC (A0 smoke page, not a real document); the model misread 부품 as 부용
A0_C8 = (
    "## 한성 시행 피이지:분기운영요약\n\n이문서는문자인식시행을위해만들한성PU에지입니다.\n\n"
    "표와수식과금역이한PU이지에하게들어 있습니다.\n\n"
    "This page was generated for an OCR smoke test and holds no real data.\n\n"
    "명%)은 \\(x = (a + b) / 2\\)로계산합니다.\n\n"
    "<fcel>化물<fcel>수당<nl><fcel>부용 A<fcel>12,345.67<nl>\n\n1,250,000원"
)
# SYNTHETIC (A0 smoke page, not a real document)
A0_C5B2 = (
    "<x_0.0918><y_0.0813>합성 시험 페이지: 분기 운영 요약<x_0.6289><y_0.1117>"
    "<class_Section-header>\n\n<x_0.0908><y_0.1422>이 문서는 문자 인식 시험을 위해 만든 합성 "
    "페이지입니다.<x_0.7324><y_0.1656><class_Text>\n\n<x_0.0928><y_0.1766>표와 수식과 금액이 한 "
    "페이지에 함께 들어 있습니다.<x_0.6768><y_0.2><class_Text>\n\n<x_0.0918><y_0.2125>This page "
    "was generated for an OCR smoke test and holds no real data.\n평균은 x = (a + b) / 2 로 "
    "계산합니다.<x_0.9043><y_0.2687><class_Text>\n\n<x_0.0938><y_0.3055>\\begin{tabular}{cc}\n"
    "\\thead{항목} & \\thead{수량}\\\\\n부품 A & 12,345.67\\\\\n\\end{tabular}<x_0.7432><y_0.3875>"
    "<class_Table>\n\n<x_0.0947><y_0.4414>1,250,000원<x_0.2842><y_0.4711><class_Text>"
)
ITEM = {"field_id": "a", "kind": "number", "anchor": "부품 A", "value": "12,345.67"}
A0 = [
    ("ovis_ocr2", A0_C2),
    ("ovis_ocr3", A0_C7),
    ("nemotron_parse_3_5", A0_C5B2),
]
ALL_A0 = [*A0, ("xiaomi_ocr_0", A0_C8)]


def _field(anchor: str, value: str = "1") -> dict[str, Any]:
    return {"field_id": "f", "kind": "number", "anchor": anchor, "value": value}


def _keeps(provider: str, text: str, field: dict[str, Any]) -> None:
    """A value the reader reads from the raw text is read identically after normalising."""
    before = value_after_anchor(field, text)
    assert before is not None, "fixture must be readable raw"
    assert value_after_anchor(field, n1.normalise(provider, text)[0]) == before


PROPERTY = [
    ("nemotron_parse_3_5", "Research & development 1,234", "Research & development"),
    ("ovis_ocr2", "Research & development 1,234", "Research & development"),
    ("ovis_ocr2", "| Total revenue | 1,234 | 1,100 |", "Total revenue"),
    ("nemotron_parse_3_5", "Total revenue & 1,234 & 1,100 \\\\", "Total revenue"),
    ("ovis_ocr2", "Price &para 1,234", "Price &para"),
]


@pytest.mark.parametrize(("provider", "text"), A0)
def test_a0_reads_the_table_value_only_after_normalising(provider: str, text: str) -> None:
    assert value_after_anchor(ITEM, text) is None
    assert value_after_anchor(ITEM, n1.normalise(provider, text)[0]) == ("12345.67", "num", None)


def test_c8_misread_its_anchor_so_the_true_anchor_reads_nothing() -> None:
    out = n1.normalise("xiaomi_ocr_0", A0_C8)[0]
    assert value_after_anchor(ITEM, A0_C8) is None
    assert value_after_anchor(ITEM, out) is None
    # the markup barrier itself is gone: the anchor the model wrote reads the value
    misread = dict(ITEM, anchor="부용 A")
    assert value_after_anchor(misread, A0_C8) is None
    assert value_after_anchor(misread, out) == ("12345.67", "num", None)


@pytest.mark.parametrize(("provider", "text"), ALL_A0)
def test_a0_residual_zero_and_idempotent(provider: str, text: str) -> None:
    out, residual = n1.normalise(provider, text)
    assert residual == 0
    assert n1.normalise(provider, out) == (out, 0)


@pytest.mark.parametrize(("provider", "text"), ALL_A0)
def test_digits_outside_markup_are_kept_in_order(provider: str, text: str) -> None:
    markup = re.compile(r"<[^<>]{0,60}>|\\[A-Za-z]+\{[^{}]{0,10}\}")
    assert re.findall(r"\d", n1.normalise(provider, text)[0]) == re.findall(
        r"\d", markup.sub(" ", text)
    )


@pytest.mark.parametrize(("provider", "text", "anchor"), PROPERTY)
def test_a_value_read_raw_is_read_identically_after(provider: str, text: str, anchor: str) -> None:
    _keeps(provider, text, _field(anchor))


def test_nemotron_ampersand_is_a_cell_only_inside_tabular() -> None:
    text = "R & D \\& co\n\\begin{tabular}{cc}\nRevenue & 1,234 \\& x\\\\ \\hline\n\\end{tabular}"
    out, residual = n1.normalise("nemotron_parse_3_5", text)
    assert out.startswith("R & D & co\n")
    assert re.search(r"Revenue +\| +1,234 & x", out)
    assert residual == 0


def test_entities_need_a_semicolon_and_nbsp_becomes_space() -> None:
    out, _ = n1.normalise("ovis_ocr2", "a&amp;b &#160;x &para y &#x31;")
    assert out == "a&b  x &para y 1"


def test_unknown_tag_is_kept_and_counted() -> None:
    out, residual = n1.normalise("ovis_ocr2", "<td>A</td><span>1</span> \\frac")
    assert "<span>1</span>" in out
    assert residual == 3


def test_symbol_cells_join_their_number() -> None:
    usd = _field("Total revenue", "$ 1,234")
    neg = _field("Total revenue", "(1,234)")
    pct = _field("Margin", "1.5%")
    for field, text in (
        (usd, "| Total revenue | $ | 1,234 |"),
        (neg, "| Total revenue | (1,234 | ) |"),
        (neg, "| Total revenue | ( | 1,234 | ) |"),
        (pct, "| Margin | 1.5 | % |"),
    ):
        assert value_after_anchor(field, text) is None  # the boundary hides the symbol
        out = n1.normalise("ovis_ocr2", text)[0]
        assert value_after_anchor(field, out) == gold_value(field)
    out = n1.normalise("ovis_ocr2", "<tr><td>Total revenue</td><td>$</td><td>1,234</td></tr>")[0]
    assert value_after_anchor(usd, out) == ("1234", "num", "USD")
    assert value_after_anchor(neg, n1.normalise("ovis_ocr2", "| x | (1,234 | ) |")[0]) is None
    assert "$ | 1" not in n1.normalise("ovis_ocr2", "| Total revenue | $ | 1,234 |")[0]
    assert value_after_anchor(neg, "| Total revenue | (1,234) |") == ("-1234", "num", None)
    # the reviewer's html inputs (round 1): two boundaries between adjacent cells
    for field, text in (
        (neg, "<tr><td>Total revenue</td><td>(1,234</td><td>)</td></tr>"),
        (pct, "<tr><td>Margin</td><td>1.5</td><td>%</td></tr>"),
        (
            _field("Total revenue", "$ (1,234)"),
            "<tr><td>Total revenue</td><td>$</td><td>(1,234</td><td>)</td></tr>",
        ),
    ):
        out = n1.normalise("ovis_ocr2", text)[0]
        assert value_after_anchor(field, out) == gold_value(field), repr(out)


# ------------------------------------------------- one logical row, every rendering (5H-11)
# The class: after normalising, a cell holding only ) or % belongs to the nearest non-empty cell
# before it, and a cell holding only $ € £ ¥ ( to the nearest non-empty cell after it, whatever
# markup the cells came from; two value cells stay apart even with an empty cell between them.

FORMS = [
    "html",
    "html_pretty",
    "otsl",
    "nemotron",
    "nemotron_wrapped",
    "md_html",
    "md_otsl",
    "md_nemotron",
]


def _render(form: str, cells: list[str]) -> tuple[str, str]:
    """(provider, text): one table row written in one of the forms candidates emit."""
    if form == "html":
        return "ovis_ocr2", "<table><tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
    if form == "html_pretty":
        body = "".join(f"    <td>{c}</td>\n" for c in cells)
        return "mineru", f"<table>\n  <tr>\n{body}  </tr>\n</table>"
    if form == "otsl":
        return "xiaomi_ocr_0", "".join(f"<fcel>{c}" if c else "<ecel>" for c in cells) + "<nl>"
    if form.startswith("nemotron"):
        tex = [c.replace("$", "\\$").replace("%", "\\%") for c in cells]
        sep = " &\n" if form == "nemotron_wrapped" else " & "
        spec = "c" * len(cells)
        return (
            "nemotron_parse_3_5",
            f"\\begin{{tabular}}{{{spec}}}\n{sep.join(tex)} \\\\\n\\end{{tabular}}",
        )
    provider = {"md_html": "paddleocr_vl_1_6", "md_otsl": "xiaomi_ocr_0"}.get(
        form, "nemotron_parse_3_5"
    )
    return provider, "| " + " | ".join(cells) + " |"


SYMBOL_ROWS = [
    (["Total revenue", "(1,234", ")"], "(1,234)"),
    (["Total revenue", "(1,234", "", ")"], "(1,234)"),
    (["Total revenue", "$", "(1,234", ")"], "$ (1,234)"),
    (["Total revenue", "$", "", "(1,234", "", ")"], "$ (1,234)"),
    (["Total revenue", "(", "1,234", ")"], "(1,234)"),
    (["Margin", "1.5", "%"], "1.5%"),
    (["Margin", "1.5", "", "%"], "1.5%"),
    (["Total revenue", "$", "1,234"], "$ 1,234"),
    (["Total revenue", "1,234"], "1,234"),
]


@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize(("cells", "value"), SYMBOL_ROWS)
def test_a_symbol_cell_joins_its_number_in_every_rendering(
    form: str, cells: list[str], value: str
) -> None:
    field = _field(cells[0], value)
    provider, text = _render(form, cells)
    out, residual = n1.normalise(provider, text)
    assert value_after_anchor(field, out) == gold_value(field), repr(out)
    assert residual == 0
    assert n1.normalise(provider, out) == (out, 0)


@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize("cells", [["Revenue", "1,234", "5"], ["Revenue", "1,234", "", "5"]])
def test_two_value_cells_are_never_joined(form: str, cells: list[str]) -> None:
    provider, text = _render(form, cells)
    out = n1.normalise(provider, text)[0]
    held = [c.strip() for line in out.split("\n") for c in line.split("|")]
    assert "1,234" in held and "5" in held, repr(out)
    assert value_after_anchor(_field("Revenue", "1,234"), out) == ("1234", "num", None)


def test_nested_wrappers_unwrap_to_a_fixed_point_within_the_bound() -> None:
    text = "\\textbf{Revenue \\textit{net \\text{of tax}}} \\multicolumn{2}{c}{\\thead{1,234}}"
    out, residual = n1.normalise("nemotron_parse_3_5", text)
    assert out == "Revenue net of tax 1,234" and residual == 0
    assert n1.normalise("nemotron_parse_3_5", out) == (out, 0)
    deep = "\\textbf{" * (n1.TEX_PASSES + 1) + "x" + "}" * (n1.TEX_PASSES + 1)
    out, residual = n1.normalise("nemotron_parse_3_5", deep)
    assert out == "\\textbf{x}" and residual == 1  # past the bound: left visible, counted


def test_a_row_end_before_an_ampersand_is_a_row_end_and_a_cell_boundary() -> None:
    bs = "\\"
    body = f"Revenue & 1,234 {bs * 2}& 5 {bs * 2}\nR {bs}& D & 7 {bs * 3}& x"
    text = f"{bs}begin{{tabular}}{{cc}}\n{body}\n{bs}end{{tabular}}"
    out, residual = n1.normalise("nemotron_parse_3_5", text)
    lines = [[c.strip() for c in line.split("|")] for line in out.split("\n") if line.strip()]
    assert lines == [["Revenue", "1,234"], ["", "5"], ["R & D", "7"], ["& x"]], repr(out)
    assert residual == 0


ROW = "<tr><td>Revenue</td><td>1,234</td><td>5</td></tr>"


def test_cells_stay_apart() -> None:
    field = _field("Revenue", "1,234")
    for provider, text in (
        ("ovis_ocr2", ROW),
        ("xiaomi_ocr_0", "<fcel>Revenue<fcel>1,234<fcel>5<nl>"),
        ("nemotron_parse_3_5", "Revenue 1,234<x_0.5><y_0.6>Cost"),
    ):
        assert value_after_anchor(field, text) is None
        assert value_after_anchor(field, n1.normalise(provider, text)[0]) == gold_value(field)


def test_a_line_without_a_pipe_is_not_joined() -> None:
    assert n1.normalise("ovis_ocr2", "$ 5 ( 3 ) %")[0] == "$ 5 ( 3 ) %"


# ------------------------------------------------- linear in the input (round 3, decision A)
# The class: every step of normalise costs time proportional to the input length, for any input
# a pod can send (the page runner accepts up to 10 MiB). Each shape is one unit repeated; the
# ones that grew a cell on every join (round 2) and every pattern's worst case are among them.

BS = "\\"
UNITS = {
    "td_close": "<td>)</td>",
    "td_empty_close": "<td></td><td>%</td>",
    "pipe_empty_close": "| | ) ",
    "pipe_close": "| ) ",
    "td_open": "<td>$</td>",
    "pipe_open": "| ( ",
    "pipes_only": "|",
    "fcel": "<fcel>",
    "ecel_fcel_close": "<ecel><fcel>)",
    "textbf_unclosed": BS + "textbf{",
    "textbf_closed": BS + "textbf{x}",
    "amp_in_tabular": "&",
    "backslash_in_tabular": BS,
    "amp_outside": "& ",
    "begin_unclosed": BS + "begin{tabular}",
    "one_line": "Revenue 1,234 ",
    "newlines": "\n",
    "unclosed_tag": "<td ",
}
SIZES = (250_000, 500_000, 1_000_000, 2_000_000)
RATIO, FLOOR_S, ONE_MB_S = 3.0, 0.1, 5.0  # unchanged: no limit moved
RETRIES = 4


def _shape(name: str, size: int) -> str:
    body = UNITS[name] * (size // len(UNITS[name]))
    if name.endswith("_in_tabular"):
        return BS + "begin{tabular}{c}" + body + BS + "end{tabular}"
    return body


def _cpu_seconds(provider: str, text: str) -> float:
    gc.collect()
    start = time.process_time()
    n1.normalise(provider, text)
    return time.process_time() - start


@pytest.mark.parametrize("provider", ["mineru", "xiaomi_ocr_0", "nemotron_parse_3_5"])
@pytest.mark.parametrize("shape", list(UNITS))
def test_normalise_is_linear_in_its_input(provider: str, shape: str) -> None:
    """Doubling the input at most roughly doubles the time (ratio 3; below FLOOR_S a timer
    tick is noise), and 1 MB finishes inside 5 s. CPU time of this process, so other load on
    the machine does not count; contention only ever adds time, so a size over the ratio is
    measured again, up to RETRIES more times, and the minimum is judged (a spike is not a trend,
    a quadratic step is over the ratio in every measurement)."""
    took: list[float] = []
    for size in SIZES:
        text = _shape(shape, size)
        took.append(_cpu_seconds(provider, text))
        for _ in range(RETRIES):
            if len(took) < 2 or took[-1] <= RATIO * max(took[-2], FLOOR_S):
                break
            took[-1] = min(took[-1], _cpu_seconds(provider, text))
        if len(took) > 1:
            assert took[-1] <= RATIO * max(took[-2], FLOOR_S), (size, took)
        if size == 1_000_000:
            assert took[-1] < ONE_MB_S, took


JOINED = [  # what the round-2 join (7c9514f) wrote; the linear join writes the same bytes
    ("a |  | ) \t", "a ) \t"),
    (" \t| ) | x", " ) | x"),
    ("$ | \u00a0 | \u2003 | 1 \t", "$ 1 \t"),
    ("( |  | ( | 1 | ) | %", "( ( 1 ) %"),
    ("x | ) | ) | ) | 5", "x ) ) ) | 5"),
    ("$$$ | 1", "$$$ 1"),
    ("$$$$ | 1", "$$$$ | 1"),
    ("a |\t) b | 2", "a |\t) b | 2"),
    ("| | | ) |", " ) |"),
    ("| Total | $ |", "| Total | $ "),  # an open cell that absorbs a last empty cell
]


@pytest.mark.parametrize(("line", "joined"), JOINED)
def test_the_join_keeps_round_2_bytes_at_the_whitespace_edges(line: str, joined: str) -> None:
    assert n1.normalise("ovis_ocr2", line)[0] == joined


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("| Net loss | - | 1,234 |", True),
        ("<tr><td>Net loss</td><td>\u2212</td><td>(1,234)</td></tr>", True),
        ("| Net loss | - | $ | 1,234 |", True),  # $ joins 1,234 first: one number cell
        ("| Net loss | - | | 1,234 |", False),  # not directly followed
        ("| Net loss | - | n/a |", False),
        ("| Net loss | -1,234 |", False),
        ("Net loss - 1,234", False),
    ],
)
def test_a_dash_cell_before_a_number_is_found_not_joined(text: str, found: bool) -> None:
    provider = "ovis_ocr2"
    out = n1.normalise(provider, text)[0]
    assert n1.dash_cell_before_number(out) is found, repr(out)
    if found:  # decision D: the sign stays in its own cell, never invented into the number
        assert re.search(r"[-\u2212] \|", out), repr(out)


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="no normaliser profile"):
        n1.normalise("gemini_api", "x")


def test_module_sha256_is_the_file() -> None:
    data = Path(n1.__file__).read_bytes()
    assert "sha256:" + hashlib.sha256(data).hexdigest() == n1.MODULE_SHA256


# ---------------------------------------------------------------- mutants


def test_mutant_td_to_nothing_fails_cells_stay_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(n1, "CELL", "")
    with pytest.raises(AssertionError):
        test_cells_stay_apart()


def test_mutant_global_ampersand_fails_the_property(monkeypatch: pytest.MonkeyPatch) -> None:
    original = n1._nemotron
    monkeypatch.setitem(n1._STEPS, "nemotron", lambda t: original(t).replace("&", n1.CELL))
    with pytest.raises(AssertionError):
        _keeps(
            "nemotron_parse_3_5", "Research & development 1,234", _field("Research & development")
        )


def test_mutant_unescape_without_semicolon_fails_the_property(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loose = re.compile(r"&(?:#\d{1,7}|#x[0-9A-Fa-f]{1,6}|[A-Za-z]{2,8});?")
    monkeypatch.setattr(n1, "_ENTITY", loose)
    with pytest.raises(AssertionError):
        _keeps("ovis_ocr2", "Price &para 1,234", _field("Price &para"))
