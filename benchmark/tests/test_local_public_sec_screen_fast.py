"""WO-LPC-R2P: the page selection is measured, uses the machine's cores and can resume.

Synthetic filings only (one of them shaped like the slow case: many filer pages, a flat body,
many tagged facts). No browser, no network, no real data.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from benchmark.local_public import sec_align, sec_pages, sec_screen, sources
from benchmark.screen.critical_fields import gold_value
from benchmark.tests.test_local_public_sec_screen import Fake, World, page_html

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


# ---------------------------------------------------------------- 2. cores, 3. resume

BREAK_DIV = b'<div style="page-break-after:always"></div>'


class FixedClock(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> FixedClock:
        return cls(2026, 11, 17, tzinfo=UTC)


def render_jitter(html: Path, pdf: Path) -> int:
    """One page; sleeps 0-120 ms by the file name, so a pool completes out of order."""
    time.sleep(hashlib.sha256(html.name.encode()).digest()[0] / 255 * 0.12)
    return render_one(html, pdf)


class Killed(BaseException):
    """A kill: not an Exception, so nothing on the way catches it as a render failure."""


_BUDGET = [0]


def render_until_killed(html: Path, pdf: Path) -> int:
    if not _BUDGET[0]:
        raise Killed
    _BUDGET[0] -= 1
    return render_one(html, pdf)


class BadFiling(Fake):
    """A loader whose pinned read of one filing fails, as a changed file would."""

    def open_verified(self, name: str) -> Any:
        if name.endswith("-000013"):
            raise sources.HashMismatch(f"{name}: expected aa, found bb")
        return super().open_verified(name)


def adversarial(tmp: Path) -> World:
    """Rank-order traps: a company whose first filings fail, one with a 4th filing, two companies
    whose pages are byte-identical (the later one in serial order is the duplicate), refusals."""
    w = World(tmp)
    w.filing("0000000001-25-000011", "100", html=page_html("s", script=True))
    w.filing("0000000001-25-000012", "100", html=page_html("n").replace(BREAK_DIV, b""))
    w.filing("0000000001-25-000013", "100")
    for i, kind in enumerate(("script", "few", "few", "good")):
        html = {"script": page_html("t", script=True), "few": page_html("f", rows=2)}.get(kind)
        w.filing(f"0000000002-25-00002{i}", "200", html=html, label=f"g{i}")
    w.filing("0000000003-25-000031", "300", label="dup")
    w.filing("0000000004-25-000041", "400", label="dup")
    w.filing("0000000005-25-000051", "500", html=page_html("v", rows=2))
    for c in range(6, 11):
        w.filing(f"00000000{c:02d}-25-0000{c:02d}", f"{c}00")
    return w


def build(w: World, out: Path, seed: str, **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = dict(
        seed=seed,
        screen_pages=3,
        eg04_pages=10,  # more than there is: every CIK is reached, so every trap is judged
        recorded_by="test",
        gold_value=gold_value,
        loader=w.loader(),
        render=render_jitter,
        pool=50,
    )
    args.update(kw)
    return sec_screen.build(out, **args)


def outputs(out: Path) -> dict[str, Any]:
    """Every output byte, and the receipt without its timing field and its absolute paths."""
    files = {
        p.relative_to(out).as_posix(): p.read_bytes()
        for p in sorted(out.rglob("*"))
        if p.is_file() and p.name != "receipt.json"
    }
    rec = json.loads((out / "receipt.json").read_text("utf-8"))
    del rec["created_at"]
    root = out.resolve()
    rec["outputs"] = [
        (Path(o["path"]).relative_to(root).as_posix(), o["sha256"]) for o in rec["outputs"]
    ]
    return {"files": files, "receipt": rec}


def outputs_of(w: World, out: Path, seed: str, workers: int) -> dict[str, Any]:
    build(w, out, seed, workers=workers)
    return outputs(out)


@pytest.mark.parametrize("seed", ["s1", "s2", "s3"])
def test_output_is_byte_identical_for_1_2_and_n_workers_and_any_completion_order(
    tmp_path: Path, seed: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sec_screen, "datetime", FixedClock)
    w = adversarial(tmp_path)
    got = {n: outputs_of(w, tmp_path / f"w{n}", seed, n) for n in (1, 2, 4)}
    assert got[2] == got[1] and got[4] == got[1]
    files = got[1]["files"]
    assert "journal.jsonl" not in files and not any(f.startswith("tmp/") for f in files)
    census = got[1]["receipt"]["census"]
    sel = set(json.loads(files["selected_ciks.json"])["ciks"])
    # the serial rules, stated independently: 100 is found at its one good filing whatever the
    # rank; 200's one good filing counts only if it is among its first 3 by rank; of the two
    # identical pages the company first in CIK rank order wins, the other is the duplicate
    assert 100 in sel
    tries = sorted(
        (f"0000000002-25-00002{i}" for i in range(4)),
        key=lambda a: sec_screen._rank(seed, "filing", a),
    )[: sec_screen.TRIES]
    assert (200 in sel) == ("0000000002-25-000023" in tries)
    first = min(("300", "400"), key=lambda c: sec_screen._rank(seed, "cik", c))
    assert sel & {300, 400} == {int(first)}
    assert census["reasons"]["source_hash_excluded_or_duplicate"] == 1


def killed_run(tmp: Path, monkeypatch: pytest.MonkeyPatch, pages: int = 3) -> tuple[World, Path]:
    monkeypatch.setattr(sec_screen, "datetime", FixedClock)
    w = adversarial(tmp)
    out = tmp / "killed"
    _BUDGET[:] = [pages]
    with pytest.raises(Killed):
        build(w, out, "s1", render=render_until_killed)
    assert (out / "journal.jsonl").exists() and not (out / "receipt.json").exists()
    assert not list(out.rglob("records.jsonl")) and not list(out.rglob("gold.sealed.jsonl"))
    return w, out


@pytest.mark.parametrize("pages_before_kill", [0, 1, 3, 5])
def test_a_killed_run_resumes_to_the_uninterrupted_output(
    tmp_path: Path, pages_before_kill: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    w, out = killed_run(tmp_path, monkeypatch, pages_before_kill)
    whole = outputs_of(w, tmp_path / "whole", "s1", 1)
    build(w, out, "s1", workers=2)  # the resumed run may use another worker count
    assert outputs(out) == whole


def test_resume_judges_only_what_the_journal_does_not_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    w, out = killed_run(tmp_path, monkeypatch)
    journalled = len((out / "journal.jsonl").read_bytes().splitlines()) - 1
    assert journalled >= 3
    capsys.readouterr()
    build(w, out, "s1", render=render_one)
    err = capsys.readouterr().err
    assert err.count("(journal)") == journalled and f"{journalled} decisions in the journal" in err
    assert not (out / "journal.jsonl").exists()


def _rechain(path: Path, edit: Any) -> None:
    """Rewrite a journal with `edit(bodies)` applied and every chain hash recomputed."""
    bodies = [json.loads(x)["body"] for x in path.read_bytes().splitlines()]
    edit(bodies)
    prev, text = "", ""
    for b in bodies:
        prev = sec_screen._chain(prev, b)
        text += json.dumps({"body": b, "chain": prev}, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_bytes(text.encode())


def test_a_journal_with_one_changed_byte_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w, out = killed_run(tmp_path, monkeypatch)
    j = out / "journal.jsonl"
    raw = j.read_bytes()
    at = raw.index(b'"filings_read": 1')
    j.write_bytes(raw[:at] + b'"filings_read": 2' + raw[at + 17 :])
    with pytest.raises(sec_screen.ScreenError, match="does not verify"):
        build(w, out, "s1", render=render_one)
    assert not (out / "receipt.json").exists()


def test_a_journal_from_another_seed_arguments_or_code_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w, out = killed_run(tmp_path, monkeypatch)
    with pytest.raises(sec_screen.ScreenError, match=r"different arguments \['seed'\]"):
        build(w, out, "s2", render=render_one)
    with pytest.raises(sec_screen.ScreenError, match=r"different arguments \['eg04_pages'\]"):
        build(w, out, "s1", render=render_one, eg04_pages=9)

    def other_code(bodies: list[dict[str, Any]]) -> None:
        bodies[0]["code_sha256"] = "0" * 64

    _rechain(out / "journal.jsonl", other_code)
    with pytest.raises(sec_screen.ScreenError, match="different code"):
        build(w, out, "s1", render=render_one)
    assert not (out / "receipt.json").exists()


def test_a_reordered_journal_is_refused_even_when_its_chain_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w, out = killed_run(tmp_path, monkeypatch)

    def swap(bodies: list[dict[str, Any]]) -> None:
        bodies[1], bodies[2] = bodies[2], bodies[1]

    _rechain(out / "journal.jsonl", swap)
    with pytest.raises(sec_screen.ScreenError, match="out of this run's order"):
        build(w, out, "s1", render=render_one)


def test_a_torn_last_line_is_dropped_and_judged_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w, out = killed_run(tmp_path, monkeypatch)
    whole = outputs_of(w, tmp_path / "whole", "s1", 1)
    j = out / "journal.jsonl"
    raw = j.read_bytes()
    j.write_bytes(raw[: len(raw) - 40])  # the crash cut the last write short
    build(w, out, "s1", render=render_one)
    assert outputs(out) == whole


def test_a_changed_journalled_page_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w, out = killed_run(tmp_path, monkeypatch)
    pdf = next(p for p in out.rglob("*.pdf"))
    pdf.write_bytes(pdf.read_bytes() + b"x")
    with pytest.raises(sec_screen.ScreenError, match="missing or changed"):
        build(w, out, "s1", render=render_one)


@pytest.mark.parametrize("workers", [1, 2])
def test_a_worker_that_raises_fails_the_run_with_no_final_output(
    tmp_path: Path, workers: int
) -> None:
    w = adversarial(tmp_path)
    base = cast(Fake, w.loader())
    loader = BadFiling(base.paths, base._by_name)
    out = tmp_path / "out"
    with pytest.raises(sources.HashMismatch, match="000013"):
        build(w, out, "s1", workers=workers, loader=loader)
    assert not (out / "receipt.json").exists() and not (out / "selected_ciks.json").exists()
    assert not list(out.rglob("records.jsonl")) and not list(out.rglob("gold.sealed.jsonl"))
    assert not (out / "tmp").exists()


def test_workers_below_one_refuse(tmp_path: Path) -> None:
    w = adversarial(tmp_path)
    with pytest.raises(sec_screen.ScreenError, match="workers"):
        build(w, tmp_path / "out", "s1", workers=0)
    assert not (tmp_path / "out").exists()
