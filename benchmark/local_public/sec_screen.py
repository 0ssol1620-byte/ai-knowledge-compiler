"""SEC screen / EG-04 records, sealed gold, split-gold (LPC design 2.3-2.5, 5.2, WO-LPC-4).

`build` selects one filing per CIK (seed-hash order, CIK-disjoint between the screen and EG-04
profiles, the companies of the amendment pairs reserved), prints one filer-marked page of each to a
one-page PDF, and emits WO-D02-1 document records (it does not freeze). Gold goes only to
`<profile>/gold.sealed.jsonl`; `split-gold` writes per-split files from a frozen manifest and
removes the sealed one. Local data is reached only through the pinned loader.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import shutil
import sys
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from benchmark.local_public import sec_pages, sec_print, sec_time, sources
from benchmark.local_public.pit_rows import _group
from benchmark.local_public.pit_tasks import SPEC_STATEMENTS
from benchmark.local_public.sec_align import Candidate, Excluded, align
from benchmark.screen import manifest as screen_manifest
from benchmark.screen.acquire import load_families
from benchmark.v6.contracts import canonical_sha256

FAMILY, LICENCE = "sec_edgar", "SEC-WEBSITE-POLICY"
SNAPSHOT_ENTRY = "terms/data_sec_edgar_filings"
RENDERER_ENTRY = "tool/chrome-headless-shell"
CLASS = {
    "10-K": "sec_10k_statement_print",
    "10-K/A": "sec_10k_statement_print",
    "10-KT": "sec_10k_statement_print",
    "10-Q": "sec_10q_statement_print",
}
STRATUM = {"screen": "en_native", "eg04": "en_native"}
TRIES = 3  # filings tried per CIK, in seed-hash order
POOL = 6  # candidate CIKs preloaded per wanted page; ponytail: raise --pool when a run falls short
SELECTION = "dom_rule_v2 (§2.3)"
NOTE = "Chromium print of one filer-marked page of the filed HTML; external images not fetched"
_NOT_PRESENTED = ("dimensional", "coregistrant", "not_presented", "no_inline_xbrl")
STATEMENTS = (
    *SPEC_STATEMENTS,
    "Yields are measured over the filings this run tried (one CIK is tried until a page "
    "is found), not over the whole corpus.",
)


class ScreenError(Exception):
    pass


_CUR_PAREN = re.compile(r"^([$€£¥]) \((.+)\)$")


def canonical_gold(gold: str) -> str:
    """The scorer reads "($ 700)" and refuses "$ (700)": the symbol goes inside the bracket."""
    m = _CUR_PAREN.match(gold)
    return f"({m[1]} {m[2]})" if m else gold


def signed(gold_value: Callable[[dict[str, Any]], Any]) -> Callable[[dict[str, Any]], Decimal]:
    """`sec_align` wants a signed number; the scorer returns (amount, kind, unit)."""

    def read(field: dict[str, Any]) -> Decimal:
        canon = gold_value({**field, "value": canonical_gold(field["value"])})
        if not (isinstance(canon, tuple) and len(canon) == 3):
            raise ValueError(f"unexpected canonical value {canon!r}")
        return Decimal(canon[0])

    return read


def _norm(cik: Any) -> str:
    return str(cik).lstrip("0") or "0"


def _rank(seed: str, kind: str, key: Any) -> str:
    return hashlib.sha256(f"{seed}:{kind}:{key}".encode()).hexdigest()


def reserved_ciks(subs: Iterable[dict[str, str]]) -> set[str]:
    """Companies with a 10-K/A whose 10-K (same CIK and period) is also in FSDS (addendum P5)."""
    subs = list(subs)
    tenk = {(s["cik"], s["period"]) for s in subs if s["form"] == "10-K"}
    return {
        _norm(s["cik"]) for s in subs if s["form"] == "10-K/A" and (s["cik"], s["period"]) in tenk
    }


def _subs(loader: sources.Loader) -> dict[str, tuple[str, dict[str, str]]]:
    """adsh -> (quarter, FSDS sub row) over every pinned FSDS quarter."""
    out: dict[str, tuple[str, dict[str, str]]] = {}
    for name in sorted(n for n in loader._by_name if n.startswith("sec_fsds/")):
        with zipfile.ZipFile(loader.verified_path(name)) as zf, zf.open("sub.txt") as f:
            for r in csv.DictReader(
                io.TextIOWrapper(f, "utf-8", errors="replace"),
                delimiter="	",
                quoting=csv.QUOTE_NONE,
            ):
                out[r["adsh"]] = (name.split("/")[1], r)
    return out


def frozen_exclusions(path: Path) -> tuple[set[str], set[str]]:
    """(CIKs, source hashes) of a frozen manifest. A SEC document without provenance.cik refuses."""
    docs = json.loads(path.read_text("utf-8")).get("documents")
    if not isinstance(docs, list):
        raise ScreenError(f"{path}: not a frozen manifest (no documents list)")
    ciks, hashes = set(), set()
    for d in docs:
        hashes.add(d["source_sha256"])
        cik = (d.get("provenance") or {}).get("cik")
        if cik is not None:
            ciks.add(_norm(cik))
        elif (d.get("rights") or {}).get("licence_id") == LICENCE:
            raise ScreenError(f"{d.get('doc_id')}: SEC document without provenance.cik")
    return ciks, hashes


# ---------------------------------------------------------------- one filing -> one page


@dataclass
class Page:
    segment: int
    excerpt: bytes
    pdf: Path
    fields: list[Candidate]


def pick_page(
    sub: dict[str, str],
    num: list[dict[str, str]],
    pre: list[dict[str, str]],
    html: bytes,
    *,
    gold_value: Callable[[dict[str, Any]], Any],
    render: Callable[[Path, Path], int],
    seed: str,
    work: Path,
    reasons: Counter[str],
    rows: Counter[str],
    errors: list[str],
) -> Page | None:
    """First segment, in seed-hash order, that is eligible and prints to one page; else None."""
    adsh = sub["adsh"]
    if sec_pages.has_script(html):
        reasons["script_refused"] += 1
        return None
    try:
        segs = sec_pages.segments(html)
    except sec_pages.SegmentRefused as exc:
        reasons[exc.reason] += 1
        return None
    cands: list[Candidate] = []
    for item in align(sub, num, pre, html, signed(gold_value)):
        if isinstance(item, Excluded):
            reasons[item.reason] += 1
            rows["presented_rows"] += item.reason not in _NOT_PRESENTED
        else:
            cands.append(replace(item, gold=canonical_gold(item.gold)))
    aligned = {c.field_id: c for c in cands}
    rows["presented_rows"] += len(aligned)
    rows["aligned_rows"] += len(aligned)
    rows["ddate_rounded_match"] += sum(c.ddate_rounded for c in aligned.values())
    dom_ok: set[str] = set()
    eligible: list[tuple[Any, list[Candidate]]] = []
    for seg in sorted(segs, key=lambda s: _rank(seed, "segment", f"{adsh}:{s.index}")):
        ok, bad = sec_pages.accept(seg, cands)
        reasons.update(b.reason for b in bad)
        dom_ok.update(c.field_id for c in ok)
        once = Counter(c.field_id for c in ok)
        kept = [c for c in ok if once[c.field_id] == 1]
        reasons["duplicate_field_in_page"] += len(ok) - len(kept)  # one field, two anchors: no gold
        fields = []
        for c in kept:
            try:
                gold_value({"kind": c.kind, "value": c.gold, "anchor": c.anchor})
            except Exception:
                reasons["gold_unparseable"] += 1
            else:
                fields.append(c)
        if len(fields) >= sec_pages.MIN_FIELDS:
            eligible.append((seg, fields))
        elif ok:
            reasons["too_few_fields"] += len(fields)
    rows["dom_accepted_rows"] += len(dom_ok)
    for seg, fields in eligible:
        excerpt = sec_pages.excerpt_html(html, seg)
        src, pdf = work / f"{adsh}-{seg.index}.html", work / f"{adsh}-{seg.index}.pdf"
        src.write_bytes(excerpt)
        try:
            pages = render(src, pdf)
        except Exception as exc:  # operational failure: counted and listed, never silent
            reasons["render_failed"] += 1
            errors.append(f"{adsh}#{seg.index}: {type(exc).__name__}: {exc}"[:300])
            continue
        if pages != 1:
            reasons["segment_multi_page"] += 1
            continue
        rows["gold_rows"] += len(fields)
        return Page(seg.index, excerpt, pdf, fields)
    return None


def _truth(page: Page, sub: dict[str, str], quarter: str, lpc_sha: str) -> dict[str, Any]:
    return {
        "critical_fields": [
            {
                "field_id": c.field_id,
                "kind": c.kind,
                "value": c.gold,
                "anchor": c.anchor,
                "ixbrl": {
                    "context_id": c.context_id,
                    "start": c.start,
                    "end": c.end,
                    "scale": c.scale,
                    "sign": c.sign,
                    "sign_basis": c.sign_basis,
                },
                "fsds": {"quarter": quarter, **c.fsds},
            }
            for c in sorted(page.fields, key=lambda c: c.field_id)
        ],
        "high_risk": True,
        "text": sec_pages.dom_text(page.excerpt),
        "text_source": "html_dom_text",
        "gold_source": "sec_fsds_inline_xbrl",
        "selection_condition": SELECTION,
        "lpc_manifest_sha256": lpc_sha,
    }


# ---------------------------------------------------------------- build


def _check_rights(families: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if "public_record" not in screen_manifest.RIGHTS_CLASSES:
        raise ScreenError("RIGHTS_CLASSES has no 'public_record'; refusing before any read")
    fam = families.get(FAMILY)
    if fam is None or LICENCE not in (fam.get("licences") or {}):
        raise ScreenError(f"sources.yaml has no family {FAMILY!r} with licence {LICENCE!r}")
    if fam.get("rights_class") != "public_record":
        raise ScreenError(f"family {FAMILY!r} is {fam.get('rights_class')!r}, not public_record")
    return fam


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _jsonl(path: Path, items: Iterable[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps(i, sort_keys=True, ensure_ascii=False) + "\n" for i in items)


def build(
    out: Path,
    *,
    seed: str,
    screen_pages: int,
    eg04_pages: int,
    recorded_by: str,
    gold_value: Callable[[dict[str, Any]], Any],
    loader: sources.Loader,
    exclude_from: Path | None = None,
    render: Callable[[Path, Path], int] | None = None,
    families: dict[str, dict[str, Any]] | None = None,
    pool: int = POOL,
    private_audit_dir: Path | None = None,
) -> dict[str, Any]:
    fam = _check_rights(load_families() if families is None else families)
    if not recorded_by.strip():
        raise ScreenError("recorded_by is required")
    if sources._inside_git_tree(out):
        raise ScreenError(f"output {out} is inside a git work tree")
    want = {"screen": screen_pages, "eg04": eg04_pages}
    if min(want.values()) < 0 or sum(want.values()) == 0:
        raise ScreenError("--screen-pages/--eg04-pages must be >= 0 and not both 0")
    ex_ciks, ex_hashes = frozen_exclusions(exclude_from) if exclude_from else (set(), set())
    lpc_sha = loader.manifest["manifest_sha256"]
    snapshot = loader.resolve(SNAPSHOT_ENTRY)["sha256"]
    renderer_sha = loader.resolve(RENDERER_ENTRY)["sha256"]
    if render is None:
        exe = loader.verified_path(RENDERER_ENTRY)

        def real_render(html: Path, pdf: Path) -> int:
            return sec_print.print_pdf(exe, html, pdf)

        render = real_render

    subs = _subs(loader)
    with zipfile.ZipFile(loader.verified_path("sec_submissions_bulk")) as bz:
        bulk = sec_time.bulk_index(bz)
    c2 = {
        r["adsh"]: r
        for r in map(
            json.loads, loader.verified_path("c2_manifest").read_text("utf-8").splitlines()
        )
    }
    reserved = reserved_ciks(s for _, s in subs.values())
    banned = reserved | ex_ciks
    reasons: Counter[str] = Counter()
    by_cik: dict[str, list[str]] = {}
    for adsh, (_, s) in subs.items():
        if adsh not in c2 or s["form"] not in CLASS or not s["instance"].endswith("_htm.xml"):
            continue
        if _norm(s["cik"]) in banned:
            continue
        if sec_time.accepted_at(s["accepted"], bulk.get(adsh)) is None:
            reasons["acceptance_unresolved"] += 1
            continue
        by_cik.setdefault(_norm(s["cik"]), []).append(adsh)
    order = sorted(by_cik, key=lambda c: _rank(seed, "cik", c))[: pool * sum(want.values())]
    plan = {c: sorted(by_cik[c], key=lambda a: _rank(seed, "filing", a))[:TRIES] for c in order}
    by_q: dict[str, set[str]] = {}
    for tries in plan.values():
        for a in tries:
            by_q.setdefault(subs[a][0], set()).add(a)
    nums: dict[str, list[dict[str, str]]] = {}
    pres: dict[str, list[dict[str, str]]] = {}
    for q, adshes in sorted(by_q.items()):
        with zipfile.ZipFile(loader.verified_path(f"sec_fsds/{q}")) as zf:
            nums.update(_group(zf, "num.txt", adshes))
            pres.update(_group(zf, "pre.txt", adshes))

    out.mkdir(parents=True)
    work = out / "tmp"
    work.mkdir()
    rows: Counter[str] = Counter()
    errors: list[str] = []
    records: dict[str, list[dict[str, Any]]] = {p: [] for p in want}
    golds: dict[str, list[dict[str, Any]]] = {p: [] for p in want}
    chosen: dict[str, list[str]] = {p: [] for p in want}
    seen_hash: set[str] = set()
    cursor = iter(order)
    try:
        for profile, n in want.items():
            (out / profile / "corpus").mkdir(parents=True)
            for cik in cursor if n else ():
                for adsh in plan[cik]:
                    quarter, sub = subs[adsh]
                    with gzip.open(loader.open_verified(f"sec_filing/{adsh}")) as g:
                        html = g.read()
                    page = pick_page(
                        sub,
                        nums.get(adsh, []),
                        pres.get(adsh, []),
                        html,
                        gold_value=gold_value,
                        render=render,
                        seed=seed,
                        work=work,
                        reasons=reasons,
                        rows=rows,
                        errors=errors,
                    )
                    if page is None:
                        continue
                    pdf = page.pdf.read_bytes()
                    if "sha256:" + _sha(pdf) in ex_hashes or _sha(pdf) in seen_hash:
                        reasons["source_hash_excluded_or_duplicate"] += 1
                        continue
                    seen_hash.add(_sha(pdf))
                    doc_id = f"sec-{adsh}.pdf"
                    shutil.copyfile(page.pdf, out / profile / "corpus" / doc_id)
                    records[profile].append(
                        _record(
                            doc_id,
                            pdf,
                            sub,
                            c2[adsh]["url"],
                            quarter,
                            loader,
                            page,
                            fam,
                            snapshot,
                            renderer_sha,
                            lpc_sha,
                            STRATUM[profile],
                            recorded_by,
                        )
                    )
                    golds[profile].append(
                        {"page_id": f"{doc_id}#0", "truth": _truth(page, sub, quarter, lpc_sha)}
                    )
                    chosen[profile].append(cik)
                    break
                if len(records[profile]) >= n:
                    break
    finally:
        shutil.rmtree(work, ignore_errors=True)

    outputs: list[Path] = []
    for p in want:
        _jsonl(out / p / "records.jsonl", records[p])
        _jsonl(out / p / "gold.sealed.jsonl", golds[p])
        outputs += [out / p / "records.jsonl", out / p / "gold.sealed.jsonl"]
    union = sorted({int(c) for cs in chosen.values() for c in cs})
    sel = out / "selected_ciks.json"
    sel.write_text(json.dumps({"ciks": union}, indent=1), "utf-8")
    outputs.append(sel)
    ledger = loader.ledger
    rec = sources.receipt(ledger, outputs, list(STATEMENTS))
    pr = rows["presented_rows"] or 1
    rec["census"] = {
        "reasons": dict(sorted(reasons.items())),
        "rows": dict(sorted(rows.items())),
        "yield_over_presented_non_dimensional_rows": {
            "aligned": rows["aligned_rows"] / pr,
            "dom_accepted": rows["dom_accepted_rows"] / pr,
            "gold": rows["gold_rows"] / pr,
            "denominator": rows["presented_rows"],
        },
        "documents": {p: len(records[p]) for p in want},
        "shortfall": {p: max(0, want[p] - len(records[p])) for p in want},
        "filer_agent_prefix_by_profile": {
            p: dict(Counter(r["provenance"]["adsh"][:10] for r in records[p])) for p in want
        },
        "reserved_amendment_ciks": len(reserved),
        "excluded_from_ciks": len(ex_ciks),
        "selected_ciks_sha256": _sha(sel.read_bytes()),
        "render_errors": errors[:20],
        "seed": seed,
        "pool": pool,
    }
    sources.write_receipt(rec, out, private_audit_dir)
    census: dict[str, Any] = rec["census"]
    return census


def _record(
    doc_id: str,
    pdf: bytes,
    sub: dict[str, str],
    url: str,
    quarter: str,
    loader: sources.Loader,
    page: Page,
    fam: dict[str, Any],
    snapshot: str,
    renderer_sha: str,
    lpc_sha: str,
    stratum: str,
    recorded_by: str,
) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "source_sha256": "sha256:" + _sha(pdf),
        "byte_size": len(pdf),
        "page_count": 1,
        "stratum": stratum,
        "language": "en",
        "document_class": CLASS[sub["form"]],
        "page_origin": "born_digital_html_print",
        "notes": NOTE,
        "rights": {
            "source_url": url,
            "licence_id": LICENCE,
            "licence_snapshot_sha256": "sha256:" + snapshot,
            "rights_class": fam["rights_class"],
            "redistribution": False,
            "recorded_by": recorded_by,
            "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "provenance": {
            "adsh": sub["adsh"],
            "cik": int(sub["cik"]),
            "form": sub["form"],
            "filing_content_sha256": loader.resolve(f"sec_filing/{sub['adsh']}")["content_sha256"],
            "excerpt_html_sha256": _sha(page.excerpt),
            "fsds_quarter": quarter,
            "renderer_sha256": renderer_sha,
            "lpc_manifest_sha256": lpc_sha,
        },
    }


# ---------------------------------------------------------------- split-gold


def split_gold(manifest_path: Path, sealed: Path) -> dict[str, Any]:
    """Per-split gold from a frozen manifest; refuses on any doc-set mismatch; removes `sealed`."""
    m = json.loads(manifest_path.read_text("utf-8"))
    body = {k: v for k, v in m.items() if k != "manifest_sha256"}
    if canonical_sha256(body) != m.get("manifest_sha256"):
        raise ScreenError("manifest_sha256 does not match manifest content")
    mine = {d["doc_id"]: d for d in m["documents"] if "adsh" in (d.get("provenance") or {})}
    if not mine or any(d.get("split") not in screen_manifest.SPLITS for d in mine.values()):
        raise ScreenError("every SEC document in the manifest needs a split")
    lines: dict[str, list[str]] = {}
    for line in sealed.read_text("utf-8").splitlines():
        if line.strip():
            lines.setdefault(json.loads(line)["page_id"].rsplit("#", 1)[0], []).append(line)
    if set(lines) != set(mine):
        raise ScreenError(
            "gold and manifest document sets differ: "
            f"only in gold {sorted(set(lines) - set(mine))}, "
            f"only in manifest {sorted(set(mine) - set(lines))}"
        )
    dests = {s: sealed.parent / f"gold.{s}.jsonl" for s in screen_manifest.SPLITS}
    if any(d.exists() for d in dests.values()):
        raise ScreenError("per-split gold already exists; refusing to overwrite")
    for s, dest in dests.items():
        with dest.open("x", encoding="utf-8", newline="\n") as f:
            for doc_id in sorted(d for d in mine if mine[d]["split"] == s):
                f.writelines(x + "\n" for x in lines[doc_id])
    receipt = {
        "manifest_sha256": m["manifest_sha256"],
        "documents": {s: sum(d["split"] == s for d in mine.values()) for s in dests},
        "filer_agent_prefix_by_split": {
            s: dict(Counter(d["provenance"]["adsh"][:10] for d in mine.values() if d["split"] == s))
            for s in dests
        },
        "outputs": {s: _sha(d.read_bytes()) for s, d in dests.items()},
        "sealed_removed": sealed.as_posix(),
    }
    (sealed.parent / "split_gold_receipt.json").write_text(
        json.dumps(receipt, indent=1, sort_keys=True), "utf-8"
    )
    sealed.unlink()
    return receipt


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sec_screen")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--seed", required=True)
    b.add_argument("--screen-pages", type=int, default=33)
    b.add_argument("--eg04-pages", type=int, default=225)
    b.add_argument("--exclude-from", type=Path)
    b.add_argument("--recorded-by", required=True)
    b.add_argument("--pool", type=int, default=POOL)
    b.add_argument("--manifest", type=Path, default=sources.DEFAULT_MANIFEST)
    b.add_argument("--private-audit-dir", type=Path)
    g = sub.add_parser("split-gold")
    g.add_argument("--manifest", type=Path, required=True)
    g.add_argument("--gold", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "split-gold":
            print(json.dumps(split_gold(a.manifest, a.gold), sort_keys=True))
            return 0
        from benchmark.screen.critical_fields import gold_value

        census = build(
            a.out,
            seed=a.seed,
            screen_pages=a.screen_pages,
            eg04_pages=a.eg04_pages,
            recorded_by=a.recorded_by,
            gold_value=gold_value,
            loader=sources.configure(a.manifest),
            exclude_from=a.exclude_from,
            pool=a.pool,
            private_audit_dir=a.private_audit_dir,
        )
        print(json.dumps(census["documents"]), json.dumps(census["shortfall"]))
        return 1 if any(census["shortfall"].values()) else 0
    except (ScreenError, sources.SourceError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
