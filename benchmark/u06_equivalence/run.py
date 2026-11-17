"""U06 runner. `py -3.13 -m benchmark.u06_equivalence.run --manifest M.json --out DIR`.

Manifest (JSON): {"requested_at": ISO-8601 with tz, "tenant_id"?, "workspace_id"?, "collection_id"?,
"cases": [{"case_id", "stratum", "before": {"path", "sha256"}, "after": {"path", "sha256"}}]}.
Each path (relative to the manifest) holds a JSON list of ProductCoreDocument (camelCase).
`sha256` is of the file bytes; any mismatch refuses the whole run. Write --out outside the repo.

`--fact-key-mode candidate` (ADR-010, WO-D12-13) runs both arms on this commit, off then
candidate with the benchmark's declarations, and writes `results.<arm>.jsonl` and a summary with
per-arm counts, the off -> candidate transition table and a `by_construction` block. `--faults N`
(candidate only) also runs N generated fault cases (`faults.generate`, `--fault-seed`) built from
the manifest's pairs on both arms, into `faults.<arm>.jsonl`. Without these flags the run is
today's, byte for byte. Nothing here is identity accuracy and nothing is a gate result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from akc_cir.identity import source_id
from akc_product_core.contracts import (
    PreviousWorldSnapshot,
    ProductCoreCompileResponse,
    ProductCoreDocument,
)
from akc_product_core.fact_keys import FactKeyDeclaration
from pydantic import TypeAdapter

from benchmark.u06_equivalence.declarations import ASSIGNED_BY, DECLARATIONS
from benchmark.u06_equivalence.faults import FaultCase, generate
from benchmark.u06_equivalence.harness import (
    DEFAULT_TENANT,
    CaseResult,
    compile_pair,
    judge,
    run_case,
)

_DOCS = TypeAdapter(tuple[ProductCoreDocument, ...])
Docs = tuple[ProductCoreDocument, ...]
Arm = Literal["off", "candidate"]
Loaded = list[tuple[dict[str, Any], Docs, Docs]]
ARMS: tuple[Arm, ...] = ("off", "candidate")


class ManifestHashMismatch(RuntimeError):
    pass


def _load(base: Path, ref: dict[str, str]) -> tuple[ProductCoreDocument, ...]:
    data = (base / ref["path"]).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != ref["sha256"].removeprefix("sha256:"):
        raise ManifestHashMismatch(f"{ref['path']}: sha256 {actual} != manifest {ref['sha256']}")
    return _DOCS.validate_json(data)


def summarize(rows: list[tuple[str, CaseResult]]) -> dict[str, object]:
    holds: Counter[str] = Counter()
    strata: dict[str, Counter[str]] = {}
    for stratum, result in rows:
        bucket = strata.setdefault(stratum, Counter())
        bucket[result.verdict.lower()] += 1
        bucket["phantom"] += result.phantom
        if result.verdict == "HOLD":
            holds.update(result.hold_reasons)
    return {
        "cases": len(rows),
        "equal": sum(r.verdict == "EQUAL" for _, r in rows),
        "hold": sum(r.verdict == "HOLD" for _, r in rows),
        "hold_by_reason": dict(holds),
        "diverged": sum(r.verdict == "DIVERGED" for _, r in rows),
        "phantom_total": sum(r.phantom for _, r in rows),
        "per_stratum": {k: dict(v) for k, v in strata.items()},
    }


def _provenance(raw: bytes) -> dict[str, str]:
    git_sha = subprocess.run(
        [shutil.which("git") or "git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return {
        "git_sha": git_sha,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "python": platform.python_version(),
        "host": platform.node(),
    }


def _compile_error(rows: Sequence[CaseResult]) -> bool:
    return any(reason.startswith("COMPILE_ERROR:") for r in rows for reason in r.hold_reasons)


# --------------------------------------------------------------------------- both arms (ADR-010)


def _source(document: ProductCoreDocument, tenant: str) -> str:
    """The compiler's derived source id (it refuses a supplied one that differs)."""
    return document.source_id or source_id(
        tenant_id=tenant, connector_type=document.connector_type, native_id=document.native_id
    )


