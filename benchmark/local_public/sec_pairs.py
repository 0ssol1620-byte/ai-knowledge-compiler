"""SEC revision pairs in the U06 `run.py` format (WO-LPC-5; LPC design 3, addendum P5, Amendment 4).

Documents are template-rendered from FSDS rows (one per `(cik, stmt)`, one region per presented,
non-dimensional `num` row). Strata come from the region diff of the documents actually built, never
from the filing form. `--exclude-ciks` is required; the 48 amendment-pair companies are reserved by
the caller (they are simply absent from that list). Real data is read only through
`benchmark.local_public.sources`.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import sys
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from akc_product_core.contracts import ProductCoreDocument
from pydantic import TypeAdapter

from benchmark.local_public import sources
from benchmark.local_public.sec_align import STMTS, contexts, fsds_rows, nearest_month_end
from benchmark.local_public.sec_time import accepted_at, bulk_index
from benchmark.revision_pairs.to_product_core import make_doc

RESTATED = "sec_amendment_restated"
SAME_VALUES = "sec_amendment_same_values"
SUCC_10K = "sec_successor_10k"
SUCC_10Q = "sec_successor_10q"
QUOTAS = {RESTATED: 15, SAME_VALUES: 33, SUCC_10K: 26, SUCC_10Q: 26}
# ponytail: successor = same CIK, same form, next period within a plain day gap; no calendar logic
_GAP_DAYS = {"10-K": (300, 430), "10-Q": (60, 130)}
_DOCS = TypeAdapter(tuple[ProductCoreDocument, ...])
DocMap = dict[tuple[int, str], ProductCoreDocument]


class PairError(ValueError):
    """A pair that must not be built (reversed order, wrong CIK, missing exclusion list)."""


class _NoExact(Exception):
    pass


@dataclass(frozen=True)
class Side:
    sub: dict[str, str]
    num: list[dict[str, str]]
    pre: list[dict[str, str]]
    html: bytes | None = None  # filed inline-XBRL bytes, when the filing has them

    @property
    def ixbrl(self) -> bool:
        return self.html is not None and self.sub["instance"].endswith("_htm.xml")


@dataclass(frozen=True)
class Case:
    case_id: str
    stratum: str
    cik: int
    before: tuple[ProductCoreDocument, ...]
    after: tuple[ProductCoreDocument, ...]
    before_adsh: str
    after_adsh: str
    date_basis: str
    added_regions: int = 0
    removed_regions: int = 0


@dataclass(frozen=True)
class Dropped:
    reason: str
    key: str


def _exact_dates(side: Side, row: dict[str, str]) -> tuple[str | None, str]:
    """(start, end) of the one non-dimensional iXBRL context that matches the FSDS row."""
    ctxs, facts, _ = contexts(side.html or b"")
    q, found = int(row["qtrs"]), set()
    for f in facts:
        c = ctxs.get(f.ctx)
        if f.name != row["tag"] or c is None or c.segment or (q == 0) != (c.start is None):
            continue
        e = date.fromisoformat(c.end)
        if q and round(((e - date.fromisoformat(c.start or c.end)).days + 1) / 91.3125) != q:
            continue  # design 2.2 rule 2: the context length must equal qtrs
        ne = nearest_month_end(e)
        if ne is not None and ne.strftime("%Y%m%d") == row["ddate"]:
            found.add((c.start, c.end))
    if len(found) != 1:
        raise _NoExact
    return next(iter(found))


def _regions(side: Side, basis: str) -> dict[str, list[tuple[str, str]]]:
    """stmt -> [(region_id, text)]; ids are unique per stmt even under duplicate `pre` lines."""
    first: dict[tuple[str, str, str], dict[str, str]] = {}
    for line in sorted(side.pre, key=lambda r: int(r["line"])):
        if line["stmt"] in STMTS:
            first.setdefault((line["tag"], line["version"], line["stmt"]), line)
    out: dict[str, list[tuple[str, str]]] = {}
    seen: set[tuple[str, str]] = set()
    for r in side.num:
        if r["segments"] or r["coreg"] or not r["value"]:
            continue
        for stmt in STMTS:
            p = first.get((r["tag"], r["version"], stmt))
            if p is None:
                continue
            ddate, q = r["ddate"], int(r["qtrs"])
            if basis == "exact":
                start, end = _exact_dates(side, r)
                when = f"{start} to {end}" if start else f"as of {end}"
            else:
                when = (
                    f"period ending {ddate[:4]}-{ddate[4:6]} (month as rounded by FSDS), "
                    f"{q} quarters"
                )
            rid = re.sub(r"[^A-Za-z0-9._:-]", "-", f"{r['tag']}-{ddate}m-{q}-{r['uom']}")
            if (stmt, rid) in seen:  # same tag in another version: keep ids unique by pre.line
                rid = f"{rid}-l{p['line']}"
            seen.add((stmt, rid))
            out.setdefault(stmt, []).append(
                (rid, f"{p['plabel']}: {r['value']} {r['uom']}, {when}.")
            )
    return out


def _docs(side: Side, basis: str, at: datetime) -> DocMap:
    cik = int(side.sub["cik"])
    return {
        (cik, stmt): make_doc(
            connector="sec-fsds",
            native_id=f"{cik}-{stmt}",
            title=f"{cik} {stmt} (template-rendered from FSDS)",
            parts=parts,
            key_prefix="sec-fsds",
            version=side.sub["adsh"],
        ).model_copy(
            # the compiler derives both ids from native_id and content; make_doc's would be refused.
            # The accession stays in immutable_object_key and in the manifest provenance.
            update={"available_at": at, "source_id": None, "source_version_id": None}
        )
        for stmt, parts in _regions(side, basis).items()
    }


def _build(sides: tuple[Side, Side], bulk: dict[str, str]) -> tuple[str, DocMap, DocMap] | str:
    """Both sides' documents on one date basis, or the reason the pair is dropped."""
    ats = []
    for s in sides:
        at = accepted_at(s.sub["accepted"], bulk.get(s.sub["adsh"]))
        if at is None:
            return "acceptance_unresolved"
        ats.append(at)
    # both sides iXBRL and every row dated by its own context -> exact; anything else -> month
    if all(s.ixbrl for s in sides):
        try:
            return "exact", _docs(sides[0], "exact", ats[0]), _docs(sides[1], "exact", ats[1])
        except _NoExact:
            pass
    return "month", _docs(sides[0], "month", ats[0]), _docs(sides[1], "month", ats[1])


