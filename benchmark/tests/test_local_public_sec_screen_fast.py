"""WO-LPC-R2P: the page selection is measured, uses the machine's cores and can resume.

Synthetic filings only (one of them shaped like the slow case: many filer pages, a flat body,
many tagged facts). No browser, no network, no real data.
"""

from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from benchmark.local_public import sec_align, sec_pages, sec_screen
from benchmark.screen.critical_fields import gold_value

CTX = (
    '<xbrli:context id="c1"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity>'
    "<xbrli:period><xbrli:startDate>2025-05-04</xbrli:startDate>"
    "<xbrli:endDate>2025-08-02</xbrli:endDate></xbrli:period></xbrli:context>"
)
BREAK = '<div style="page-break-after:always"></div>'


def _fact(tag: str) -> str:
    return (
        f'<ix:nonFraction name="us-gaap:{tag}" contextRef="c1" scale="6" unitRef="usd">'
        "1,234</ix:nonFraction>"
    )


def slow_filing(
    adsh: str, pages: int, stmt: int = 3, rows: int = 4, filler: int = 20, notes: int = 5
) -> tuple[dict[str, str], list[dict[str, str]], list[dict[str, str]], bytes]:
    """`stmt` statement pages of `rows` presented facts; every other page is a flat run of
    `filler` divs and `notes` tagged facts whose FSDS rows are not presented."""
    sub = {
        "adsh": adsh,
        "cik": "1",
        "form": "10-Q",
        "period": "20250731",
        "fye": "0131",
        "fy": "2025",
        "fp": "Q2",
        "instance": "x-20250802_htm.xml",
    }
    num: list[dict[str, str]] = []
    pre: list[dict[str, str]] = []
    body: list[str] = []
    for p in range(pages):
        if p < stmt:
            trs = []
            for r in range(rows):
                tag = f"S{p}x{r}"
                trs.append(f"<tr><td>Line {p} {r}</td><td>$</td><td>{_fact(tag)}</td></tr>")
                num.append(_num(adsh, tag))
                pre.append(
                    {
                        "adsh": adsh,
                        "report": "2",
                        "line": "1",
                        "stmt": "IS",
                        "plabel": tag,
                        "negating": "0",
                        "tag": tag,
                        "version": "us-gaap/2024",
                    }
                )
            body.append(f"<table>{''.join(trs)}</table>")
        else:
            body += [f"<div><span>Narrative {p} {i}</span></div>" for i in range(filler)]
            for i in range(notes):
                body.append(f"<p>Note {_fact(f'N{p}x{i}')} million</p>")
                num.append(_num(adsh, f"N{p}x{i}"))
        body.append(BREAK)
    html = (
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
        'xmlns:xbrli="http://www.xbrl.org/2003/instance"><body>'
        f'<div style="display:none"><ix:header><ix:resources>{CTX}</ix:resources></ix:header></div>'
        f"{''.join(body)}</body></html>"
    ).encode()
    return sub, num, pre, html


def _num(adsh: str, tag: str) -> dict[str, str]:
    return {
        "adsh": adsh,
        "tag": tag,
        "version": "us-gaap/2024",
        "ddate": "20250731",
        "qtrs": "1",
        "uom": "USD",
        "segments": "",
        "coreg": "",
        "value": "1234000000",
    }


def render_one(html: Path, pdf: Path) -> int:
    pdf.write_bytes(b"%PDF-fake" + html.read_bytes())
    return 1


def _pick(sub: Any, num: Any, pre: Any, html: bytes) -> tuple[Any, Counter[str], Counter[str]]:
    reasons: Counter[str] = Counter()
    rows: Counter[str] = Counter()
    with tempfile.TemporaryDirectory() as t:
        page = sec_screen.pick_page(
            sub, num, pre, html, gold_value=gold_value, render=render_one, seed="s",
            work=Path(t), reasons=reasons, rows=rows, errors=[],
        )  # fmt: skip
    return page, reasons, rows


# ---------------------------------------------------------------- 1. the algorithmic fix


def test_slow_shape_copies_the_document_only_for_segments_with_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before: every one of the 60 filer pages deep-copied the whole document in `accept`."""
    calls: list[int] = []
    real = sec_pages._clone

    def counting(seg: sec_pages.Segment) -> Any:
        calls.append(seg.index)
        return real(seg)

    monkeypatch.setattr(sec_pages, "_clone", counting)
    page, reasons, rows = _pick(*slow_filing("0000000001-25-000001", pages=60))
    assert page is not None and len(page.fields) == 4
    # 3 statement pages judged + 1 excerpt of the chosen page; never once per filer page
    assert len(calls) == 4 and set(calls) <= {0, 1, 2}
    assert rows["dom_accepted_rows"] == 12 and reasons["not_presented"] == 57 * 5


def test_fact_paths_are_computed_once_per_document_and_only_for_candidate_tags() -> None:
    sub, num, pre, html = slow_filing("0000000001-25-000001", pages=8)
    cands = [
        c
        for c in sec_align.align(sub, num, pre, html, sec_screen.signed(gold_value))
        if isinstance(c, sec_align.Candidate)
    ]
    segs = sec_pages.segments(html)
    assert all(s.paths is segs[0].paths for s in segs) and not segs[0].paths
    for s in segs:
        sec_pages.accept(s, cands)
    # 12 statement facts get a path; the 25 note facts (no candidate of that name) never do
    assert set(segs[0].paths) == {c.dom_path for c in cands} and len(segs[0].paths) == 12


def test_segment_without_candidates_is_judged_without_copying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sub, num, pre, html = slow_filing("0000000001-25-000001", pages=5)
    cands = [
        c
        for c in sec_align.align(sub, num, pre, html, sec_screen.signed(gold_value))
        if isinstance(c, sec_align.Candidate)
    ]
    segs = sec_pages.segments(html)

    def boom(seg: Any) -> Any:
        raise AssertionError("copied a segment that holds no candidate")

    monkeypatch.setattr(sec_pages, "_clone", boom)
    assert sec_pages.accept(segs[4], cands) == ([], [])
    with pytest.raises(AssertionError, match="no candidate"):  # mutant guard: the path is live
        sec_pages.accept(segs[0], cands)