def _paths(
    previous: PreviousWorldSnapshot,
    incremental: ProductCoreCompileResponse,
    after: Docs,
    declarations: Sequence[FactKeyDeclaration],
    tenant: str,
) -> dict[str, str]:
    """For each declared document of the after side: which path the incremental compile took.

    The compiler records only refusals, so eligibility is read from its rule (ADR-010 §3:
    previous units present and content changed); a refusal for a document the rule calls
    ineligible means this reading is wrong, and it stops instead of guessing."""
    declared = {item.connector_type for item in declarations}
    previous_sha: dict[str, str] = {}
    for unit in previous.units:
        previous_sha.setdefault(unit.source_id, unit.source_content_sha256)
    out: dict[str, str] = {}
    for document in after:
        if document.connector_type not in declared:
            continue
        sid = _source(document, tenant)
        prefix = f"IDENTITY_FACT_KEY_REFUSED:{sid}:"
        refused = sorted(
            r.removeprefix(prefix)
            for r in incremental.candidate.review_reasons
            if r.startswith(prefix)
        )
        if sid not in previous_sha:
            path = "no_previous"
        elif previous_sha[sid] == document.content_sha256:
            path = "unchanged"
        else:
            path = f"refused:{refused[0]}" if refused else "keyed"
        if refused and not path.startswith("refused:"):
            raise RuntimeError(
                f"refusal recorded for {sid}, which the eligibility rule calls {path}"
            )
        out[sid] = path
    return out


def _counts(
    previous: PreviousWorldSnapshot,
    incremental: ProductCoreCompileResponse,
    paths: dict[str, str],
    *,
    declared: bool,
) -> Counter[str]:
    """Structural counts, ids never written. A MATCHED unit is cross-key when its anchor (native
    object id, else region id) is not the anchor of the previous unit whose id it inherited.
    The keyed-document figures exist only for an arm with declarations; every figure a case can
    measure is written, zero included, so a missing figure always means "not measured"."""
    anchors: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for unit in previous.units:
        anchors[unit.logical_id].add((unit.source_id, unit.anchor))
    keyed = {sid for sid, path in paths.items() if path == "keyed"}
    counts: Counter[str] = Counter()
    cross: set[str] = set()
    cross_keyed: set[str] = set()
    for unit in incremental.candidate.units:
        counts["units"] += 1
        counts[f"units_{unit.identity_state}"] += 1
        if unit.identity_state != "matched":
            continue
        origin = anchors.get(unit.logical_id)
        if origin is None:
            counts["matched_id_not_in_previous"] += 1
        elif (unit.source_id, unit.anchor) not in origin:
            cross.add(unit.logical_id)
            if unit.source_id in keyed:
                cross_keyed.add(unit.logical_id)
    modified = [
        str(change["logical_id"])
        for change in cast(list[dict[str, Any]], incremental.candidate.diff["changes"])
        if change["kind"] == "modified_claim"
    ]
    counts["cross_key_matched"] = len(cross)
    counts["modified_claim"] = len(modified)
    counts["modified_claim_cross_key"] = sum(lid in cross for lid in modified)
    counts["relocated_units"] = sum(
        r.startswith("IDENTITY_FACT_KEY_RELOCATED:") for r in incremental.candidate.review_reasons
    )
    if declared:
        counts["cross_key_matched_on_keyed_documents"] = len(cross_keyed)
        counts["modified_claim_cross_key_on_keyed_documents"] = sum(
            lid in cross_keyed for lid in modified
        )
        counts.update(f"declared_documents_{path}" for path in paths.values())
    return counts


