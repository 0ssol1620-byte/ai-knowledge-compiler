"""Stage S4 (WO-D10-0Z): the blind collection on the holdout and the custodian's report.

``python -m benchmark.screen.s4 collect ...`` is the S0 driver (``s0.Driver``, the same
``run_screen`` path, prechecks, readiness, retries, deadlines and exit codes) opening the
holdout split instead of dev: only with the frozen recipe file and its digest (the body hashes
to the digest, ``select_5h._check_recipe``'s rule) and, for a recipe member, its revision, image
digest and config digest equal to its entry; for the baseline (S4-5, outside the recipe) equal
to the pins file the lead wrote. The guard opens ``holdout`` / ``evaluate_frozen`` with that
digest and writes the one access log the caller names (S4-7). No gold is read and nothing is
scored (S4-1, decision D-6): a record holds what the page server answered, its failure class,
latency, derived cost, raw digest and pins. The per-page line prints status, latency and cost;
the run's pins (with the split, recipe digest, access log and role) are ``s0-run.json``, so a
resume on a fresh pod (S4-3) with the same ``--out`` sends no page already terminal and refuses
a pin that differs.

``python -m benchmark.screen.s4 report ...`` is the custodian's tool. It verifies every stored
raw digest and pin, refuses a run with a page that has no terminal record or that carries a
score, re-derives each answer with normaliser v2 from the stored ``text_before`` as ``rederive``
does (S4-4), scores with reader v1 through ``run_screen`` (a failed page counts the gold's
fields as wrong), runs ``signals_s3`` on the holdout through the guard and writes ``s4.json``
once with the S4-2 figures per stratum (H, R) and on the sensitivity subset (S4-9). Its stdout is
one line, the sha256 of ``s4.json``; a refusal prints its exit code, a fixed text and counts on
stderr, and the detail (which may name a page) goes to ``refusal.txt`` inside ``--out`` only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from akc_absorption.metrics import mcnemar_exact

from benchmark.runners.base import RunnerUnavailable
from benchmark.screen import critical_fields, rederive, run_screen, s0, select_5h
from benchmark.screen import normalise_v1 as v1
from benchmark.screen import normalise_v2 as v2
from benchmark.screen.manifest import HoldoutGuard, HoldoutSealedError, verify
from benchmark.screen.paired_report import build_report
from benchmark.screen.run_screen import Candidate, ImmutableOutputError
from benchmark.screen.s0 import (
    EXIT_CRASH,
    EXIT_INTEGRITY,
    EXIT_OK,
    EXIT_REFUSED,
    Driver,
    Exit,
)
from benchmark.screen.select_5h import H, R, _Key
from benchmark.v6.contracts import ContractError, canonical_sha256, require_sha256
from benchmark.w6.v2.grading import wilson_interval

MODULE_SHA256 = "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SENSITIVITY = "sensitivity"
FILER_PREFIX = 10  # provenance.adsh[:10]: the filing agent (S4-9)
PIN_KEYS = ("candidate_id", "provider", "revision", "image_digest", "config_sha256")
COST_KIND = (
    "derived: the sum of the per-page derived costs the members' records carry (stated price x "
    "measured request latency; a page without a measured latency carries none and is counted "
    "in pages_without_cost), divided by the accepted pages; not billed"
)


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(Path(path).read_bytes())


# ---------------------------------------------------------------- collection (G1 + G2)


class Collector(Driver):
    """``s0.Driver`` on the holdout: frozen recipe or baseline pins, the named access log, no
    gold. Every check of the dev driver runs as it does there."""

    split, purpose = "holdout", "evaluate_frozen"

    def __init__(self, args: argparse.Namespace, **kw: Any) -> None:
        self.frozen_recipe_sha256 = str(args.recipe_sha256)
        super().__init__(args, **kw)

    def _access_log(self) -> Path:
        return Path(self.args.access_log)

    def _read_gold(self) -> None:
        return None  # S4-1: the collecting process holds no gold

    def _frozen_pins(self) -> dict[str, Any]:
        a, digest = self.args, str(self.args.recipe_sha256)
        try:
            require_sha256(digest, "recipe_sha256")
            recipe = json.loads(Path(a.recipe).read_text(encoding="utf-8"))
            members = list(recipe["member_order"])
            select_5h._check_recipe(recipe, digest, members, recipe["escalate_on"], [])
        except (OSError, ValueError, KeyError, TypeError):  # ContractError is a ValueError
            raise Exit(
                EXIT_REFUSED, "the recipe file is not the recipe --recipe-sha256 names"
            ) from None
        first = self.guard._first_recipe()
        if first is not None and first != digest:
            raise Exit(EXIT_REFUSED, "the access log names another recipe: the holdout opens once")
        mine = {
            "candidate_id": self.cid,
            "provider": self.provider,
            "revision": a.revision,
            "image_digest": a.image_digest,
            "config_sha256": self.candidate.config_sha256,
        }
        pins_sha = None
        if self.cid in members:
            if a.baseline_pins is not None:
                raise Exit(EXIT_REFUSED, "a recipe member takes its pins from the recipe only")
            row = {**mine, "page_id": "-"}
            try:
                select_5h._check_recipe(recipe, digest, members, recipe["escalate_on"], [row])
            except ContractError:
                raise Exit(
                    EXIT_REFUSED, "the candidate's pins differ from the frozen recipe"
                ) from None
        else:
            if a.baseline_pins is None:
                raise Exit(EXIT_REFUSED, "a candidate outside the recipe needs --baseline-pins")
            try:
                data = Path(a.baseline_pins).read_bytes()
                pinned = json.loads(data)
            except (OSError, ValueError):
                raise Exit(EXIT_REFUSED, "the baseline pins file is not readable JSON") from None
            if pinned != mine:
                raise Exit(EXIT_REFUSED, "the baseline's pins differ from the baseline pins file")
            pins_sha = _sha(data)
        return {
            "split": self.split,
            "frozen_recipe_sha256": digest,
            "access_log": str(self._access_log().resolve()),
            "role": "member" if pins_sha is None else "baseline",
            "baseline_pins_sha256": pins_sha,
        }

    def _log(
        self, n: int, what: str, latency: Any = None, cost: Any = None, res: Any = None
    ) -> None:
        def show(v: Any, fmt: str) -> str:
            return format(v, fmt) if isinstance(v, int | float) else "-"

        print(
            f"S4 {self.cid} page {n}/{len(self.ordinal)} {what} "
            f"latency={show(latency, '.0f')} cost={show(cost, '.6f')}",
            flush=True,
        )

    def summary(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        out = super().summary(records)
        del out["accepted"]  # nothing is scored here: no figure that reads like a score
        return out

    def _done_line(self, summary: dict[str, Any]) -> str:
        return f"S4 {self.cid} collected pages={summary['pages']}"


def _collect_args(p: argparse.ArgumentParser) -> None:
    for name in ("candidate-id", "provider", "revision", "image-digest", "pod-id", "created-utc"):
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--config-sha256", default=None)
    p.add_argument("--usd-per-hour", required=True, type=float)
    p.add_argument("--recipe-sha256", required=True)
    for name in ("manifest", "corpus-root", "out", "recipe", "access-log"):
        p.add_argument(f"--{name}", required=True, type=Path)
    p.add_argument("--baseline-pins", type=Path, default=None)


def collect(
    args: argparse.Namespace,
    *,
    request: s0.Request | None = None,
    call: s0.Call = run_screen._call,
    now: Callable[[], datetime] = s0._utcnow,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    try:
        driver = Collector(args, request=request, call=call, now=now, sleep=sleep)
        driver.wait_ready()
        return driver.run()
    except Exit as stop:
        print(f"S4 {args.candidate_id} exit {stop.code}: {stop}", flush=True)
        return stop.code
    except ImmutableOutputError:
        print(
            f"S4 {args.candidate_id} exit {EXIT_INTEGRITY}: stored raw output changed", flush=True
        )
        return EXIT_INTEGRITY
    except HoldoutSealedError:
        print(f"S4 {args.candidate_id} exit {EXIT_REFUSED}: the holdout guard refused", flush=True)
        return EXIT_REFUSED
    except Exception as exc:  # the message may quote a document: the type only
        print(f"S4 {args.candidate_id} exit {EXIT_CRASH}: crash {type(exc).__name__}", flush=True)
        return EXIT_CRASH


# ---------------------------------------------------------------- the custodian (G3 + G4)


def _report_args(p: argparse.ArgumentParser) -> None:
    for name in ("recipe-sha256", "baseline", "normaliser-v2-sha256", "billed-source"):
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--billed-usd", required=True, type=float)
    for name in (
        "recipe",
        "manifest",
        "dev-manifest",
        "corpus-root",
        "gold",
        "runs",
        "baseline-pins",
        "access-log",
        "out",
    ):
        p.add_argument(f"--{name}", required=True, type=Path)


def _json(path: Path, what: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Exit(EXIT_REFUSED, f"{what} is not readable JSON") from exc


def _manifests(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    hold = _json(args.manifest, "--manifest")
    dev = _json(args.dev_manifest, "--dev-manifest")
    try:
        verify(hold, Path(args.corpus_root))
    except Exception as exc:  # the message may name a document: the type only on stderr
        raise Exit(EXIT_REFUSED, f"holdout manifest verify failed ({type(exc).__name__})") from exc
    if not isinstance(dev, dict) or canonical_sha256(
        {k: v for k, v in dev.items() if k != "manifest_sha256"}
    ) != dev.get("manifest_sha256"):
        raise Exit(EXIT_REFUSED, "the dev manifest is not an intact frozen manifest")
    if any(d.get("split") != "dev" for d in dev["documents"]):
        raise Exit(EXIT_REFUSED, "the dev manifest holds a page that is not dev")
    if "disjoint_from_sha256" not in hold or hold["disjoint_from_sha256"] != dev["manifest_sha256"]:
        raise Exit(
            EXIT_REFUSED, "the holdout manifest was not frozen disjoint from this dev manifest"
        )
    return hold, dev


def _prefix(doc: Mapping[str, Any]) -> str:
    adsh = doc["provenance"]["adsh"]
    if not isinstance(adsh, str) or len(adsh) < FILER_PREFIX:
        raise ContractError("a document's provenance.adsh has no filer prefix")
    return adsh[:FILER_PREFIX]


def sensitivity_pages(hold: Mapping[str, Any], dev: Mapping[str, Any]) -> list[str]:
    """S4-9: holdout pages whose filer prefix (``provenance.adsh[:10]``) is on no dev page;
    sorted. A document without one refuses, never a page silently in or out."""
    try:
        filed = {_prefix(d) for d in dev["documents"]}
        return sorted(
            f"{d['doc_id']}#{p}"
            for d in hold["documents"]
            if d.get("split") == "holdout" and _prefix(d) not in filed
            for p in range(d["page_count"])
        )
    except (KeyError, TypeError, ContractError) as exc:
        raise Exit(EXIT_REFUSED, "a document has no provenance.adsh filer prefix") from exc


def _access(path: Path, digest: str, manifest_sha: str) -> dict[str, Any]:
    """The one log (S4-7) exists, was opened by the collection, and names only this recipe."""
    try:
        lines = [
            json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()
        ]
    except (OSError, ValueError) as exc:
        raise Exit(EXIT_REFUSED, "the access log is missing or not JSON lines") from exc
    want = {"frozen_recipe_sha256": digest, "manifest_sha256": manifest_sha}
    if not lines or any(x != want for x in lines):
        raise Exit(
            EXIT_REFUSED, f"the access log's {len(lines)} line(s) do not all name this recipe"
        )
    return {"sha256": _file_sha(path), "lines": len(lines)}


def _run_pins(
    run_dir: Path, cid: str, args: argparse.Namespace, recipe: Mapping[str, Any]
) -> dict[str, Any]:
    pins = _json(run_dir / "s0-run.json", f"{cid}'s s0-run.json")
    member = cid in recipe["member_order"]
    want = {
        "candidate_id": cid,
        "split": "holdout",
        "frozen_recipe_sha256": str(args.recipe_sha256),
        "access_log": str(Path(args.access_log).resolve()),
        "role": "member" if member else "baseline",
        "normaliser_sha256": v1.MODULE_SHA256,
    }
    if not isinstance(pins, dict) or any(k not in pins or pins[k] != v for k, v in want.items()):
        raise Exit(EXIT_REFUSED, f"{cid}: the run's pins are not a collection under this recipe")
    if member:
        entry = next(m for m in recipe["members"] if m["candidate_id"] == cid)
        if any(pins[k] != entry[k] for k in ("revision", "image_digest", "config_sha256")):
            raise Exit(EXIT_INTEGRITY, f"{cid}: the run's pins differ from the frozen recipe")
        if pins["baseline_pins_sha256"] is not None:
            raise Exit(EXIT_REFUSED, f"{cid}: a member run names a baseline pins file")
    else:
        try:
            data = Path(args.baseline_pins).read_bytes()
            pinned = json.loads(data)
        except (OSError, ValueError) as exc:
            raise Exit(EXIT_REFUSED, "the baseline pins file is not readable JSON") from exc
        if _sha(data) != pins["baseline_pins_sha256"] or pinned != {k: pins[k] for k in PIN_KEYS}:
            raise Exit(EXIT_INTEGRITY, f"{cid}: the run's pins are not the baseline pins file")
    return pins


def _rederive(
    cid: str,
    run_dir: Path,
    pins: Mapping[str, Any],
    pages: set[str],
    *,
    guard: HoldoutGuard,
    digest: str,
    corpus_root: Path,
    gold: Mapping[str, dict[str, Any]],
    stage: Path,
) -> tuple[list[dict[str, Any]], str]:
    """One run's records scored with v2 text through ``run_screen`` (reader v1); the stored
    collection records' digest. Only the scored fields and the raw digest of a re-normalised
    answer may differ from the stored record."""
    provider = str(pins["provider"])
    _, records, stored, records_sha = rederive._load(run_dir, provider)
    got = {r["page_id"] for r in records}
    if got != pages:
        raise Exit(
            EXIT_REFUSED,
            f"{cid}: {len(pages - got)} page(s) without a terminal record, "
            f"{len(got - pages)} outside the holdout",
        )
    if any(
        r.get("split") != "holdout" or r["critical"] is not None or r["accepted"] is not None
        for r in records
    ):
        raise Exit(EXIT_REFUSED, f"{cid}: a record is not a blind holdout collection record")
    replays: dict[str, dict[str, Any]] = {}
    for key, data in stored.items():
        if data is None:
            continue
        raw = json.loads(data)
        replays[key] = rederive._replay(provider, raw) if rederive._normalised(raw) else raw
    candidate = Candidate(
        candidate_id=cid,
        provider=provider,
        revision=str(pins["revision"]),
        image_digest=str(pins["image_digest"]),
        config_sha256=str(pins["config_sha256"]),
    )

    def call(c: Candidate, case: dict[str, Any], _: Path) -> dict[str, Any]:
        page_id = f"{case['source']['path']}#{case['page_index']}"
        answer = replays.get(canonical_sha256([page_id, *(getattr(c, k) for k in rederive.PINS)]))
        if answer is None:  # stored without output: its failure is the stored record's
            raise RunnerUnavailable("no stored answer to replay")
        return answer

    with tempfile.TemporaryDirectory(dir=stage) as ledger:
        try:
            fresh = run_screen.run_screen(
                guard=guard,
                split="holdout",
                purpose="evaluate_frozen",
                frozen_recipe_sha256=digest,
                candidate=candidate,
                corpus_root=corpus_root,
                gold=gold,
                raw_dir=stage / "raw",
                records_path=Path(ledger) / "records.jsonl",
                call=call,
            )
        except ContractError as exc:
            raise Exit(EXIT_REFUSED, f"{cid}: run_screen refused ({type(exc).__name__})") from exc
    old = {r["record_key"]: r for r in records}
    out = []
    for r in fresh:
        before = old[r["record_key"]]
        if stored[r["record_key"]] is None:  # no output: the stored failure, the gold's fields
            r = {**before, **{k: r[k] for k in ("critical", "metrics", "accepted")}}
        else:
            r = {**r, "latency_ms": before["latency_ms"]}  # S4 measured it; a replay does not
            differ = {
                k
                for k in set(r) | set(before)
                if k not in rederive.SCORED and r.get(k) != before.get(k)
            }
            if not rederive._normalised(json.loads(stored[r["record_key"]] or b"")):
                differ |= {"raw_sha256"} if r["raw_sha256"] != before["raw_sha256"] else set()
            if differ:  # field names only, never a value
                raise Exit(
                    EXIT_INTEGRITY, f"{cid}: a re-derived record differs in {sorted(differ)}"
                )
        out.append(r)
    return out, records_sha


def _rate(k: int, n: int) -> dict[str, Any]:
    return {
        "k": k,
        "n": n,
        "rate": k / n if n else None,
        "wilson_95": wilson_interval(k, n) if n else None,
    }


def _mcnemar(a: Sequence[bool], b: Sequence[bool]) -> dict[str, Any]:
    only_a = sum(x and not y for x, y in zip(a, b, strict=True))
    only_b = sum(y and not x for x, y in zip(a, b, strict=True))
    return {
        "pages": len(a),
        "both": sum(x and y for x, y in zip(a, b, strict=True)),
        "neither": sum(not x and not y for x, y in zip(a, b, strict=True)),
        "only_left": only_a,
        "only_baseline": only_b,
        "p_exact": mcnemar_exact(only_a, only_b),
    }


def s4_part(
    pages: Sequence[str],
    *,
    fields: Mapping[str, Sequence[_Key]],
    escalated: Mapping[_Key, bool],
    right: Mapping[str, Mapping[_Key, bool]],
    cost: Mapping[str, Mapping[str, float | None]],
    members: Sequence[str],
    baseline: str,
) -> dict[str, Any]:
    """S4-2 over ``pages``. A field is escalated when the recipe's rule fires on it, accepted
    otherwise (P's value stands). An accepted page has no escalated field. McNemar is page
    level: the recipe's "every field accepted and exact" and P alone's "every field exact"
    against the baseline's "every field exact" (a page with no gold field is neither)."""
    p = members[0]
    keys = [k for pg in pages for k in fields[pg]]
    esc = sum(escalated[k] for k in keys)
    acc = len(keys) - esc
    acc_exact = sum(right[p][k] for k in keys if not escalated[k])
    accepted_pages = sum(not any(escalated[k] for k in fields[pg]) for pg in pages)

    def all_ok(pg: str, ok: Callable[[_Key], bool]) -> bool:
        return bool(fields[pg]) and all(ok(k) for k in fields[pg])

    recipe_ok = [all_ok(pg, lambda k: not escalated[k] and right[p][k]) for pg in pages]
    base_ok = [all_ok(pg, lambda k: right[baseline][k]) for pg in pages]
    p_ok = [all_ok(pg, lambda k: right[p][k]) for pg in pages]
    known = {m: [c for pg in pages if (c := cost[m][pg]) is not None] for m in members}
    derived = sum(sum(v) for v in known.values())
    return {
        "pages": len(pages),
        "fields": len(keys),
        "escalated_fields": esc,
        "accepted_fields": acc,
        "accepted_pages": accepted_pages,
        "escalation_rate": esc / len(keys) if keys else None,
        "accepted_field_exact": _rate(acc_exact, acc),
        "false_accept": _rate(acc - acc_exact, acc),
        "recipe_yield": _rate(acc_exact, len(keys)),
        "cost": {
            "kind": COST_KIND,
            "derived_usd": derived,
            "pages_without_cost": {m: len(pages) - len(known[m]) for m in members},
            "usd_per_accepted_page": derived / accepted_pages if accepted_pages else None,
        },
        "mcnemar_recipe_vs_baseline": _mcnemar(recipe_ok, base_ok),
        "mcnemar_primary_vs_baseline": _mcnemar(p_ok, base_ok),
    }


def _cells(
    records: Sequence[dict[str, Any]],
    reasons: Mapping[str, Mapping[str, str | None]],
    place: Mapping[str, str],
    baseline: str,
) -> dict[str, Any]:
    """Field-exact cells per part by ``select_s1``'s relabelling (``select_5h.relabel``)."""
    rows = [
        select_5h.relabel(r, reasons[r["candidate_id"]][r["page_id"]], place[r["page_id"]])
        for r in records
        if r["page_id"] in place
    ]
    strata = build_report(rows, incumbent=baseline)["strata"] if rows else {}
    return {s: v["cells"] for s, v in strata.items()}


def _refuse_on(stage: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Run a select_5h step; its refusals may name a page: re-raised as fixed text (the
    original is kept as the cause, for refusal.txt only)."""

    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        def go(*a: Any, **kw: Any) -> Any:
            try:
                return fn(*a, **kw)
            except (ValueError, KeyError, TypeError, HoldoutSealedError) as exc:
                raise Exit(EXIT_REFUSED, f"{stage} refused ({type(exc).__name__})") from exc

        return go

    return wrap


def build(args: argparse.Namespace, stage: Path) -> dict[str, Any]:
    """Everything before ``s4.json`` is written; refusals are ``Exit`` with fixed text."""
    if args.normaliser_v2_sha256 != v2.MODULE_SHA256:
        raise Exit(EXIT_REFUSED, "normalise_v2.py is not the v2 --normaliser-v2-sha256 names")
    if _file_sha(Path(critical_fields.__file__)) != select_5h.READER_V1_SHA256:
        raise Exit(EXIT_REFUSED, "critical_fields.py is not reader v1")
    billed = args.billed_usd
    if not (math.isfinite(billed) and billed >= 0):
        raise Exit(EXIT_REFUSED, "--billed-usd must be a finite non-negative number")
    if not select_5h._is_reason(args.billed_source):
        raise Exit(
            EXIT_REFUSED,
            f"--billed-source must be non-empty text of at most {select_5h.MAX_INELIGIBLE_REASON}",
        )
    digest = str(args.recipe_sha256)
    recipe = _json(args.recipe, "--recipe")
    try:
        require_sha256(digest, "recipe_sha256")
        members = list(recipe["member_order"])
        escalate_on = list(recipe["escalate_on"])
        select_5h._check_recipe(recipe, digest, members, escalate_on, [])
    except (ValueError, KeyError, TypeError) as exc:
        raise Exit(EXIT_REFUSED, "the recipe file is not the recipe --recipe-sha256 names") from exc
    baseline = str(args.baseline)
    if baseline in members or len(members) < 2:
        raise Exit(EXIT_REFUSED, "the baseline must be outside a recipe of at least two members")
    hold, dev = _manifests(args)
    try:
        gold = Driver._gold(Path(args.gold))
    except OSError as exc:
        raise Exit(EXIT_REFUSED, "--gold is not readable") from exc
    access = _access(Path(args.access_log), digest, hold["manifest_sha256"])
    guard = HoldoutGuard(hold, Path(args.access_log))
    # the collection opened the holdout under this digest: the guard writes nothing more
    scope = _refuse_on("scope")(select_5h._scope)(guard, "holdout", "evaluate_frozen", digest)
    subset: dict[str, str] = scope[0]
    if set(gold) != set(subset):
        raise Exit(
            EXIT_REFUSED,
            f"gold and holdout differ: {len(set(subset) - set(gold))} page(s) without gold, "
            f"{len(set(gold) - set(subset))} gold row(s) outside the holdout",
        )
    sens = sensitivity_pages(hold, dev)
    (stage / "raw").mkdir()
    cands = [*members, baseline]
    records: list[dict[str, Any]] = []
    runs: dict[str, Any] = {}
    for c in cands:
        run_dir = Path(args.runs) / c
        pins = _run_pins(run_dir, c, args, recipe)
        got, collected_sha = _rederive(
            c,
            run_dir,
            pins,
            set(subset),
            guard=guard,
            digest=digest,
            corpus_root=Path(args.corpus_root),
            gold=gold,
            stage=stage,
        )
        records += got
        runs[c] = {"pins": pins, "collected_records_sha256": collected_sha}
    texts = _refuse_on("load_texts")(select_5h.load_texts)(records, stage / "raw")
    signals = _refuse_on("signals_s3")(select_5h.signals_s3)(
        records,
        texts,
        gold,
        guard=guard,
        members=members,
        escalate_on=escalate_on,
        split="holdout",
        frozen_recipe_sha256=digest,
        recipe=recipe,
    )
    by = _refuse_on("records")(select_5h._check)(records, scope)
    read, right = _refuse_on("reader")(select_5h._reads)(by, texts, gold, cands)
    rows = select_5h.field_signals(read, members, escalate_on, {}, False)
    p = members[0]
    reasons = {
        c: {
            pg: _refuse_on("failures")(select_5h._reason)(r, stage / "raw")
            for pg, r in by[c].items()
        }
        for c in cands
    }
    fields = {
        pg: [(pg, str(f["field_id"])) for f in gold[pg].get("critical_fields") or []]
        for pg in subset
    }
    # S4-2: a failed primary page escalates all its fields (no_value raises it too)
    escalated = {k: bool(rows[k]["escalate"]) or reasons[p][k[0]] is not None for k in rows}
    cost = {m: {pg: by[m][pg]["provider_cost_usd"] for pg in subset} for m in members}
    parts = {
        H: sorted(pg for pg in subset if subset[pg] == H),
        R: sorted(pg for pg in subset if subset[pg] == R),
        SENSITIVITY: sens,
    }
    figures = {
        name: s4_part(
            pages,
            fields=fields,
            escalated=escalated,
            right=right,
            cost=cost,
            members=members,
            baseline=baseline,
        )
        for name, pages in parts.items()
    }
    cells = _refuse_on("cells")(_cells)(records, reasons, subset, baseline)
    cells_s = _refuse_on("cells")(_cells)(
        records, reasons, dict.fromkeys(sens, SENSITIVITY), baseline
    )
    all_pages = sorted(subset)
    derived_total = sum(c for m in members for pg in all_pages if (c := cost[m][pg]) is not None)
    return {
        "stage": "S4",
        "publishable": False,
        "frozen_recipe_sha256": digest,
        "members": members,
        "primary": p,
        "baseline": baseline,
        "escalate_on": sorted(escalate_on),
        "definitions": {
            "escalated": "the recipe's rule fires on the field (signals_s3 over the members), or "
            "the primary's page failed",
            "accepted": "not escalated: the primary's value stands",
            "accepted_page": "a page with no escalated field",
            "accepted_field_exact": "accepted and exact / accepted",
            "false_accept": "accepted and wrong / accepted",
            "escalation_rate": "escalated / all fields",
            "recipe_yield": "accepted and exact / all fields (5H's recipe field-exact rate)",
            "failed_page": "a page with a 5H-17/18/19 failure class: every gold field counts wrong",
        },
        "parts": {
            name: {
                **figures[name],
                "cells": (
                    cells_s.get(SENSITIVITY, {}) if name == SENSITIVITY else cells.get(name, {})
                ),
            }
            for name in parts
        },
        "sensitivity_subset": {
            "rule": "holdout pages whose provenance.adsh[:10] is on no dev page (S4-9)",
            "pages": len(sens),
            "page_ids_sha256": canonical_sha256(sens),
        },
        "failures": {c: select_5h._tally(by[c], reasons[c]) for c in cands},
        "signals_s3": signals,
        "billed": {
            "usd": billed,
            "source": args.billed_source,
            "kind": "billed total passed in by the lead; never mixed into a derived figure",
        },
        "derived_total_usd": derived_total,
        "inputs": {
            "recipe_file_sha256": _file_sha(args.recipe),
            "holdout_manifest_sha256": hold["manifest_sha256"],
            "holdout_manifest_file_sha256": _file_sha(args.manifest),
            "dev_manifest_sha256": dev["manifest_sha256"],
            "dev_manifest_file_sha256": _file_sha(args.dev_manifest),
            "gold_file_sha256": _file_sha(args.gold),
            "gold_sha256": select_5h._gold_sha(gold, all_pages),
            "baseline_pins_file_sha256": _file_sha(args.baseline_pins),
            "access_log": access,
            "runs": runs,
            "scored_records_sha256": select_5h._records_sha(records),
            "texts_sha256": select_5h._texts_sha(texts, records),
            "code": {
                "s4": MODULE_SHA256,
                "select_5h": _file_sha(Path(select_5h.__file__)),
                "run_screen": _file_sha(Path(run_screen.__file__)),
                "s0": _file_sha(Path(s0.__file__)),
                "rederive": rederive.MODULE_SHA256,
                "reader_v1": select_5h.READER_V1_SHA256,
                "normaliser_v1": v1.MODULE_SHA256,
                "normaliser_v2": v2.MODULE_SHA256,
            },
        },
    }


def _detail(out: Path, exc: BaseException) -> None:
    """The refusal's full text, for the custodian's directory only (never a stream)."""
    lines = []
    e: BaseException | None = exc
    while e is not None:
        lines.append(f"{type(e).__module__}.{type(e).__qualname__}: {e}")
        e = e.__cause__ or e.__context__
    out.mkdir(parents=True, exist_ok=True)
    (out / "refusal.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def report(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        print(
            f"s4 report exit {EXIT_REFUSED}: --out is not empty; s4.json is written once",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=out.name + ".stage-", dir=out.parent))
    try:
        body = build(args, stage)
    except Exit as stop:
        _detail(out, stop)
        print(f"s4 report exit {stop.code}: {stop}", file=sys.stderr)
        return stop.code
    except Exception as exc:  # the message may quote a document: the type only
        _detail(out, exc)
        print(f"s4 report exit {EXIT_CRASH}: crash {type(exc).__name__}", file=sys.stderr)
        return EXIT_CRASH
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    data = select_5h.dump(body)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "s4.json").open("xb") as fh:
        fh.write(data)
    print(_sha(data), flush=True)
    return EXIT_OK


def main(argv: list[str] | None = None, **collect_kw: Any) -> int:
    ap = argparse.ArgumentParser(prog="python -m benchmark.screen.s4")
    sub = ap.add_subparsers(dest="cmd", required=True)
    _collect_args(sub.add_parser("collect", help="one member or the baseline over the holdout"))
    _report_args(sub.add_parser("report", help="the custodian's scoring and S4 report"))
    args = ap.parse_args(argv)
    if args.cmd == "collect":
        return collect(args, **collect_kw)
    return report(args)


if __name__ == "__main__":
    sys.exit(main())
