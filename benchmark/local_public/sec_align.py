"""FSDS rows <-> inline-XBRL facts of the same accession (LPC design 2.2, addendum fixes 1 and 3).

Pure functions over file objects and bytes. FSDS `ddate`/`period` are month-end rounded, so they are
used to MATCH only; every recorded date is the inline-XBRL context date of the same accession.
The scorer's normaliser is injected (`gold_value`), never imported or copied.
"""

from __future__ import annotations

import calendar
import csv
import io
import re
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from lxml import etree

IX = "http://www.xbrl.org/2013/inlineXBRL"
XI = "http://www.xbrl.org/2003/instance"
STMTS = ("BS", "IS", "CF", "CI", "EQ")
ANNUAL_FORMS = ("10-K", "10-K/A", "10-KT", "20-F")
_Q = {"Q1": 1, "Q2": 2, "Q3": 3}
_DASHES = {"-", chr(0x2013), chr(0x2014), chr(0x2212)}
_NUMBER = re.compile(r"^(\d{1,3}(,\d{3})+|\d+)?(\.\d+)?$")
_SYMBOLS_ONLY = re.compile(r"^[\s$€£¥(\-\u2212]*$")
_CLOSE_ONLY = re.compile(r"^[\s)%]*$")
_CUR = "$€£¥"


@dataclass(frozen=True)
class Candidate:
    """One accepted fact element. A row whose fact is printed in several places gives several."""

    field_id: str
    adsh: str
    tag: str
    anchor: str
    gold: str
    context_id: str
    start: str | None
    end: str
    scale: int
    sign: str | None
    sign_basis: str
    ddate_rounded: bool
    dom_path: str
    fsds: dict[str, str]
    kind: str = "number"


@dataclass(frozen=True)
class Excluded:
    reason: str
    adsh: str
    tag: str
    ddate: str
    qtrs: str


@dataclass
class _Fact:
    el: Any
    name: str
    ctx: str
    hidden: bool


@dataclass
class _Ctx:
    start: str | None
    end: str
    segment: bool


@dataclass
class _Probe:
    reason: str | None = None
    cand: Candidate | None = None


def fsds_rows(
    zf: zipfile.ZipFile, adsh: str
) -> tuple[dict[str, str] | None, list[dict[str, str]], list[dict[str, str]]]:
    """Stream sub/num/pre of one quarterly FSDS ZIP, keeping only `adsh`."""

    def rows(name: str) -> Iterator[dict[str, str]]:
        with zf.open(name) as f:
            reader = csv.DictReader(
                io.TextIOWrapper(f, "utf-8", errors="replace"),
                delimiter="\t",
                quoting=csv.QUOTE_NONE,
            )
            for r in reader:
                if r["adsh"] == adsh:
                    yield r

    return next(rows("sub.txt"), None), list(rows("num.txt")), list(rows("pre.txt"))


def _local(el: Any) -> str:
    """Element name without its namespace; never raises, for any node of either parser.

    `{ns}td` and `td` -> "td". An unbound prefix keeps the whole name: lxml's XML recover parser
    names it "zz:td", and an HTML parser (lxml's, and Chromium's for the printed excerpt) binds no
    prefix at all, so every `ix:*` element of an excerpt is "ix:...". No HTML element name has a
    colon, so such a name never matches td/tr/table/style/body. Comment, PI, entity -> "".
    (`etree.QName` raised ValueError on the colon: R2 run 2, `ix:continuation`.)
    """
    return el.tag.rpartition("}")[2] if isinstance(el.tag, str) else ""


def _text(el: Any) -> str:
    return " ".join("".join(el.itertext()).split())


def _hidden(f: Any) -> bool:
    return any(
        (a.tag == f"{{{IX}}}hidden")
        or "display:none" in (a.get("style") or "").replace(" ", "").lower()
        for a in f.iterancestors()
    )