def _arm_case(
    before: Docs, after: Docs, *, arm: Arm, requested_at: datetime, scope: dict[str, str]
) -> tuple[CaseResult, Counter[str] | None, dict[str, str] | None]:
    """`run_case` for one arm, keeping what the counts need. A compile that raises is that case's
    HOLD named by the exception type only, exactly as `run_case`; judging is not caught."""
    declarations = DECLARATIONS if arm == "candidate" else ()
    seen: list[PreviousWorldSnapshot] = []

    def keep(previous: PreviousWorldSnapshot) -> PreviousWorldSnapshot:
        seen.append(previous)  # observes the snapshot; returns it unchanged
        return previous

    try:
        incremental, cold = compile_pair(
            before,
            after,
            requested_at=requested_at,
            tamper_previous=keep,
            fact_key_mode=arm,
            fact_key_declarations=declarations,
            **scope,
        )
    except Exception as exc:
        return (
            CaseResult(verdict="HOLD", hold_reasons=(f"COMPILE_ERROR:{type(exc).__name__}",)),
            None,
            None,
        )
    if len(seen) != 1:
        raise RuntimeError(f"expected one previous world, observed {len(seen)}")
    paths = _paths(
        seen[0], incremental, after, declarations, scope.get("tenant_id", DEFAULT_TENANT)
    )
    counts = _counts(seen[0], incremental, paths, declared=bool(declarations))
    return judge(incremental, cold), counts, paths


def _reading(summary: dict[str, Any]) -> str:
    text = (
        f"{summary['equal']} of {summary['cases']} pairs proven equal, {summary['hold']} declined"
    )
    return text + (f", {summary['diverged']} diverged" if summary["diverged"] else "")


def _transitions(
    off: list[tuple[str, CaseResult]], cand: list[tuple[str, CaseResult]]
) -> dict[str, Any]:
    total: Counter[str] = Counter()
    strata: dict[str, Counter[str]] = {}
    for (stratum, a), (_, b) in zip(off, cand, strict=True):
        key = f"{a.verdict}->{b.verdict}"
        total[key] += 1
        strata.setdefault(stratum, Counter())[key] += 1
    return {
        "all": dict(sorted(total.items())),
        "per_stratum": {k: dict(sorted(v.items())) for k, v in strata.items()},
    }


def _touched(case: FaultCase, base_after: Docs, tenant: str) -> dict[str, str]:
    """Source id -> connector type of every document a fault changed: added, edited (both of its
    versions name one source) or removed, against the base pair's after side."""
    changed = [d for d in case.after_docs if d not in base_after]
    changed += [d for d in base_after if d not in case.after_docs]
    return {_source(d, tenant): d.connector_type for d in changed}


def _expected(case: FaultCase, arm: Arm, connectors: Iterable[str]) -> str:
    """D12-D12b: repeated text under a declared key is equal_or_hold; undeclared stays `hold`."""
    declared = {item.connector_type for item in DECLARATIONS} if arm == "candidate" else set()
    if case.fault_class == "duplicate_region_text" and declared & set(connectors):
        return "equal_or_hold"
    return case.expected


def _met(expected: str, verdict: str) -> bool:
    return verdict == "HOLD" if expected == "hold" else verdict in ("EQUAL", "HOLD")


