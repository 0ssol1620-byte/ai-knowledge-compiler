"""Markup normaliser v1 (WO-D10-0G, decision 5H-11).

The four A0 texts below are SYNTHETIC: model outputs for a one-page test PDF made for the A0
smoke (receipts/d10-screen-v1/A0/out/, C2, C7, C8, C5b2). They hold no real document, no gold
and rank nothing. The other fixtures are constructed strings.
"""

from __future__ import annotations

import hashlib
import re
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
