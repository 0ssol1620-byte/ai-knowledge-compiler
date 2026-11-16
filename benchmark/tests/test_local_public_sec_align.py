"""WO-LPC-2: FSDS <-> inline-XBRL alignment.

Synthetic fixtures only; the scorer's normaliser is a local stand-in.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from benchmark.local_public import sec_align as sa
from benchmark.local_public.sec_align import (
    Candidate,
    Excluded,
    align,
    fsds_rows,
    nearest_month_end,
)

ADSH = "0000950170-25-113028"
KOHLS = {
    "adsh": ADSH,
    "form": "10-Q",
    "period": "20250731",
    "fye": "0131",
    "fy": "2025",
    "fp": "Q2",
    "instance": "kss-20250802_htm.xml",
}


def gold_value(field: dict[str, Any]) -> Decimal:
    """Stand-in for the scorer: parentheses or a leading minus are negative."""
    t = field["value"].replace("$", "").replace(" ", "").replace(",", "").replace("%", "")
    neg = (t.startswith("(") and t.endswith(")")) or t.startswith("-")
    return Decimal(t.strip("()-")) * (-1 if neg else 1)


def sloppy_gold_value(field: dict[str, Any]) -> Decimal:
    """Stand-in with the defect the addendum measured: a parenthesis is ignored."""
    return Decimal(field["value"].replace("$", "").replace(" ", "").replace(",", "").strip("()"))


def doc(
    contexts: list[tuple[str, str | None, str, bool]], rows: list[list[str]], hidden: str = ""
) -> bytes:
    """contexts: (id, start|None, end, has_segment); rows: list of cell inner-HTML lists."""
    cx = ""
    for cid, start, end, seg in contexts:
        period = (
            f"<xbrli:instant>{end}</xbrli:instant>"
            if start is None
            else (f"<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>")
        )
        sg = "<xbrli:segment>x</xbrli:segment>" if seg else ""
        cx += (
            f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier>1</xbrli:identifier>'
            f"{sg}</xbrli:entity>"
            f"<xbrli:period>{period}</xbrli:period></xbrli:context>"
        )
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return (
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
        'xmlns:xbrli="http://www.xbrl.org/2003/instance"><body>'
        '<div style="display:none"><ix:header>'
        f"<ix:hidden>{hidden}</ix:hidden><ix:resources>{cx}</ix:resources></ix:header></div>"
        f"<table>{trs}</table></body></html>"
    ).encode()


def fact(
    text: str,
    ctx: str = "c1",
    tag: str = "us-gaap:Revenues",
    scale: int = 6,
    sign: str | None = None,
    fmt: str | None = None,
) -> str:
    s = f' sign="{sign}"' if sign else ""
    f = f' format="{fmt}"' if fmt else ""
    return (
        f'<ix:nonFraction name="{tag}" contextRef="{ctx}" scale="{scale}" unitRef="usd"{s}{f}>'
        f"{text}</ix:nonFraction>"
    )


def num(
    value: str = "1234000000",
    ddate: str = "20250731",
    qtrs: str = "1",
    tag: str = "Revenues",
    **kw: str,
) -> dict[str, str]:
    return {
        "adsh": ADSH,
        "tag": tag,
        "version": "us-gaap/2024",
        "ddate": ddate,
        "qtrs": qtrs,
        "uom": "USD",
        "segments": "",
        "coreg": "",
        "value": value,
        **kw,
    }


def pre(tag: str = "Revenues", negating: str = "0", stmt: str = "IS") -> list[dict[str, str]]:
    return [
        {
            "adsh": ADSH,
            "tag": tag,
            "version": "us-gaap/2024",
            "stmt": stmt,
            "negating": negating,
            "plabel": tag,
            "line": "1",
            "report": "2",
        }
    ]


CTX = [("c1", "2025-05-04", "2025-08-02", False)]


def run(
    rows: list[list[str]],
    n: dict[str, str] | None = None,
    p: list[dict[str, str]] | None = None,
    contexts: list[tuple[str, str | None, str, bool]] | None = None,
    sub: dict[str, str] | None = None,
    gv: Any = gold_value,
    hidden: str = "",
) -> list[Candidate | Excluded]:
    return align(
        sub or KOHLS,
        [n or num()],
        p if p is not None else pre(),
        doc(contexts or CTX, rows, hidden),
        gv,
    )


def one(res: list[Candidate | Excluded]) -> Candidate | Excluded:
    assert len(res) == 1
    return res[0]


def reason(res: list[Candidate | Excluded]) -> str:
    r = one(res)
    assert isinstance(r, Excluded), r
    return r.reason


def cand(res: list[Candidate | Excluded]) -> Candidate:
    r = one(res)
    assert isinstance(r, Candidate), r
    return r


def row(f: str, *, before: str = "", after: str = "") -> list[str]:
    return ["Total revenues", before, f, after]


def test_kohls_52_53_week_rounding_aligns_and_records_context_dates() -> None:
    c = cand(run([row(fact("1,234"))]))
    assert c.field_id == f"{ADSH}:Revenues:2025-05-04_2025-08-02:USD"
    assert (c.start, c.end, c.ddate_rounded, c.gold, c.anchor, c.sign_basis) == (
        "2025-05-04",
        "2025-08-02",
        True,
        "1,234",
        "Total revenues",
        "match",
    )
    assert c.fsds["ddate"] == "20250731" and c.fsds["ddate_precision"] == "month_rounded"
    assert c.dom_path.endswith("ix:nonFraction") or "nonFraction" in c.dom_path


def test_exact_date_is_not_counted_as_rounded() -> None:
    c = cand(run([row(fact("1,234"))], contexts=[("c1", "2025-05-01", "2025-07-31", False)]))
    assert c.ddate_rounded is False and c.field_id.endswith("2025-05-01_2025-07-31:USD")


def test_rounding_tie_is_ambiguous() -> None:
    assert nearest_month_end(date(2025, 4, 15)) is None
    res = run(
        [row(fact("1,234"))],
        n=num(ddate="20250430", qtrs="0"),
        contexts=[("c1", None, "2025-04-15", False)],
    )
    assert reason(res) == "ddate_rounding_ambiguous"


def test_two_contexts_matching_one_row() -> None:
    ctx = [*CTX, ("c2", "2025-05-02", "2025-08-01", False)]
    assert (
        reason(run([row(fact("1,234")), row(fact("1,234", "c2"))], contexts=ctx))
        == "context_ambiguous"
    )


def test_ten_k_quarterly_note_table_is_not_statement_context() -> None:
    sub = {**KOHLS, "form": "10-K", "period": "20190331", "fp": "FY"}
    res = run(
        [row(fact("1,234"))],
        n=num(ddate="20181231", qtrs="1"),
        sub=sub,
        contexts=[("c1", "2018-10-01", "2018-12-31", False)],
    )
    assert reason(res) == "not_statement_context"


def test_ten_k_annual_current_and_prior_years_accepted() -> None:
    sub = {**KOHLS, "form": "10-K", "period": "20190331", "fp": "FY"}
    res = run(
        [row(fact("1,234"))],
        n=num(ddate="20180331", qtrs="4"),
        sub=sub,
        contexts=[("c1", "2017-04-01", "2018-03-31", False)],
    )
    assert isinstance(one(res), Candidate)


def test_ten_q_q2_cumulative_prior_year_accepted() -> None:
    sub = {**KOHLS, "period": "20250731", "fp": "Q2"}
    res = run(
        [row(fact("1,234"))],
        n=num(ddate="20240731", qtrs="2"),
        sub=sub,
        contexts=[("c1", "2024-02-04", "2024-08-03", False)],
    )
    assert isinstance(one(res), Candidate)


@pytest.mark.parametrize(
    "ddate,end,ok",
    [
        (
            "20250131",
            "2025-02-01",
            True,
        ),  # Kohl's: fy=2025 with fye=0131, the opening balance sheet (fix 1)
        ("20240131", "2024-02-03", True),
        ("20230131", "2023-01-28", False),  # two fiscal year ends back
        ("20231031", "2023-10-28", False),
    ],
)
def test_ten_q_instant_comparatives_are_fiscal_year_ends(ddate: str, end: str, ok: bool) -> None:
    res = run(
        [row(fact("1,234"))], n=num(ddate=ddate, qtrs="0"), contexts=[("c1", None, end, False)]
    )
    assert isinstance(one(res), Candidate) is ok
    if not ok:
        assert reason(res) == "not_statement_context"


def test_ten_q_instant_prior_year_same_quarter_end() -> None:
    res = run(
        [row(fact("1,234"))],
        n=num(ddate="20240731", qtrs="0"),
        contexts=[("c1", None, "2024-08-03", False)],
    )
    assert isinstance(one(res), Candidate)


def test_scale_and_value_mismatch() -> None:
    assert cand(run([row(fact("1,234", scale=6))])).scale == 6
    assert reason(run([row(fact("1,235"))])) == "value_mismatch"


def test_sign_rules() -> None:
    neg = "-1234000000"
    c = cand(run([row(fact("1,234", sign="-"), before="(", after=")")], n=num(neg)))
    assert c.sign_basis == "match" and c.gold == "(1,234)"
    c = cand(run([row(fact("55", scale=6, sign="-"))], n=num("-55000000")))  # Dentsply
    assert c.sign_basis == "ix_sign_attribute"
    c = cand(run([row(fact("1,234"), before="(", after=")")], p=pre(negating="1")))
    assert c.sign_basis == "pre_negating"
    assert reason(run([row(fact("1,234"), before="(", after=")")])) == "sign_unsupported"
    # shown positive against a negative FSDS value, no sign attribute: never reaches the sign rule,
    # the exact value test (rule 5) fails first, because `sign` is part of the fact's value.
    assert reason(run([row(fact("1,234"))], n=num(neg))) == "value_mismatch"
    assert reason(run([row(fact("1,234"), before="(")])) == "sign_unsupported"  # lone parenthesis


def test_zero_dash_cells() -> None:
    for text, fmt in (
        ("—", None),
        ("-", None),
        (chr(0x2013), None),
        ("0", "ixt:fixed-zero"),
        ("-", "ixt:zerodash"),
    ):
        assert reason(run([row(fact(text, fmt=fmt))], n=num("0"))) == "zero_dash"
    assert isinstance(one(run([row(fact("0"))], n=num("0"))), Candidate)  # a plain 0 is kept


def test_unparseable_format() -> None:
    assert reason(run([row(fact("1.234,5", fmt="ixt:num-comma-decimal"))])) == "unparseable_format"


def test_gold_string_is_canonical_with_currency_and_parentheses() -> None:
    assert cand(run([row(fact("1,234"), before="$")])).gold == "$ 1,234"
    assert (
        cand(run([row(fact("1,234", sign="-"), before="(", after=")")], n=num("-1234000000"))).gold
        == "(1,234)"
    )
    # "$ (" in the preceding cell: negative, currency kept, no stray spaces inside the parentheses
    assert (
        cand(
            run([row(fact("1,234", sign="-"), before="$ (", after=")")], n=num("-1234000000"))
        ).gold
        == "$ (1,234)"
    )
    assert (
        cand(
            run(
                [["Total revenues", "", "$", "(", fact("1,234", sign="-"), ")"]],
                n=num("-1234000000"),
            )
        ).gold
        == "$ (1,234)"
    )
    assert cand(run([row(fact("12"), before="", after="%")], n=num("12000000"))).gold == "12%"


def test_in_cell_spaced_parentheses_do_not_flip_the_gold_sign() -> None:
    """'( 1,234 )' joined by whitespace reads positive in the scorer; the gold is rebuilt."""
    cell = "( " + fact("1,234", sign="-") + " )"
    c = cand(run([["Total revenues", cell]], n=num("-1234000000")))
    assert c.gold == "(1,234)" and gold_value({"value": c.gold}) == Decimal(-1234)


def test_gold_that_does_not_round_trip_is_excluded() -> None:
    res = run(
        [row(fact("1,234", sign="-"), before="(", after=")")],
        n=num("-1234000000"),
        gv=sloppy_gold_value,
    )
    assert reason(res) == "gold_roundtrip_mismatch"

    def raising(field: dict[str, Any]) -> Decimal:
        raise ValueError(field["value"])

    assert reason(run([row(fact("1,234"))], gv=raising)) == "gold_unparseable"


def test_hidden_fact_only() -> None:
    hidden = fact("1,234")
    assert reason(run([["Total revenues", "text"]], hidden=hidden)) == "hidden_only"
    styled = '<span style="display: none">' + fact("1,234") + "</span>"
    assert reason(run([["Total revenues", styled]])) == "hidden_only"


def test_scope_and_presentation_codes() -> None:
    r = [row(fact("1,234"))]
    assert reason(run(r, n=num(segments="Axis=X"))) == "dimensional"
    assert reason(run(r, n=num(coreg="Co"))) == "coregistrant"
    assert reason(run(r, p=[])) == "not_presented"
    assert reason(run(r, p=pre(stmt="SI"))) == "not_presented"
    assert reason(run(r, sub={**KOHLS, "instance": "kss-20250802.xml"})) == "no_inline_xbrl"
    assert reason(run(r, n=num(value="abc"))) == "fsds_unparseable"
    assert (
        reason(
            run(
                [],
            )
        )
        == "no_ix_fact"
    )


def test_context_with_segment_is_ignored() -> None:
    assert (
        reason(run([row(fact("1,234"))], contexts=[("c1", "2025-05-04", "2025-08-02", True)]))
        == "no_ix_fact"
    )


def test_second_column_fact_and_missing_label() -> None:
    other = fact("999", "c1", tag="us-gaap:Other")
    assert reason(run([["Total revenues", other, fact("1,234")]])) == "not_first_column"
    assert reason(run([["", fact("1,234")]])) == "no_label"
    assert reason(run([[fact("1,234")]])) == "no_label"


def test_fact_printed_twice_gives_two_candidates_shadow_decision_left_to_pages() -> None:
    res = run([row(fact("1,234")), ["Other label", fact("1,234")]])
    assert len(res) == 2 and all(isinstance(r, Candidate) for r in res)
    assert {r.anchor for r in res if isinstance(r, Candidate)} == {"Total revenues", "Other label"}


def test_later_filing_restated_value_never_aligns_to_earlier_adsh() -> None:
    """A key restated in a later filing carries another adsh; one accession is read."""
    later = {**num("1300000000"), "adsh": "0000950170-25-999999"}
    res = align(KOHLS, [num()], pre(), doc(CTX, [row(fact("1,300"))]), gold_value)
    assert reason(res) == "value_mismatch"
    assert later["adsh"] != KOHLS["adsh"]


def test_no_stored_output_carries_ddate_outside_fsds() -> None:
    c = cand(run([row(fact("1,234"))]))
    flat = {k: v for k, v in c.__dict__.items() if k != "fsds"}
    assert "20250731" not in repr(flat)
    assert "ddate" not in flat


def test_fsds_rows_streams_one_adsh() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("sub.txt", "adsh\tform\nA\t10-Q\nB\t10-K\n")
        z.writestr("num.txt", "adsh\ttag\nA\tx\nB\ty\nA\tz\n")
        z.writestr("pre.txt", "adsh\ttag\nB\tq\n")
    with zipfile.ZipFile(buf) as z:
        s, n, p = fsds_rows(z, "A")
    assert s == {"adsh": "A", "form": "10-Q"} and [r["tag"] for r in n] == ["x", "z"] and p == []


def test_module_does_not_import_the_scorer() -> None:
    with open(sa.__file__, encoding="utf-8") as f:
        assert "critical_fields" not in f.read()