def _run_faults(
    cases: Sequence[FaultCase],
    base: Sequence[tuple[Docs, Docs]],
    case_ids: Sequence[str],
    *,
    arm: Arm,
    requested_at: datetime,
    scope: dict[str, str],
    sink_path: Path,
) -> tuple[dict[str, Any], list[CaseResult]]:
    declared = {item.connector_type for item in DECLARATIONS} if arm == "candidate" else set()
    tenant = scope.get("tenant_id", DEFAULT_TENANT)
    classes: dict[str, Counter[str]] = {}
    touched_paths: dict[str, Counter[str]] = defaultdict(Counter)
    results: list[CaseResult] = []
    with sink_path.open("w", encoding="utf-8") as sink:
        for case in cases:
            result, _, paths = _arm_case(
                case.before_docs, case.after_docs, arm=arm, requested_at=requested_at, scope=scope
            )
            results.append(result)
            touched = _touched(case, base[case.parent_pair_id][1], tenant)
            expected = _expected(case, arm, touched.values())
            # the path each touched declared document took: "absent" when the fault removed it,
            # "not_compiled" when the compile raised (that case is a COMPILE_ERROR hold)
            mine = [
                "not_compiled" if paths is None else paths.get(sid, "absent")
                for sid, kind in touched.items()
                if kind in declared
            ]
            bucket = classes.setdefault(case.fault_class, Counter())
            bucket["cases"] += 1
            bucket[result.verdict.lower()] += 1
            bucket["phantom"] += result.phantom
            bucket[
                "expectation_met" if _met(expected, result.verdict) else "expectation_not_met"
            ] += 1
            bucket["declared_documents_touched"] += len(mine)
            bucket["declared_documents_exercised"] += mine.count("keyed")
            touched_paths[case.fault_class].update(mine)
            line = {
                "case_id": case.case_id,
                "fault_class": case.fault_class,
                "parent_case_id": case_ids[case.parent_pair_id],
                "expected": expected,
                **asdict(result),
                "touched_declared_paths": dict(Counter(mine)),
            }
            sink.write(json.dumps(line) + "\n")
    report: dict[str, Any] = {}
    for name, bucket in classes.items():
        row: dict[str, Any] = {
            k: bucket[k]
            for k in (
                "cases",
                "equal",
                "hold",
                "diverged",
                "phantom",
                "expectation_met",
                "expectation_not_met",
            )
        }
        met = f"expectation met in {bucket['expectation_met']} of {bucket['cases']} cases"
        if arm == "candidate":
            row["declared_documents_touched"] = bucket["declared_documents_touched"]
            row["declared_documents_exercised"] = bucket["declared_documents_exercised"]
            row["touched_declared_paths"] = dict(sorted(touched_paths[name].items()))
            # never a pass for a class that reached no declared document's keyed path
            row["status"] = "not exercised" if not bucket["declared_documents_exercised"] else met
        else:
            row["status"] = met
        report[name] = row
    return report, results