def contexts(html_bytes: bytes) -> tuple[dict[str, _Ctx], list[_Fact], Any]:
    """Contexts by id, every `ix:nonFraction` with a `hidden` flag, and the parsed root."""
    root = etree.fromstring(html_bytes, etree.XMLParser(huge_tree=True, recover=True))
    if root is None:
        raise ValueError("unparseable inline XBRL document")
    ctxs: dict[str, _Ctx] = {}
    for c in root.iter(f"{{{XI}}}context"):
        i, s, e = (c.find(f".//{{{XI}}}{t}") for t in ("instant", "startDate", "endDate"))
        if i is not None and i.text:
            ctxs[c.get("id", "")] = _Ctx(
                None, i.text.strip(), c.find(f".//{{{XI}}}segment") is not None
            )
        elif e is not None and s is not None and e.text and s.text:
            ctxs[c.get("id", "")] = _Ctx(
                s.text.strip(), e.text.strip(), c.find(f".//{{{XI}}}segment") is not None
            )
    facts = []
    for el in root.iter(f"{{{IX}}}nonFraction"):
        facts.append(
            _Fact(
                el, (el.get("name") or "").split(":")[-1], el.get("contextRef") or "", _hidden(el)
            )
        )
    return ctxs, facts, root


def _eom(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def nearest_month_end(d: date) -> date | None:
    """Closer of this month's end and the previous month's end; None on an exact tie."""
    a, pm = _eom(d.year, d.month), d.replace(day=1) - timedelta(days=1)
    da, db = (a - d).days, (d - pm).days
    return None if da == db else (a if da < db else pm)


def _d(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _back(dd: str, years: int) -> str:
    d = _d(dd)
    return _ymd(_eom(d.year - years, d.month))


def _statement_context(sub: dict[str, str], qtrs: int, ddate: str) -> bool:
    """Context-level test on rounded ddate.

    10-Q instant comparatives are the fiscal-year ends: the most recent month end of the `fye`
    month strictly before the period, and one year earlier (addendum fix 1:
    a January filer's fy=2025 ends 2025-01-31, so FYE is never derived from `fy`)."""
    form, p = sub["form"], sub["period"]
    if form in ANNUAL_FORMS:
        if qtrs == 4:
            return ddate in {p, _back(p, 1), _back(p, 2)}
        return qtrs == 0 and ddate in {p, _back(p, 1), _back(p, 2), _back(p, 3)}
    if form.startswith("10-Q") and sub["fp"] in _Q:
        if qtrs == 0:
            m, pd = int(sub["fye"][:2]), _d(p)
            last = _eom(pd.year, m)
            if last >= pd:
                last = _eom(pd.year - 1, m)
            return ddate in {p, _back(p, 1), _ymd(last), _ymd(_eom(last.year - 1, m))}
        return qtrs in (1, _Q[sub["fp"]]) and ddate in {p, _back(p, 1)}
    return False


def _cells(tr: Any) -> list[Any]:
    return [c for c in tr if _local(c) in ("td", "th")]


def _probe(
    el: Any,
    row: dict[str, str],
    pre: dict[str, str],
    sub: dict[str, str],
    ctx_id: str,
    c: _Ctx,
    rounded: bool,
    gold_value: Callable[[dict[str, Any]], Any],
    root: Any,
) -> _Probe:
    """Rules 10, 6, 5, 7, 8, 9 on one visible fact element; the first failing rule is the reason."""
    raw = _text(el)
    fmt = (el.get("format") or "").split(":")[-1]
    if (
        (raw and set(raw) <= _DASHES)
        or fmt in ("fixed-zero", "zerodash")
        or (fmt == "numwordsen" and raw.lower() == "none")
    ):
        return _Probe("zero_dash")
    if fmt not in ("", "num-dot-decimal", "numdotdecimal") or not raw or not _NUMBER.match(raw):
        return _Probe("unparseable_format")
    try:
        fsds_value = Decimal(row["value"])
        scale = int(el.get("scale") or 0)
    except (InvalidOperation, ValueError):
        return _Probe("fsds_unparseable")
    sign_attr = el.get("sign")
    if Decimal(raw.replace(",", "")).scaleb(scale) * (-1 if sign_attr == "-" else 1) != fsds_value:
        return _Probe("value_mismatch")
    # row position (8) is needed to read the shown sign (7): cells first, reasons keep rule order
    td = next((a for a in el.iterancestors() if _local(a) in ("td", "th")), None)
    tr = next((a for a in el.iterancestors() if _local(a) == "tr"), None)
    cells = _cells(tr) if tr is not None else []
    k = next((i for i, x in enumerate(cells) if x is td), -1)
    cell = _text(td) if td is not None else raw
    idx = max(cell.find(raw), 0)
    run_b: list[str] = []
    run_a: list[str] = []
    for x in reversed(
        cells[: max(k, 0)]
    ):  # contiguous symbol-only cells: "$" "(" before, ")" "%" after
        if not _SYMBOLS_ONLY.match(_text(x)):
            break
        run_b.insert(0, _text(x))
    for x in cells[k + 1 :] if k >= 0 else []:
        if not _CLOSE_ONLY.match(_text(x)):
            break
        run_a.append(_text(x))
    before = " ".join(run_b) + " " + cell[:idx]
    after = cell[idx + len(raw) :] + " " + " ".join(run_a)
    open_, close = re.search(r"\([\s$€£¥]*$", before), re.match(r"^\s*\)", after)
    if bool(open_) != bool(close):
        return _Probe("sign_unsupported")
    paren, minus = bool(open_), not open_ and bool(re.search(r"[\-\u2212][\s$€£¥]*$", before))
    shown_neg, fsds_neg = paren or minus, fsds_value < 0
    if shown_neg == fsds_neg:
        basis = "match"
    elif pre.get("negating") == "1":
        basis = "pre_negating"
    elif not shown_neg and sign_attr == "-":
        basis = "ix_sign_attribute"
    else:
        return _Probe("sign_unsupported")
    first = (
        next((f for f in tr.iter(f"{{{IX}}}nonFraction") if not _hidden(f)), None)
        if tr is not None
        else None
    )
    numeric_before = any(re.search(r"\d", _text(x)) for x in cells[1:k]) or bool(
        re.search(r"\d", cell[:idx])
    )
    if tr is None or first is not el or numeric_before:
        return _Probe("not_first_column" if tr is not None else "no_label")
    anchor = _text(cells[0]) if cells else ""
    if not anchor or cells[0] is td:
        return _Probe("no_label")
    sym = re.search(f"[{_CUR}]", before)
    digits = raw
    gold = (f"{sym.group(0)} " if sym else "") + (
        f"({digits})" if paren else f"-{digits}" if minus else digits
    )
    gold += "%" if after.lstrip().startswith("%") else ""
    shown = Decimal(digits.replace(",", "")) * (-1 if shown_neg else 1)
    try:
        got = Decimal(str(gold_value({"kind": "number", "value": gold, "anchor": anchor})))
    except Exception:
        return _Probe("gold_unparseable")
    if got != shown:
        return _Probe("gold_roundtrip_mismatch")
    key = f"I{c.end}" if c.start is None else f"{c.start}_{c.end}"
    return _Probe(
        None,
        Candidate(
            field_id=f"{sub['adsh']}:{row['tag']}:{key}:{row['uom']}",
            adsh=sub["adsh"],
            tag=row["tag"],
            anchor=anchor,
            gold=gold,
            context_id=ctx_id,
            start=c.start,
            end=c.end,
            scale=scale,
            sign=sign_attr,
            sign_basis=basis,
            ddate_rounded=rounded,
            dom_path=root.getroottree().getpath(el),
            fsds={
                "tag": row["tag"],
                "version": row.get("version", ""),
                "ddate": row["ddate"],
                "ddate_precision": "month_rounded",
                "qtrs": row["qtrs"],
                "uom": row["uom"],
                "value": row["value"],
                "stmt": pre.get("stmt", ""),
                "negating": pre.get("negating", ""),
            },
        ),
    )


_ORDER = [
    "zero_dash",
    "unparseable_format",
    "fsds_unparseable",
    "value_mismatch",
    "sign_unsupported",
    "not_first_column",
    "no_label",
    "gold_unparseable",
    "gold_roundtrip_mismatch",
]


def align(
    sub: dict[str, str],
    num_rows: list[dict[str, str]],
    pre_rows: list[dict[str, str]],
    html_bytes: bytes,
    gold_value: Callable[[dict[str, Any]], Any],
) -> list[Candidate | Excluded]:
    """One Excluded per rejected num row, one Candidate per accepted fact element of a row.

    `gold_value(field_dict)` is the scorer's normaliser: field dict in, signed number out.
    """
    if any(x["adsh"] != sub["adsh"] for x in (*num_rows, *pre_rows)):
        raise ValueError("alignment is by the same adsh only")
    presented: dict[tuple[str, str], dict[str, str]] = {}
    for p in pre_rows:
        if p["stmt"] in STMTS:
            presented.setdefault((p["tag"], p["version"]), p)
    ctxs, facts, root = (
        contexts(html_bytes) if sub["instance"].endswith("_htm.xml") else ({}, [], None)
    )
    out: list[Candidate | Excluded] = []
    for r in num_rows:

        def no(reason: str, r: dict[str, str] = r) -> None:
            out.append(Excluded(reason, sub["adsh"], r["tag"], r["ddate"], r["qtrs"]))

        pre = presented.get((r["tag"], r["version"]))
        if r["segments"]:
            no("dimensional")
        elif r["coreg"]:
            no("coregistrant")
        elif pre is None:
            no("not_presented")
        elif not sub["instance"].endswith("_htm.xml"):
            no("no_inline_xbrl")
        else:
            _row(sub, r, pre, ctxs, facts, root, gold_value, out, no)
    return out


def _row(
    sub: dict[str, str],
    r: dict[str, str],
    pre: dict[str, str],
    ctxs: dict[str, _Ctx],
    facts: list[_Fact],
    root: Any,
    gold_value: Callable[[dict[str, Any]], Any],
    out: list[Candidate | Excluded],
    no: Callable[[str], None],
) -> None:
    q, dd = int(r["qtrs"]), r["ddate"]
    matched: dict[tuple[str | None, str], list[_Fact]] = {}
    hidden_hit = tie = False
    for f in facts:
        c = ctxs.get(f.ctx)
        if f.name != r["tag"] or c is None or c.segment or (q == 0) != (c.start is None):
            continue
        e = date.fromisoformat(c.end)
        if q and round(((e - date.fromisoformat(c.start or c.end)).days + 1) / 91.3125) != q:
            continue
        ne = nearest_month_end(e)
        if ne is None:
            tie |= dd in (_ymd(_eom(e.year, e.month)), _ymd(e.replace(day=1) - timedelta(days=1)))
        elif _ymd(ne) == dd:
            if f.hidden:
                hidden_hit = True
            else:
                matched.setdefault((c.start, c.end), []).append(f)
    if len(matched) > 1:
        return no("context_ambiguous")
    if not matched:
        return no(
            "ddate_rounding_ambiguous" if tie else "hidden_only" if hidden_hit else "no_ix_fact"
        )
    (_, end), fs = next(iter(matched.items()))
    if not _statement_context(sub, q, dd):
        return no("not_statement_context")
    probes = [
        _probe(
            f.el,
            r,
            pre,
            sub,
            f.ctx,
            ctxs[f.ctx],
            _ymd(date.fromisoformat(end)) != dd,
            gold_value,
            root,
        )
        for f in fs
    ]
    good = [p.cand for p in probes if p.cand is not None]
    if good:
        out.extend(good)
    else:
        no(max((p.reason or "" for p in probes), key=_ORDER.index))
