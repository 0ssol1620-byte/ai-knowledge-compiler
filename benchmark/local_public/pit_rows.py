"""SEC point-in-time corpus rows (LPC design 4, addendum fix 4, WO-LPC-6A).

Validity is the inline-XBRL context of the SAME accession (UTC midnight, end exclusive) or null.
`recorded_at = available_at = accepted_at(adsh)`; an unresolved acceptance writes no row.
First reporting is joined on the FSDS identifier (cik, tag, ddate, qtrs, uom) and written to
`rows_index.jsonl`, never into a corpus row. `ddate` is month-rounded: it is an identifier there.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib
import io
import json
import sys
import zipfile
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from benchmark.local_public import sec_align, sec_time, sources

TENANT = "lpc-sec"
CAP = 100_000
BASIS = "ixbrl_context_date_at_utc_midnight"
FIRST_QUARTER, LAST_QUARTER = "2019q1", "2026q1"


class PitError(Exception):
    pass


def _midnight(iso: str, plus_days: int = 0) -> str:
    d = date.fromisoformat(iso) + timedelta(days=plus_days)
    return datetime(d.year, d.month, d.day, tzinfo=UTC).isoformat()


def _dated(
    row: Callable[..., dict[str, Any]], r: dict[str, str], start: str | None, end: str
) -> dict[str, Any]:
    if start is None:
        return row(r, f"I{end}", f"as of {end}.", _midnight(end), _midnight(end, 1))
    return row(r, f"{start}_{end}", f"{start} to {end}.", _midnight(start), _midnight(end, 1))


def _month_row(row: Callable[..., dict[str, Any]], r: dict[str, str]) -> dict[str, Any]:
    text = (
        f"period ending {r['ddate'][:4]}-{r['ddate'][4:6]} "
        f"(month as rounded by FSDS), {r['qtrs']} quarters."
    )
    return row(r, f"{r['ddate']}m{r['qtrs']}", text, None, None)


def _context_span(
    r: dict[str, str], ctxs: dict[str, Any], facts: list[Any]
) -> tuple[str | None, str] | None:
    """The one non-dimensional context of this accession whose dates match the FSDS row
    (sec_align rules 1-2); None when none or several do."""
    q, found = int(r["qtrs"]), set()
    for f in facts:
        c = ctxs.get(f.ctx)
        if f.name != r["tag"] or f.hidden or c is None or c.segment:
            continue
        if (q == 0) != (c.start is None):
            continue
        e = date.fromisoformat(c.end)
        if q and round(((e - date.fromisoformat(c.start or c.end)).days + 1) / 91.3125) != q:
            continue
        ne = sec_align.nearest_month_end(e)
        if ne is not None and ne.strftime("%Y%m%d") == r["ddate"]:
            found.add((c.start, c.end))
    return next(iter(found)) if len(found) == 1 else None


def filing_rows(
    sub: dict[str, str],
    num_rows: list[dict[str, str]],
    pre_rows: list[dict[str, str]],
    html_bytes: bytes,
    gold_value: Callable[[dict[str, Any]], Any],
    accepted: datetime | None,
    tenant: str = TENANT,
    reasons: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(corpus rows, join keys) of one filing; a key is every presented non-dimensional num row.

    `accepted` None -> ([], []) and the caller counts `acceptance_unresolved`.
    `reasons` (optional, mutated) counts iXBRL rows written without a screen-field candidate,
    by the `sec_align` reason."""
    if accepted is None:
        return [], []
    if accepted.tzinfo is None or accepted.utcoffset() is None:
        raise PitError("accepted must be timezone-aware")
    stamp = accepted.astimezone(UTC).isoformat()
    adsh, cik, name = sub["adsh"], sub["cik"].lstrip("0") or "0", sub["name"]
    plabels = {
        (p["tag"], p["version"]): p["plabel"] for p in pre_rows if p["stmt"] in sec_align.STMTS
    }
    presented = [
        r
        for r in num_rows
        if not r["segments"] and not r["coreg"] and (r["tag"], r["version"]) in plabels
    ]
    keys = [
        {
            "cik": cik,
            "tag": r["tag"],
            "ddate": r["ddate"],
            "ddate_precision": "month_rounded",
            "qtrs": r["qtrs"],
            "uom": r["uom"],
            "adsh": adsh,
            "accepted_at": stamp,
        }
        for r in presented
    ]

    def row(
        r: dict[str, str], period_key: str, text: str, vf: str | None, vt: str | None
    ) -> dict[str, Any]:
        lid = f"{tenant}/{cik}/{r['tag']}/{period_key}/{r['uom']}@{adsh}"
        return {
            "tenant": tenant,
            "logical_id": lid,
            "source_id": adsh,
            "source_version_id": adsh,
            "evidence_id": f"ev:{lid}",
            "text": f"{name}: {plabels[(r['tag'], r['version'])]}: {r['value']} {r['uom']}, {text}",
            "authority": "official",
            "metadata": {
                "valid_from": vf,
                "valid_to": vt,
                "recorded_at": stamp,
                "available_at": stamp,
            },
            "_key": (cik, r["tag"], r["ddate"], r["qtrs"], r["uom"]),
        }

    rows: list[dict[str, Any]] = []
    if sub["instance"].endswith("_htm.xml"):
        cands: dict[tuple[str, ...], list[sec_align.Candidate]] = {}
        why: dict[tuple[str, str, str], str] = {}
        for c in sec_align.align(sub, num_rows, pre_rows, html_bytes, gold_value):
            if isinstance(c, sec_align.Candidate):
                f = c.fsds
                k5 = (f["tag"], f["version"], f["ddate"], f["qtrs"], f["uom"])
                cands.setdefault(k5, []).append(c)
            else:
                why[(c.tag, c.ddate, c.qtrs)] = c.reason
        ctxs, facts, _ = sec_align.contexts(html_bytes)
        for r in presented:
            ident = (r["tag"], r["version"], r["ddate"], r["qtrs"], r["uom"])
            seen: set[tuple[str | None, str]] = set()
            for c in cands.get(ident, []):
                if (c.start, c.end) in seen:  # one fact printed in several places is one row
                    continue
                seen.add((c.start, c.end))
                rows.append(_dated(row, r, c.start, c.end))
            if ident in cands:
                continue
            # not accepted as a screen field (page rules 4-10): still a presented fact. Dates
            # only if the same accession's context matches on rules 1-2, else month basis.
            if reasons is not None:
                k = why.get((r["tag"], r["ddate"], r["qtrs"]), "unknown")
                reasons[k] = reasons.get(k, 0) + 1
            span = _context_span(r, ctxs, facts)
            rows.append(_dated(row, r, *span) if span else _month_row(row, r))
    else:
        rows.extend(_month_row(row, r) for r in presented)
    return rows, keys


