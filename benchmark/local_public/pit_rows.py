"""SEC point-in-time corpus rows (LPC design 4, addendum fix 4, WO-LPC-6A).

Validity is the inline-XBRL context of the SAME accession (UTC midnight, end exclusive) or null.
`recorded_at = available_at = accepted_at(adsh)`; an unresolved acceptance writes no row.
First reporting is joined on the FSDS identifier (cik, tag, ddate, qtrs, uom) and written to
`rows_index.jsonl`, never into a corpus row. `ddate` is month-rounded: it is an identifier there.
The index also carries the num row's taxonomy `version` and the filer `name` (WO-D17-3), and
`tag_labels.jsonl` the FSDS `tag.txt` (custom, tlabel) of every (tag, version) the rows use.
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
            "_index": {"version": r["version"], "name": name},
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
            **r["_index"],
        }
        for r in corpus
    ]
    for r in corpus:
        del r["_key"], r["_index"]
    return corpus, index


# ---------------------------------------------------------------- CLI over the pinned sources


def _load_ciks(path: Path) -> set[str]:
    data = json.loads(path.read_text("utf-8"))
    return _ciks(data["ciks"] if isinstance(data, dict) and set(data) == {"ciks"} else data)


def _ciks(raw: Any) -> set[str]:
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


_TAG_LABELS = "tag_labels.jsonl"


def _tag_labels(
    zf: zipfile.ZipFile,
    member: str,
    wanted: set[tuple[str, str]],
    labels: dict[tuple[str, str], tuple[str, str, str]],
) -> None:
    """Add tag.txt (custom, tlabel) of `wanted` (tag, version) pairs to `labels`, mutated.

    A missing tag.txt, a custom flag other than 0/1 and two different labels for one
    (tag, version) are refused by name; a pair absent from tag.txt is left out (counted later)."""
    if "tag.txt" not in zf.namelist():
        raise PitError(f"tag.txt missing from {member}; refusing rows without standard labels")
    with zf.open("tag.txt") as f:
        reader = csv.DictReader(
            io.TextIOWrapper(f, "utf-8", errors="replace"), delimiter="\t", quoting=csv.QUOTE_NONE
        )
        if not {"tag", "version", "custom", "tlabel"} <= set(reader.fieldnames or ()):
            raise PitError(f"tag.txt in {member} lacks tag/version/custom/tlabel columns")
        for r in reader:
            k = (r["tag"], r["version"])
            if k not in wanted:
                continue
            if r["custom"] not in ("0", "1"):
                raise PitError(f"{member} tag.txt: custom flag {r['custom']!r} for {k}")
            v = (r["custom"], r["tlabel"] or "", member)
            if k in labels and labels[k][:2] != v[:2]:
                raise PitError(f"tag.txt rows for {k} differ between {labels[k][2]} and {member}")
            labels.setdefault(k, v)


def _rows_meta(rows_dir: Path, lo: sources.Loader) -> tuple[dict[str, Any], str]:
    """(meta, its sha256) of a rows dir built from the SAME manifest as `lo`; else refused."""
    path = rows_dir / "pit_rows_meta.json"
    try:
        raw = path.read_bytes()
        meta = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise PitError(f"cannot read {path}: {exc}") from exc
    recorded = meta.get("lpc_manifest_sha256") if isinstance(meta, dict) else None
    if recorded != lo.manifest["manifest_sha256"]:
        raise PitError(
            f"manifest {lo.manifest['manifest_sha256']} is not the one the rows in {rows_dir} "
            f"were built from ({recorded}); name that manifest with --manifest"
        )
    return meta, hashlib.sha256(raw).hexdigest()


def _jsonl(items: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(i, sort_keys=True) + "\n" for i in items).encode("utf-8")


def build(
    out: Path,
    exclude_ciks: Path | None,
    ciks: int = 12,
    seed: int = 0,
    manifest: Path | None = None,
    gold_value: Callable[[dict[str, Any]], Any] | None = None,
    rebuild_of: Path | None = None,
    holdout_of: Path | None = None,
) -> dict[str, int]:
    """`rebuild_of`: an earlier rows dir; refused unless its manifest and its corpus.jsonl bytes
    are reproduced. `holdout_of`: the dev rows dir; refused unless the manifest is the same and
    no dev CIK is drawn."""
    if exclude_ciks is None:
        raise PitError("--exclude-ciks is required")
    if gold_value is None:
        raise PitError("the scorer's gold_value is not available; refusing to guess")
    if manifest is None:
        raise PitError(
            "--manifest is required: name the manifest version the rows are built from "
            f"(the module default {sources.DEFAULT_MANIFEST.name} is not assumed)"
        )
    excluded = _load_ciks(exclude_ciks)
    lo = sources.configure(manifest)
    ref: dict[str, str] = {}
    old_corpus: bytes | None = None
    if rebuild_of is not None:
        _, ref["rebuild_of_meta_sha256"] = _rows_meta(rebuild_of, lo)
        try:
            old_corpus = (rebuild_of / "corpus.jsonl").read_bytes()
        except OSError as exc:
            raise PitError(f"cannot read the corpus being rebuilt: {exc}") from exc
    dev: set[str] = set()
    if holdout_of is not None:
        dev_meta, ref["holdout_of_meta_sha256"] = _rows_meta(holdout_of, lo)
        try:
            dev = _ciks(dev_meta["ciks"])
        except (KeyError, PitError) as exc:
            raise PitError(f"{holdout_of}/pit_rows_meta.json has no usable ciks list") from exc
    c2 = [
        json.loads(x)
        for x in sources.verified_path("c2_manifest").read_text("utf-8").splitlines()
        if x
    ]
    chosen = pick_ciks({str(r["cik"]).lstrip("0") for r in c2}, excluded, ciks, seed)
    if leaked := sorted(chosen & dev, key=int):
        raise PitError(f"holdout draw contains dev CIKs {leaked}; exclude them (exclude-union)")
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
    labels: dict[tuple[str, str], tuple[str, str, str]] = {}
    stats = {"filings": 0, "acceptance_unresolved": 0, "filing_missing": 0}
    for q in quarters:
        with zipfile.ZipFile(sources.open_verified(f"sec_fsds/{q}")) as zf:
            subs = _group(zf, "sub.txt", wanted)
            if not subs:
                continue
            nums, pres = _group(zf, "num.txt", set(subs)), _group(zf, "pre.txt", set(subs))
            _tag_labels(
                zf,
                f"sec_fsds/{q}",
                {(n["tag"], n["version"]) for a in subs for n in nums.get(a, [])},
                labels,
            )
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
    corpus_raw = _jsonl(corpus)
    if old_corpus is not None and corpus_raw != old_corpus:
        raise PitError(
            f"rebuild does not reproduce {rebuild_of}/corpus.jsonl: "
            f"{hashlib.sha256(old_corpus).hexdigest()} != {hashlib.sha256(corpus_raw).hexdigest()}"
        )
    used = {(i["fsds_key"]["tag"], i["version"]) for i in index}
    tag_rows = [
        {"tag": k[0], "version": k[1], "custom": v[0], "tlabel": v[1]}
        for k, v in sorted(labels.items())
        if k in used
    ]
    without_rows = sorted(chosen - {i["fsds_key"]["cik"] for i in index}, key=int)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (
        ("corpus.jsonl", corpus_raw),
        ("rows_index.jsonl", _jsonl(index)),
        (_TAG_LABELS, _jsonl(tag_rows)),
    ):
        with (out / name).open("xb") as f:
            f.write(data)
    (out / "pit_rows_meta.json").write_text(
        json.dumps(
            {
                "valid_time_basis": BASIS,
                "lpc_manifest_sha256": lo.manifest["manifest_sha256"],
                "ixbrl_rows_without_screen_candidate_by_align_reason": reasons,
                "rows": len(corpus),
                "ciks": sorted(chosen),
                "ciks_requested": ciks,
                "ciks_without_rows": without_rows,
                "seed": seed,
                "tag_labels": len(tag_rows),
                "excluded_ciks_sha256": hashlib.sha256(exclude_ciks.read_bytes()).hexdigest(),
                **ref,
                **stats,
            },
            sort_keys=True,
            indent=1,
        ),
        encoding="utf-8",
    )
    return {
        "rows": len(corpus),
        "tag_labels": len(tag_rows),
        "ciks_without_rows": len(without_rows),
        **stats,
    }


def exclude_union(out: Path, exclude_ciks: Path | None, rows_dir: Path | None) -> dict[str, Any]:
    """One exclude-file = the screen CIKs and the dev rows' CIKs, written once, with its sha256."""
    if exclude_ciks is None or rows_dir is None:
        raise PitError("exclude-union needs --exclude-ciks (screen) and --rows-dir (dev rows)")
    screen = _load_ciks(exclude_ciks)
    try:
        dev = _ciks(json.loads((rows_dir / "pit_rows_meta.json").read_text("utf-8"))["ciks"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PitError(f"cannot read the dev CIKs of {rows_dir}: {exc}") from exc
    raw = json.dumps({"ciks": sorted(screen | dev, key=int)}, indent=1).encode() + b"\n"
    with out.open("xb") as f:
        f.write(raw)
    return {
        "ciks": len(screen | dev),
        "screen": len(screen),
        "dev": len(dev),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pit_rows")
    ap.add_argument("cmd", choices=["build", "exclude-union"])
    ap.add_argument("--ciks", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--exclude-ciks", type=Path)
    ap.add_argument("--manifest", type=Path, help="required for build: the rows' manifest")
    ap.add_argument("--rebuild-of", type=Path, help="earlier rows dir this build must reproduce")
    ap.add_argument("--holdout-of", type=Path, help="dev rows dir; a drawn dev CIK is refused")
    ap.add_argument("--rows-dir", type=Path, help="exclude-union: the dev rows dir")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "exclude-union":
        try:
            print(json.dumps(exclude_union(a.out, a.exclude_ciks, a.rows_dir)))
        except (PitError, OSError) as exc:
            print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        return 0
    try:
        gold_value = importlib.import_module("benchmark.screen.critical_fields").gold_value
    except (ImportError, AttributeError):
        gold_value = None
    try:
        print(
            build(
                a.out,
                a.exclude_ciks,
                a.ciks,
                a.seed,
                a.manifest,
                gold_value,
                rebuild_of=a.rebuild_of,
                holdout_of=a.holdout_of,
            )
        )
    except (PitError, sources.SourceError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
