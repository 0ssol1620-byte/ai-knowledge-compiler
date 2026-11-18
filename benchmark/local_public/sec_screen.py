"""SEC screen / EG-04 records, sealed gold, split-gold (LPC design 2.3-2.5, 5.2, WO-LPC-4).

`build` selects one filing per CIK (seed-hash order, CIK-disjoint between the screen and EG-04
profiles, the companies of the amendment pairs reserved), prints one filer-marked page of each to a
one-page PDF, and emits WO-D02-1 document records (it does not freeze). Gold goes only to
`<profile>/gold.sealed.jsonl`; `split-gold` writes per-split files from a frozen manifest and
removes the sealed one. Local data is reached only through the pinned loader.

Filings are judged in a process pool (`workers`); the result never depends on the worker count or
on completion order, because results are committed one by one in the serial order (CIK rank, then
filing rank) and only the filings the serial run would have tried are committed. Each committed
decision is appended to `journal.jsonl` (fsync'ed, hash-chained); a restart with the same
arguments, seed and code replays it and continues. The final files are written once, at the end.
"""

from __future__ import annotations

import argparse
import copy
import csv
import functools
import gzip
import hashlib
import io
import json
import os
import shutil
import sys
import threading
import time
import zipfile
from collections import Counter, deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from benchmark.local_public import (
    pit_rows,
    pit_tasks,
    sec_align,
    sec_pages,
    sec_print,
    sec_time,
    sources,
)
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
# CLI default: half the logical cores, at most 6 (each worker holds one parsed filing); build()=1
WORKERS = max(1, min(6, (os.cpu_count() or 2) // 2))
HEARTBEAT_S = 60.0
JOURNAL = "journal.jsonl"
JOURNAL_SCHEMA = "tavonel.lpc-screen-journal.v1"
SELECTION = "dom_rule_v2 (§2.3)"
NOTE = "Chromium print of one filer-marked page of the filed HTML; external images not fetched"
_NOT_PRESENTED = ("dimensional", "coregistrant", "not_presented", "no_inline_xbrl")
STATEMENTS = (
    *SPEC_STATEMENTS,
    "Yields are measured over the filings this run tried (one CIK is tried until a page "
    "is found), not over the whole corpus.",
)


DERIVED_NOTE = (
    "Derived pages are synthetically degraded prints of source pages, not real scans; "
    "each carries its source page's gold rows."
)


class ScreenError(Exception):
    pass


def signed(gold_value: Callable[[dict[str, Any]], Any]) -> Callable[[dict[str, Any]], Decimal]:
    """`sec_align` wants a signed number; the scorer returns (amount, kind, unit)."""

    def read(field: dict[str, Any]) -> Decimal:
        canon = gold_value(field)
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


_busy: dict[str, Any] = {}  # the filing this process is judging now, for the heartbeat


def _phase(name: str) -> None:
    _busy["phase"] = name


@functools.cache
def _heartbeat() -> None:
    """Once per process: a line every HEARTBEAT_S while a filing is judged. The phase tells a slow
    filing (phase moves) from a stuck one (phase stays)."""

    def beat() -> None:
        while True:
            time.sleep(HEARTBEAT_S)
            b = dict(_busy)
            if b.get("adsh"):
                print(
                    f"  heartbeat pid={os.getpid()} {b['adsh']} {b.get('phase')} "
                    f"{time.monotonic() - b['t0']:.0f}s",
                    file=sys.stderr,
                    flush=True,
                )

    threading.Thread(target=beat, name="lpc-heartbeat", daemon=True).start()


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
    _phase("align")
    # align before the DOM refusals: a refused filing's rows stay in the yield denominator
    cands: list[Candidate] = []
    for item in align(sub, num, pre, html, signed(gold_value)):
        if isinstance(item, Excluded):
            reasons[item.reason] += 1
            rows["presented_rows"] += item.reason not in _NOT_PRESENTED
        else:
            cands.append(item)
    aligned = {c.field_id: c for c in cands}
    rows["presented_rows"] += len(aligned)
    rows["aligned_rows"] += len(aligned)
    rows["ddate_rounded_match"] += sum(c.ddate_rounded for c in aligned.values())
    if sec_pages.has_script(html):
        reasons["script_refused"] += 1
        return None
    _phase("segments")
    try:
        segs = sec_pages.segments(html)
    except sec_pages.SegmentRefused as exc:
        reasons[exc.reason] += 1
        return None
    dom_ok: set[str] = set()
    eligible: list[tuple[Any, list[Candidate]]] = []
    ranked = sorted(segs, key=lambda s: _rank(seed, "segment", f"{adsh}:{s.index}"))
    for i, seg in enumerate(ranked):
        _phase(f"accept {i + 1}/{len(ranked)}")
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
        _phase(f"render segment {seg.index}")
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


# ---------------------------------------------------------------- one filing, in any process

Task = tuple[str, dict[str, str], list[dict[str, str]], list[dict[str, str]]]


@dataclass
class Attempt:
    """What judging one filing produced. Nothing here is shared: the parent commits it, in serial
    order, or discards it (a filing the serial run would not have tried)."""

    adsh: str
    consumed: list[dict[str, Any]]  # the verified read, recorded in the run's ledger on commit
    reasons: Counter[str] = field(default_factory=Counter)
    rows: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)
    page: Page | None = None
    seconds: float = 0.0


_ctx: dict[str, Any] = {}  # a worker's loader, gold_value, render, seed and work dir


def _init_worker(ctx: dict[str, Any]) -> None:
    _ctx.update(ctx)
    _heartbeat()


def _attempt_in_worker(task: Task) -> Attempt:
    return _attempt(_ctx, task)


def _attempt(ctx: dict[str, Any], task: Task) -> Attempt:
    adsh, sub, num, pre = task
    t0 = time.monotonic()
    _busy.update(adsh=adsh, phase="read", t0=t0)
    try:
        loader = copy.copy(ctx["loader"])  # own ledger: the parent records the read on commit
        loader.ledger = sources.InputLedger(ctx["loader"].ledger.manifest_sha256)
        with loader.open_verified(f"sec_filing/{adsh}") as f, gzip.open(f) as g:
            html, tagged = sec_pages.strip_delivery_tag(g.read())
        att = Attempt(adsh, loader.ledger.consumed)
        att.rows["filings_read"] += 1
        att.rows["delivery_tag_stripped"] += tagged
        att.page = pick_page(
            sub,
            num,
            pre,
            html,
            gold_value=ctx["gold_value"],
            render=ctx["render"],
            seed=ctx["seed"],
            work=ctx["work"],
            reasons=att.reasons,
            rows=att.rows,
            errors=att.errors,
        )
        att.seconds = time.monotonic() - t0
        return att
    finally:
        _busy.clear()


def _attempts(
    seq: list[tuple[str, str]],
    done: set[str],
    replay: deque[dict[str, Any]],
    run: Callable[[str], Task],
    ctx: dict[str, Any],
    pool: ProcessPoolExecutor | None,
    window: int,
) -> Iterator[tuple[str, str, Attempt | None, dict[str, Any] | None]]:
    """(cik, adsh, fresh attempt, journal entry) in the serial order, skipping every filing of a
    CIK in `done` (checked when it is reached, so the consumer decides). Journal entries come first
    and must follow the same order. With a pool, up to `window` filings are being judged at any
    time, ahead of the serial order: every CIK's first filing before any CIK's second (a later
    filing is needed only when the earlier ones fail). A result is used only when the serial order
    reaches it; one the serial run would not have tried is never used."""
    i = 0
    while replay:
        if i == len(seq):
            raise ScreenError("journal holds filings beyond this run's plan; refusing to resume")
        cik, adsh = seq[i]
        i += 1
        if cik in done:
            continue
        e = replay.popleft()
        if (e["cik"], e["adsh"]) != (cik, adsh):
            raise ScreenError(f"journal entry {e['adsh']} is out of this run's order (want {adsh})")
        yield cik, adsh, None, e
    futs: dict[int, Future[Attempt]] = {}
    sent: set[int] = set()
    tryno = [0] * len(seq)
    for k in range(1, len(seq)):
        tryno[k] = tryno[k - 1] + 1 if seq[k][0] == seq[k - 1][0] else 0
    ahead = sorted(range(i, len(seq)), key=lambda k: (tryno[k], k))
    at = 0

    def send(k: int) -> bool:
        if pool is None or k in sent or seq[k][0] in done:
            return False
        sent.add(k)
        futs[k] = pool.submit(_attempt_in_worker, run(seq[k][1]))
        return True

    def refill() -> None:
        nonlocal at
        busy = sum(not f.done() for f in futs.values())
        while busy < window and at < len(ahead):
            busy += send(ahead[at])
            at += 1

    try:
        for j in range(i, len(seq)):
            cik, adsh = seq[j]
            if cik in done:
                skipped = futs.pop(j, None)
                if skipped is not None:
                    skipped.cancel()
                continue
            if pool is None:
                yield cik, adsh, _attempt(ctx, run(adsh)), None
                continue
            send(j)
            refill()
            while True:  # wait for filing j, keeping the workers busy meanwhile
                try:
                    att = futs[j].result(timeout=0.5)  # a worker's exception is raised here
                    break
                except TimeoutError:
                    if futs[j].done():
                        raise
                    refill()
            del futs[j]
            yield cik, adsh, att, None
    finally:
        for f in futs.values():
            f.cancel()


def _code_sha256(gold_value: Callable[..., Any]) -> str:
    """The code that decides the selection: these modules and the injected reader's module."""
    h = hashlib.sha256()
    here = sys.modules[__name__]
    for m in (here, sec_align, sec_pages, sec_print, sec_time, sources, pit_rows, pit_tasks):
        h.update(Path(str(m.__file__)).read_bytes())
    gv = sys.modules.get(getattr(gold_value, "__module__", "") or "")
    gv_file = getattr(gv, "__file__", None)
    h.update(Path(gv_file).read_bytes() if gv_file else repr(gold_value).encode())
    return h.hexdigest()


def _chain(prev: str, body: dict[str, Any]) -> str:
    return _sha((prev + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode())


def _append(path: Path, prev: str, body: dict[str, Any]) -> str:
    """One journal line, written and fsync'ed before the caller goes on; returns its chain hash."""
    h = _chain(prev, body)
    line = json.dumps({"body": body, "chain": h}, sort_keys=True, ensure_ascii=False) + "\n"
    with path.open("ab") as f:
        f.write(line.encode())
        f.flush()
        os.fsync(f.fileno())
    return h


def _read_journal(path: Path, header: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Verified entries after the header, and the last chain hash ("" when not even the header
    survived). Any complete line that does not verify refuses. A last line without its newline is
    a write the crash cut short: it is dropped (truncated) and that filing is judged again."""
    raw = path.read_bytes()
    *lines, tail = raw.split(b"\n")
    if tail:
        print(f"journal: dropping a torn last line ({len(tail)} bytes)", file=sys.stderr)
        with path.open("r+b") as f:
            f.truncate(len(raw) - len(tail))
            os.fsync(f.fileno())
    prev, bodies = "", []
    for n, line in enumerate(lines, 1):
        try:
            rec = json.loads(line)
            ok = set(rec) == {"body", "chain"} and rec["chain"] == _chain(prev, rec["body"])
        except (ValueError, TypeError, KeyError):
            ok = False
        if not ok:
            raise ScreenError(f"{path}: line {n} does not verify; refusing to resume")
        prev = rec["chain"]
        bodies.append(rec["body"])
    if bodies:
        got = bodies[0]
        if got.get("schema") != JOURNAL_SCHEMA:
            raise ScreenError(f"{path}: not a {JOURNAL_SCHEMA} journal")
        if got.get("code_sha256") != header["code_sha256"]:
            raise ScreenError(f"{path}: written by different code; refusing to resume")
        diff = sorted(
            k for k in {*got.get("args", {}), *header["args"]}
            if got.get("args", {}).get(k) != header["args"].get(k)
        )  # fmt: skip
        if diff:
            raise ScreenError(f"{path}: written with different arguments {diff}; refusing")
    return bodies[1:], prev


def _durable(path: Path, data: bytes) -> None:
    with path.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


_DECISIVE = (
    "source_hash_excluded_or_duplicate",
    "script_refused",
    "no_filer_page_breaks",
    "render_failed",
    "segment_multi_page",
)


def _verify_page(path: Path, record: dict[str, Any]) -> None:
    if not path.is_file() or "sha256:" + _sha(path.read_bytes()) != record["source_sha256"]:
        raise ScreenError(f"{path}: a journalled page is missing or changed; refusing to resume")


def _why(reasons: dict[str, int]) -> str:
    hit = [f"{r}={reasons[r]}" for r in _DECISIVE if reasons.get(r)]
    return ", ".join(hit) or f"no page with {sec_pages.MIN_FIELDS} accepted fields"


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
    workers: int = 1,
) -> dict[str, Any]:
    """`workers` > 1 judges filings in that many processes (`render` and `gold_value` must then be
    picklable, module-level functions); the outputs are the same for any worker count."""
    fam = _check_rights(load_families() if families is None else families)
    if not recorded_by.strip():
        raise ScreenError("recorded_by is required")
    if sources._inside_git_tree(out):
        raise ScreenError(f"output {out} is inside a git work tree")
    want = {"screen": screen_pages, "eg04": eg04_pages}
    if min(want.values()) < 0 or sum(want.values()) == 0:
        raise ScreenError("--screen-pages/--eg04-pages must be >= 0 and not both 0")
    if workers < 1:
        raise ScreenError("--workers must be >= 1")
    ex_ciks, ex_hashes = frozen_exclusions(exclude_from) if exclude_from else (set(), set())
    lpc_sha = loader.manifest["manifest_sha256"]
    snapshot = loader.resolve(SNAPSHOT_ENTRY)["sha256"]
    renderer_sha = loader.resolve(RENDERER_ENTRY)["sha256"]
    # what the selection depends on; the worker count is deliberately not in it
    header = {
        "schema": JOURNAL_SCHEMA,
        "code_sha256": _code_sha256(gold_value),
        "args": {
            "seed": seed,
            "screen_pages": screen_pages,
            "eg04_pages": eg04_pages,
            "recorded_by": recorded_by,
            "pool": pool,
            "lpc_manifest_sha256": lpc_sha,
            "exclude_from_sha256": _sha(exclude_from.read_bytes()) if exclude_from else None,
            "family_sha256": _sha(json.dumps(fam, sort_keys=True, default=str).encode()),
        },
    }
    journal = out / JOURNAL
    resume = journal.exists()
    if resume and (out / "receipt.json").exists():
        raise ScreenError(f"{out} holds a finished run (receipt.json); refusing to resume")
    replay, chain = _read_journal(journal, header) if resume else ([], "")
    if render is None:
        render = functools.partial(sec_print.print_pdf, loader.verified_path(RENDERER_ENTRY))

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

    finals = [out / p / n for p in want for n in ("records.jsonl", "gold.sealed.jsonl")]
    if not resume:
        out.mkdir(parents=True)
    for f in [*finals, out / "selected_ciks.json"]:  # a crash while writing them: rewritten below
        f.unlink(missing_ok=True)
    if not chain:  # a new run, or a journal whose header itself was torn
        chain = _append(journal, "", header)
    work = out / "tmp"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    rows: Counter[str] = Counter()
    errors: list[str] = []
    records: dict[str, list[dict[str, Any]]] = {p: [] for p in want}
    golds: dict[str, list[dict[str, Any]]] = {p: [] for p in want}
    chosen: dict[str, list[str]] = {p: [] for p in want}
    seen_hash: set[str] = set()
    for p in want:
        (out / p / "corpus").mkdir(parents=True, exist_ok=True)
    # the serial order: CIKs in rank order, each CIK's filings in rank order; a profile takes
    # CIKs until its quota is met, the next profile goes on with the next CIK (a 0 quota takes none)
    profiles = [p for p in want if want[p]]
    seq = [(c, a) for c in order for a in plan[c]]
    done: set[str] = set()
    t0 = time.monotonic()
    ctx = {"loader": loader, "gold_value": gold_value, "render": render, "seed": seed, "work": work}

    def task(a: str) -> Task:
        return a, subs[a][1], nums.get(a, []), pres.get(a, [])

    def decide(att: Attempt, cik: str, profile: str) -> dict[str, Any]:
        """The journal entry of a fresh attempt; an accepted page is made durable first."""
        quarter, sub = subs[att.adsh]
        record = gold = None
        if att.page is not None:
            pdf = att.page.pdf.read_bytes()
            if "sha256:" + _sha(pdf) in ex_hashes or _sha(pdf) in seen_hash:
                att.reasons["source_hash_excluded_or_duplicate"] += 1
            else:
                doc_id = f"sec-{att.adsh}.pdf"
                _durable(out / profile / "corpus" / doc_id, pdf)
                record = _record(
                    doc_id, pdf, sub, c2[att.adsh]["url"], quarter, loader, att.page, fam,
                    snapshot, renderer_sha, lpc_sha, STRATUM[profile], recorded_by,
                )  # fmt: skip
                gold = {"page_id": f"{doc_id}#0", "truth": _truth(att.page, sub, quarter, lpc_sha)}
        body = {
            "cik": cik,
            "adsh": att.adsh,
            "profile": profile,
            "consumed": att.consumed,
            "reasons": dict(att.reasons),
            "rows": dict(att.rows),
            "errors": att.errors,
            "record": record,
            "gold": gold,
        }
        # what a resumed run reads back, exactly: a fresh and a replayed decision are one value
        entry: dict[str, Any] = json.loads(json.dumps(body, sort_keys=True, ensure_ascii=False))
        return entry

    pending = deque(replay)
    executor = None
    if workers > 1:
        executor = ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(ctx,))
    else:
        _heartbeat()
    print(
        f"lpc screen: {len(seq)} filings planned over {len(order)} CIKs, workers={workers}, "
        f"{len(replay)} decisions in the journal",
        file=sys.stderr,
        flush=True,
    )
    try:
        stream = _attempts(seq, done, pending, task, ctx, executor, 2 * workers)
        for cik, adsh, att, e in stream:
            profile = profiles[0]
            if e is None:  # fresh: decide, make the page durable, then journal the decision
                assert att is not None
                e = decide(att, cik, profile)
                chain = _append(journal, chain, e)
            elif e["profile"] != profile:
                raise ScreenError(f"journal entry {adsh} is for {e['profile']}, not {profile}")
            elif e["record"] is not None:
                _verify_page(out / profile / "corpus" / e["record"]["doc_id"], e["record"])
            reasons.update(e["reasons"])
            rows.update(e["rows"])
            errors += e["errors"]
            for c in e["consumed"]:
                if loader.resolve(c["name"])["sha256"] != c["sha256"]:
                    raise ScreenError(f"journal: {c['name']} is not the pinned file")
                loader.ledger.record(c["name"], c["sha256"], c["bytes"])
            took = "journal" if att is None else f"{att.seconds:.0f}s"
            if e["record"] is None:
                what = "rejected: " + _why(e["reasons"])
            else:
                records[profile].append(e["record"])
                golds[profile].append(e["gold"])
                chosen[profile].append(cik)
                seen_hash.add(e["record"]["source_sha256"].removeprefix("sha256:"))
                done.add(cik)
                what = "SELECTED"
            print(
                f"[{time.monotonic() - t0:7.0f}s] {profile} {len(records[profile])}/"
                f"{want[profile]} cik={cik} {adsh} {what} ({took})",
                file=sys.stderr,
                flush=True,
            )
            if len(records[profile]) >= want[profile]:
                profiles.pop(0)
                if not profiles:
                    break
        if pending:
            raise ScreenError("journal holds decisions this run never reached; refusing")
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        shutil.rmtree(work, ignore_errors=True)
    for p in want:  # a page made durable whose decision the crash cut short: not part of the run
        keep = {r["doc_id"] for r in records[p]}
        for f in (out / p / "corpus").iterdir():
            if f.name not in keep:
                f.unlink()

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
    delivery = (
        "The stored bytes of each SEC filing are the filed document plus at most one script tag "
        "that sec.gov's delivery network appended when they were downloaded; that tag is set "
        "aside before any reading (filing_content_sha256 stays the hash of the stored bytes). "
        f"{rows['delivery_tag_stripped']} of the {rows['filings_read']} filings read carried it."
    )
    rec = sources.receipt(ledger, outputs, [*STATEMENTS, delivery])
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
    journal.unlink()  # it holds the gold; after the run, gold lives only in gold.sealed.jsonl
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


def _moved(line: str, doc_id: str) -> str:
    """The same gold row under a derived page's doc id; values are carried, never read out."""
    row = json.loads(line)
    row["page_id"] = f"{doc_id}#{row['page_id'].rsplit('#', 1)[1]}"
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def _gold_row(line: str) -> tuple[str, int]:
    """(doc id, critical field count) of one sealed gold row; a malformed row refuses. The
    message names the error type only, never a value."""
    try:
        row = json.loads(line)
        doc_id, page = row["page_id"].rsplit("#", 1)
        fields = row["truth"]["critical_fields"]
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ScreenError(f"sealed gold row is malformed ({type(exc).__name__})") from None
    if not (page.isascii() and page.isdigit()) or not isinstance(fields, list):
        raise ScreenError("sealed gold row is malformed (page number or critical_fields)")
    return doc_id, len(fields)


def split_documents(docs: Any) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, str]]:
    """(SEC documents by doc id, level of each, source doc id of each derived page) of a frozen
    manifest's ``documents``. Every SEC document is checked as freeze checks it; a level comes
    from ``screen_manifest.page_levels`` (ContractError on a missing or unknown level, never a
    default); a derived page's source is in the manifest, in the same split."""
    if not isinstance(docs, list) or not all(isinstance(d, dict) for d in docs):
        raise ScreenError("manifest documents must be a list of objects")
    sec = [d for d in docs if isinstance(p := d.get("provenance"), dict) and "adsh" in p]
    for d in sec:
        screen_manifest._check_doc(d)
        screen_manifest._company(d)
    screen_manifest._check_unique(sec)
    mine = {d["doc_id"]: d for d in sec}
    if not mine or any(d.get("split") not in screen_manifest.SPLITS for d in mine.values()):
        raise ScreenError("every SEC document in the manifest needs a split")
    level_of = screen_manifest.page_levels(mine.values())
    by_sha = {d["source_sha256"]: d for d in mine.values() if "derived_from" not in d}
    source_of: dict[str, str] = {}
    for doc_id, d in mine.items():
        if "derived_from" in d:
            src = by_sha.get(d["derived_from"])
            if src is None or src["split"] != d["split"]:
                raise ScreenError(f"{doc_id}: its source page is not in the manifest's same split")
            source_of[doc_id] = src["doc_id"]
    return mine, level_of, source_of


def split_gold(manifest_path: Path, sealed: Path) -> dict[str, Any]:
    """Per-split gold from a frozen manifest; refuses on any doc-set mismatch; removes `sealed`.

    A derived page (WO-D02-3C, synthetically degraded print) gets its source page's gold rows
    under its own doc id (``split_documents``); per-level counts are of validated levels only."""
    m = json.loads(manifest_path.read_text("utf-8"))
    if not isinstance(m, dict):
        raise ScreenError("manifest is not a JSON object")
    body = {k: v for k, v in m.items() if k != "manifest_sha256"}
    if canonical_sha256(body) != m.get("manifest_sha256"):
        raise ScreenError("manifest_sha256 does not match manifest content")
    mine, level_of, source_of = split_documents(m.get("documents"))
    clean = set(mine) - set(source_of)
    lines: dict[str, list[tuple[str, int]]] = {}
    for line in sealed.read_text("utf-8").splitlines():
        if line.strip():
            doc_id, n_fields = _gold_row(line)
            lines.setdefault(doc_id, []).append((line, n_fields))
    if set(lines) != clean:
        raise ScreenError(
            "gold and manifest document sets differ: "
            f"only in gold {sorted(set(lines) - clean)}, "
            f"only in manifest {sorted(clean - set(lines))}"
        )
    dests = {s: sealed.parent / f"gold.{s}.jsonl" for s in screen_manifest.SPLITS}
    if any(d.exists() for d in dests.values()):
        raise ScreenError("per-split gold already exists; refusing to overwrite")
    by_level: dict[str, Counter[str]] = {s: Counter() for s in dests}
    for s, dest in dests.items():
        with dest.open("x", encoding="utf-8", newline="\n") as f:
            for doc_id in sorted(d for d in mine if mine[d]["split"] == s):
                level = level_of[doc_id]
                rows = lines[source_of.get(doc_id, doc_id)]
                f.writelines(
                    (_moved(x, doc_id) if doc_id in source_of else x) + "\n" for x, _ in rows
                )
                by_level[s][f"{level}.pages"] += len(rows)
                by_level[s][f"{level}.critical_fields"] += sum(n for _, n in rows)
    receipt = {
        "manifest_sha256": m["manifest_sha256"],
        "gold_rows_by_level": {s: dict(sorted(c.items())) for s, c in by_level.items()},
        "derived_pages": DERIVED_NOTE if source_of else None,
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
    b.add_argument("--workers", type=int, default=WORKERS)
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
            workers=a.workers,
        )
        print(json.dumps(census["documents"]), json.dumps(census["shortfall"]))
        return 1 if any(census["shortfall"].values()) else 0
    except (ScreenError, sources.SourceError, ValueError) as exc:  # ContractError is a ValueError
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