def assemble(
    per_filing: Iterable[tuple[list[dict[str, Any]], list[dict[str, Any]]]],
    unresolved_keys: Iterable[tuple[str, str, str, str, str]] = (),
    cap: int = CAP,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Corpus rows (without `_key`) and index rows. Duplicate logical id or over-cap raises.

    `first_reported_by` = earliest `accepted_at` among filings carrying the FSDS key. A key that
    an unresolved-acceptance filing also carries gets None: its order is unknown, so no guess."""
    first: dict[tuple[str, ...], tuple[str, str]] = {}
    corpus: list[dict[str, Any]] = []
    for rows, keys in per_filing:
        for k in keys:
            key = (k["cik"], k["tag"], k["ddate"], k["qtrs"], k["uom"])
            if key not in first or k["accepted_at"] < first[key][0]:
                first[key] = (k["accepted_at"], k["adsh"])
        corpus.extend(rows)
        if len(corpus) > cap:
            raise PitError(f"row cap {cap} exceeded")
    ids = [r["logical_id"] for r in corpus]
    if len(set(ids)) != len(ids):
        dup = next(i for i in ids if ids.count(i) > 1)
        raise PitError(f"duplicate logical id: {dup}")
    blind = set(unresolved_keys)
    index = [
        {
            "logical_id": r["logical_id"],
            "adsh": r["source_id"],
            "fsds_key": dict(
                zip(("cik", "tag", "ddate", "qtrs", "uom"), r["_key"], strict=True),
                ddate_precision="month_rounded",
            ),
            "first_reported_by": None if r["_key"] in blind else first[r["_key"]][1],
        }
        for r in corpus
    ]
    for r in corpus:
        del r["_key"]
    return corpus, index


# ---------------------------------------------------------------- CLI over the pinned sources


def _load_ciks(path: Path) -> set[str]:
    data = json.loads(path.read_text("utf-8"))
    raw = data["ciks"] if isinstance(data, dict) and set(data) == {"ciks"} else data
    if (
        not isinstance(raw, list)
        or not raw
        or not all(
            (isinstance(c, int) and not isinstance(c, bool)) or (isinstance(c, str) and c.isdigit())
            for c in raw
        )
    ):
        raise PitError(
            'exclude-ciks must be a non-empty list of numeric CIKs or {"ciks": [...]}; '
            "refusing to guess the holdout boundary"
        )
    return {str(c).lstrip("0") or "0" for c in raw}


def pick_ciks(all_ciks: set[str], excluded: set[str], k: int, seed: int) -> set[str]:
    pool = sorted(all_ciks - excluded)
    pool.sort(key=lambda c: hashlib.sha256(f"{seed}:{c}".encode()).hexdigest())
    return set(pool[:k])


def _group(zf: zipfile.ZipFile, name: str, adshes: set[str]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    with zf.open(name) as f:
        for r in csv.DictReader(
            io.TextIOWrapper(f, "utf-8", errors="replace"), delimiter="\t", quoting=csv.QUOTE_NONE
        ):
            if r["adsh"] in adshes:
                out.setdefault(r["adsh"], []).append(r)
    return out


def build(
    out: Path,
    exclude_ciks: Path | None,
    ciks: int = 12,
    seed: int = 0,
    manifest: Path = sources.DEFAULT_MANIFEST,
    gold_value: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, int]:
    if exclude_ciks is None:
        raise PitError("--exclude-ciks is required")
    if gold_value is None:
        raise PitError("the scorer's gold_value is not available; refusing to guess")
    excluded = _load_ciks(exclude_ciks)
    lo = sources.configure(manifest)
    c2 = [
        json.loads(x)
        for x in sources.verified_path("c2_manifest").read_text("utf-8").splitlines()
        if x
    ]
    chosen = pick_ciks({str(r["cik"]).lstrip("0") for r in c2}, excluded, ciks, seed)
    wanted = {r["adsh"] for r in c2 if str(r["cik"]).lstrip("0") in chosen}
    with zipfile.ZipFile(sources.open_verified("sec_submissions_bulk")) as bz:
        bulk = sec_time.bulk_index(bz)
    quarters = sorted(
        e["name"].split("/", 1)[1]
        for e in lo.manifest["entries"]
        if e["name"].startswith("sec_fsds/")
        and FIRST_QUARTER <= e["name"].split("/", 1)[1] <= LAST_QUARTER
    )
    per_filing: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
    unresolved: list[tuple[str, str, str, str, str]] = []
    reasons: dict[str, int] = {}
    stats = {"filings": 0, "acceptance_unresolved": 0, "filing_missing": 0}
    for q in quarters:
        with zipfile.ZipFile(sources.open_verified(f"sec_fsds/{q}")) as zf:
            subs = _group(zf, "sub.txt", wanted)
            if not subs:
                continue
            nums, pres = _group(zf, "num.txt", set(subs)), _group(zf, "pre.txt", set(subs))
        for adsh, (sub,) in subs.items():
            if sub["cik"].lstrip("0") not in chosen:
                continue
            html = b""
            if sub["instance"].endswith("_htm.xml"):
                try:
                    with sources.open_verified(f"sec_filing/{adsh}") as raw:
                        html = gzip.decompress(raw.read())
                except sources.SourceMissing:
                    stats["filing_missing"] += 1
                    continue
            acc = sec_time.accepted_at(sub["accepted"], bulk.get(adsh))
            rows, keys = filing_rows(
                sub, nums.get(adsh, []), pres.get(adsh, []), html, gold_value, acc, reasons=reasons
            )
            if acc is None:
                stats["acceptance_unresolved"] += 1
                unresolved += [
                    (sub["cik"].lstrip("0") or "0", n["tag"], n["ddate"], n["qtrs"], n["uom"])
                    for n in nums.get(adsh, [])
                    if not n["segments"] and not n["coreg"]
                ]
            stats["filings"] += 1
            per_filing.append((rows, keys))
    corpus, index = assemble(per_filing, unresolved)
    out.mkdir(parents=True, exist_ok=True)
    for name, items in (("corpus.jsonl", corpus), ("rows_index.jsonl", index)):
        with (out / name).open("x", encoding="utf-8", newline="\n") as f:
            f.writelines(json.dumps(i, sort_keys=True) + "\n" for i in items)
    (out / "pit_rows_meta.json").write_text(
        json.dumps(
            {
                "valid_time_basis": BASIS,
                "lpc_manifest_sha256": lo.manifest["manifest_sha256"],
                "ixbrl_rows_without_screen_candidate_by_align_reason": reasons,
                "rows": len(corpus),
                "ciks": sorted(chosen),
                "excluded_ciks_sha256": hashlib.sha256(exclude_ciks.read_bytes()).hexdigest(),
                **stats,
            },
            sort_keys=True,
            indent=1,
        ),
        encoding="utf-8",
    )
    return {"rows": len(corpus), **stats}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pit_rows")
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--ciks", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--exclude-ciks", type=Path)
    ap.add_argument("--manifest", type=Path, default=sources.DEFAULT_MANIFEST)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        gold_value = importlib.import_module("benchmark.screen.critical_fields").gold_value
    except (ImportError, AttributeError):
        gold_value = None
    try:
        print(build(a.out, a.exclude_ciks, a.ciks, a.seed, a.manifest, gold_value))
    except (PitError, sources.SourceError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