def _ids(doc: ProductCoreDocument) -> dict[str, str]:
    return {r.region_id: r.text for r in doc.regions}


def amendment_case(original: Side, amendment: Side, bulk: dict[str, str]) -> Case | Dropped:
    """10-K -> 10-K/A: the amendment's `(cik, stmt)` documents replace the original's."""
    key = f"{original.sub['adsh']}>{amendment.sub['adsh']}"
    if original.sub["cik"] != amendment.sub["cik"]:
        raise PairError("an amendment pair is one CIK")
    built = _build((original, amendment), bulk)
    if isinstance(built, str):
        return Dropped(built, key)
    basis, old, new = built
    if not new:
        return Dropped("part_iii_only", key)
    changed = added = removed = 0
    for k, doc in new.items():
        was = _ids(old[k]) if k in old else {}
        now = _ids(doc)
        changed += sum(was[i] != t for i, t in now.items() if i in was)
        added += len(now.keys() - was.keys())
        removed += len(was.keys() - now.keys())
    after = {**old, **new}
    return Case(
        f"sec-amend-{original.sub['cik']}-{original.sub['adsh']}-{amendment.sub['adsh']}",
        RESTATED if changed else SAME_VALUES,
        int(original.sub["cik"]),
        tuple(old[k] for k in sorted(old)),
        tuple(after[k] for k in sorted(after)),
        original.sub["adsh"],
        amendment.sub["adsh"],
        basis,
        added,
        removed,
    )


def successor_case(
    earlier: Side, later: Side, stratum: str, bulk: dict[str, str]
) -> Case | Dropped:
    """Filing n -> filing n+1 of one CIK; ordered by period, a reversed pair is refused."""
    if stratum not in (SUCC_10K, SUCC_10Q):
        raise PairError(f"not a successor stratum: {stratum}")
    if earlier.sub["cik"] != later.sub["cik"]:
        raise PairError("a successor pair is one CIK")
    if earlier.sub["period"] >= later.sub["period"]:
        raise PairError(
            f"pair not ordered by period: {earlier.sub['period']} >= {later.sub['period']}"
        )
    key = f"{earlier.sub['adsh']}>{later.sub['adsh']}"
    built = _build((earlier, later), bulk)
    if isinstance(built, str):
        return Dropped(built, key)
    basis, old, new = built
    if not old or not new:
        return Dropped("no_presented_rows", key)
    return Case(
        f"sec-succ-{earlier.sub['cik']}-{earlier.sub['adsh']}-{later.sub['adsh']}",
        stratum,
        int(earlier.sub["cik"]),
        tuple(old[k] for k in sorted(old)),
        tuple(new[k] for k in sorted(new)),
        earlier.sub["adsh"],
        later.sub["adsh"],
        basis,
    )