def _both_arms(
    loaded: Loaded,
    *,
    requested_at: datetime,
    scope: dict[str, str],
    faults: list[FaultCase],
    out: Path,
) -> tuple[dict[str, Any], bool]:
    arms: dict[str, Any] = {}
    rows: dict[str, list[tuple[str, CaseResult]]] = {}
    fault_reports: dict[str, Any] = {}
    fault_results: list[CaseResult] = []
    for arm in ARMS:
        rows[arm] = []
        total: Counter[str] = Counter()
        without = 0
        with (out / f"results.{arm}.jsonl").open("w", encoding="utf-8") as sink:
            for case, before, after in loaded:
                result, counts, _ = _arm_case(
                    before, after, arm=arm, requested_at=requested_at, scope=scope
                )
                rows[arm].append((case["stratum"], result))
                if counts is None:
                    without += 1
                else:
                    total.update(counts)
                line = {
                    "case_id": case["case_id"],
                    "stratum": case["stratum"],
                    **asdict(result),
                    "counts": dict(sorted(counts.items())) if counts is not None else None,
                }
                sink.write(json.dumps(line) + "\n")
        summary = summarize(rows[arm])
        arms[arm] = {
            **summary,
            "reading": _reading(summary),
            "counts": dict(sorted(total.items())),
            "cases_without_counts": without,
        }
        if faults:
            base = [(before, after) for _, before, after in loaded]
            ids = [case["case_id"] for case, _, _ in loaded]
            fault_reports[arm], results = _run_faults(
                faults,
                base,
                ids,
                arm=arm,
                requested_at=requested_at,
                scope=scope,
                sink_path=out / f"faults.{arm}.jsonl",
            )
            fault_results += results
    cand = arms["candidate"]
    disagreements = cand["hold_by_reason"].get("COMPILE_ERROR:FactKeyDisagreement", 0) + sum(
        "COMPILE_ERROR:FactKeyDisagreement" in r.hold_reasons for r in fault_results
    )
    # A figure no case measured is None, never 0, and does not hold.
    by_construction: dict[str, dict[str, Any]] = {
        "candidate.cross_key_matched_on_keyed_documents": {
            "value": cand["counts"].get("cross_key_matched_on_keyed_documents"),
            "expected": 0,
            "why": "a keyed unit is offered only to the previous unit with its own key "
            "(ADR-010 §4)",
        },
        "candidate.modified_claim_cross_key_on_keyed_documents": {
            "value": cand["counts"].get("modified_claim_cross_key_on_keyed_documents"),
            "expected": 0,
            "why": "a cross-key modification needs a cross-key match, which the keyed path "
            "never makes",
        },
        "candidate.fact_key_disagreements": {
            "value": disagreements,
            "expected": 0,
            "why": "the compiler raises FactKeyDisagreement rather than publish a keyed world its "
            "diff disagrees with (ADR-010 §5); pairs and faults",
        },
    }
    if "duplicate_region_text" in fault_reports.get("candidate", {}):
        dup = fault_reports["candidate"]["duplicate_region_text"]
        by_construction["faults.candidate.duplicate_region_text.declared_documents_exercised"] = {
            "value": dup["declared_documents_exercised"],
            "expected": 0,
            "why": "the pinned key pattern rejects the fault's '-dup' suffix, so the faulted "
            "document is refused (D-MISSING) and stays on today's path (D12-D12b)",
        }
    held = all(item["value"] == item["expected"] for item in by_construction.values())
    report: dict[str, Any] = {
        "fact_key_mode": "candidate",
        "declarations": [
            {
                **{
                    k: getattr(item, k)
                    for k in (
                        "connector_type",
                        "key_pattern",
                        "collision_suffix",
                        "evidence_ref",
                        "evidence_sha256",
                    )
                },
                "assigned_by": ASSIGNED_BY,
            }
            for item in DECLARATIONS
        ],
        "arms": arms,
        "transitions": _transitions(rows["off"], rows["candidate"]),
        "by_construction": by_construction,
        "by_construction_held": held,
    }
    failed = not held or any(
        arms[arm]["diverged"]
        or arms[arm]["phantom_total"]
        or _compile_error([r for _, r in rows[arm]])
        for arm in arms
    )
    if faults:
        report["faults"] = fault_reports
        failed = failed or any(
            row["diverged"] or row["phantom"] or row["expectation_not_met"]
            for arm_report in fault_reports.values()
            for row in arm_report.values()
        )
    return report, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fact-key-mode", choices=("off", "candidate"), default="off")
    parser.add_argument("--faults", type=int, default=0)
    parser.add_argument("--fault-seed", type=int, default=1)
    args = parser.parse_args(argv)
    if args.faults < 0:
        parser.error("--faults must be >= 0")
    if args.faults and args.fact_key_mode != "candidate":
        parser.error("--faults runs both arms; it needs --fact-key-mode candidate")
    raw = args.manifest.read_bytes()
    manifest = json.loads(raw)
    scope = {
        k: manifest[k] for k in ("tenant_id", "workspace_id", "collection_id") if k in manifest
    }
    requested_at = datetime.fromisoformat(manifest["requested_at"])
    rows: list[tuple[str, CaseResult]] = []
    try:  # verify every hash before running anything or writing anything
        loaded = [
            (c, _load(args.manifest.parent, c["before"]), _load(args.manifest.parent, c["after"]))
            for c in manifest["cases"]
        ]
    except ManifestHashMismatch as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if args.fact_key_mode == "candidate":
        # generated before anything is written: a class no pair supports refuses the run
        faults = (
            generate([(b, a) for _, b, a in loaded], n=args.faults, seed=args.fault_seed)
            if args.faults
            else []
        )
        args.out.mkdir(parents=True, exist_ok=True)
        report, failed = _both_arms(
            loaded, requested_at=requested_at, scope=scope, faults=faults, out=args.out
        )
        if faults:
            report["fault_cases"], report["fault_seed"] = len(faults), args.fault_seed
        report.update(_provenance(raw))
        (args.out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1 if failed else 0
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "results.jsonl").open("w", encoding="utf-8") as sink:
        for case, before, after in loaded:
            result = run_case(before, after, requested_at=requested_at, **scope)
            rows.append((case["stratum"], result))
            line = {"case_id": case["case_id"], "stratum": case["stratum"], **asdict(result)}
            sink.write(json.dumps(line) + "\n")
    summary = {**summarize(rows), **_provenance(raw)}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    compile_error = _compile_error([r for _, r in rows])
    return 1 if summary["diverged"] or summary["phantom_total"] or compile_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