def order(keys: Iterable[str], seed: str) -> list[str]:
    return sorted(keys, key=lambda k: hashlib.sha256(f"{seed}:{k}".encode()).hexdigest())


def fill(
    keys: Iterable[str],
    seed: str,
    quota: int,
    build: Callable[[str], Case | Dropped],
    accept: Callable[[Case], bool] = lambda _: True,
) -> tuple[list[Case], list[Dropped]]:
    """Seed-hash order, never padded: stops at the quota or when the keys run out."""
    cases: list[Case] = []
    drops: list[Dropped] = []
    for k in order(keys, seed):
        if len(cases) >= quota:
            break
        got = build(k)
        if isinstance(got, Dropped):
            drops.append(got)
        elif accept(got):
            cases.append(got)
    return cases, drops


class MissingSide(PairError):
    """A candidate names a filing the sources manifest does not hold."""


def drop_missing(build: Callable[[str], Case | Dropped]) -> Callable[[str], Case | Dropped]:
    """Only a missing filing is a counted drop; hash or read errors still stop the run."""

    def wrapped(k: str) -> Case | Dropped:
        try:
            return build(k)
        except MissingSide:
            return Dropped("side_not_in_manifest", k)

    return wrapped


def stratum_stats(
    candidates: int, got: list[Case], drops: list[Dropped], quota: int
) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    for d in drops:
        reasons[d.reason] = reasons.get(d.reason, 0) + 1
    return {
        "candidates": candidates,
        "built": len(got),
        "dropped_by_reason": reasons,
        "shortfall": max(quota - len(got), 0),
    }


def load_excluded(path: Path | None) -> frozenset[int]:
    """The holdout list is required: a missing file refuses the run."""
    if path is None or not path.is_file():
        raise PairError("--exclude-ciks is required and must be a readable file")
    raw = json.loads(path.read_text("utf-8"))
    return frozenset(int(x) for x in (raw["ciks"] if isinstance(raw, dict) else raw))


@dataclass
class Result:
    cases: list[Case] = field(default_factory=list)
    drops: list[Dropped] = field(default_factory=list)
    shortfall: dict[str, int] = field(default_factory=dict)
    strata: dict[str, dict[str, Any]] = field(default_factory=dict)


def write(
    result: Result,
    out: Path,
    *,
    requested_at: datetime,
    lpc_manifest_sha256: str,
    excluded: frozenset[int],
) -> Path:
    """Side files plus a `u06_equivalence.run` manifest with a provenance block."""
    if requested_at.tzinfo is None:
        raise PairError("requested_at must be timezone-aware")
    if any(c.cik in excluded for c in result.cases):
        raise PairError("an excluded CIK reached the output")
    (out / "sides").mkdir(parents=True, exist_ok=True)
    cases, prov = [], []
    for c in result.cases:
        refs = {}
        for side, docs in (("before", c.before), ("after", c.after)):
            data = _DOCS.dump_json(docs, by_alias=True)
            name = f"sides/{c.case_id}.{side}.json"
            (out / name).write_bytes(data)
            refs[side] = {"path": name, "sha256": hashlib.sha256(data).hexdigest()}
        cases.append({"case_id": c.case_id, "stratum": c.stratum, **refs})
        prov.append(
            {
                "case_id": c.case_id,
                "before_adsh": c.before_adsh,
                "after_adsh": c.after_adsh,
                "date_basis": c.date_basis,
                "added_regions": c.added_regions,
                "removed_regions": c.removed_regions,
            }
        )
    manifest = {
        "requested_at": requested_at.isoformat(),
        "cases": cases,
        "provenance": {
            "lpc_manifest_sha256": lpc_manifest_sha256,
            "excluded_ciks_sha256": hashlib.sha256(
                json.dumps(sorted(excluded)).encode()
            ).hexdigest(),
            "cases": prov,
            "counts": {s: sum(c.stratum == s for c in result.cases) for s in QUOTAS},
            "quotas": QUOTAS,
            "shortfall": result.shortfall,
            "strata": result.strata,
            "dropped": [{"key": d.key, "reason": d.reason} for d in result.drops],
        },
    }
    path = out / "manifest.json"
    path.write_text(json.dumps(manifest, indent=1), "utf-8")
    return path


# --------------------------------------------------------------- real data (read-only)


def _subs(loader: sources.Loader) -> dict[str, tuple[str, dict[str, str]]]:
    """adsh -> (quarter, sub row) over every pinned FSDS quarter."""
    out: dict[str, tuple[str, dict[str, str]]] = {}
    for name in sorted(n for n in loader._by_name if n.startswith("sec_fsds/")):
        with zipfile.ZipFile(loader.verified_path(name)) as zf, zf.open("sub.txt") as f:
            for r in csv.DictReader(
                io.TextIOWrapper(f, "utf-8", errors="replace"),
                delimiter="\t",
                quoting=csv.QUOTE_NONE,
            ):
                out[r["adsh"]] = (name.split("/")[1], r)
    return out


def _days(p1: str, p2: str) -> int:
    return (
        date(int(p2[:4]), int(p2[4:6]), int(p2[6:8]))
        - date(int(p1[:4]), int(p1[4:6]), int(p1[6:8]))
    ).days


def run(loader: sources.Loader, excluded: frozenset[int], seed: str) -> Result:  # pragma: no cover
    """Needs the real corpus; the pure parts above are what the unit tests pin."""
    subs = _subs(loader)
    with zipfile.ZipFile(loader.verified_path("sec_submissions_bulk")) as zf:
        bulk = bulk_index(zf)

    def side(adsh: str) -> Side:
        with zipfile.ZipFile(loader.verified_path(f"sec_fsds/{subs[adsh][0]}")) as zf:
            sub, num, pre = fsds_rows(zf, adsh)
        if sub is None:
            raise PairError(f"{adsh} is not in its FSDS quarter")
        html = None
        if sub["instance"].endswith("_htm.xml"):
            try:
                fh = loader.open_verified(f"sec_filing/{adsh}")
            except sources.SourceMissing as exc:
                raise MissingSide(f"filing not in manifest: {adsh}") from exc
            with gzip.open(fh) as g:
                html = g.read()
        return Side(sub, num, pre, html)

    ok = {a: s for a, (_, s) in subs.items() if int(s["cik"]) not in excluded}
    tenk = {(s["cik"], s["period"]): a for a, s in ok.items() if s["form"] == "10-K"}
    amend = [
        f"{tenk[(s['cik'], s['period'])]}>{a}"
        for a, s in ok.items()
        if s["form"] == "10-K/A" and (s["cik"], s["period"]) in tenk
    ]
    memo: dict[str, Case | Dropped] = {}

    def build_amend(k: str) -> Case | Dropped:
        if k not in memo:
            o, a = k.split(">")
            memo[k] = amendment_case(side(o), side(a), bulk)
        return memo[k]

    result = Result()
    for stratum in (RESTATED, SAME_VALUES):

        def wanted(c: Case, want: str = stratum) -> bool:
            return c.stratum == want

        got, drops = fill(amend, seed, QUOTAS[stratum], drop_missing(build_amend), wanted)
        result.strata[stratum] = stratum_stats(len(amend), got, drops, QUOTAS[stratum])
        result.cases += got
        result.drops += drops
    for stratum, form in ((SUCC_10K, "10-K"), (SUCC_10Q, "10-Q")):
        by_cik: dict[str, list[tuple[str, str]]] = {}
        for a, s in ok.items():
            if s["form"] == form:
                by_cik.setdefault(s["cik"], []).append((s["period"], a))
        lo, hi = _GAP_DAYS[form]
        keys = [
            f"{a1}>{a2}"
            for rows in by_cik.values()
            for (p1, a1), (p2, a2) in zip(sorted(rows), sorted(rows)[1:], strict=False)
            if lo <= _days(p1, p2) <= hi
        ]

        def build_succ(k: str, st: str = stratum) -> Case | Dropped:
            a1, a2 = k.split(">")
            return successor_case(side(a1), side(a2), st, bulk)

        got, drops = fill(keys, seed, QUOTAS[stratum], drop_missing(build_succ))
        result.strata[stratum] = stratum_stats(len(keys), got, drops, QUOTAS[stratum])
        result.cases += got
        result.drops += drops
    for stratum, quota in QUOTAS.items():
        have = sum(c.stratum == stratum for c in result.cases)
        if have < quota:
            result.shortfall[stratum] = quota - have
    return result


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude-ciks", type=Path)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sources-manifest", type=Path, default=sources.DEFAULT_MANIFEST)
    args = ap.parse_args(argv)
    try:
        excluded = load_excluded(args.exclude_ciks)
    except PairError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if sources._inside_git_tree(args.out):
        print("REFUSED: --out is inside a git work tree", file=sys.stderr)
        return 2
    loader = sources.configure(args.sources_manifest)
    result = run(loader, excluded, args.seed)
    path = write(
        result,
        args.out,
        requested_at=datetime.now(UTC),
        lpc_manifest_sha256=loader.manifest["manifest_sha256"],
        excluded=excluded,
    )
    print(json.dumps({"manifest": str(path), "shortfall": result.shortfall}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
