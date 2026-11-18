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
today's, byte for byte. Every file is written with LF line ends on every platform (WO-D10-1A).
Nothing here is identity accuracy and nothing is a gate result.

Fault outcomes per case (WO-D12-16r): `parent_already_held` (a HOLD that adds no reason to its
parent pair's HOLD; never counted as met, nor as exercise: its declared documents are counted
only in `parent_already_held_declared_documents_touched`, and a class with no other case, or on
the candidate arm none that reached a keyed path, reads "not exercised; N parent_already_held"),
`joined` (D12-D13r, `duplicate_region_text` only: an abstention lost - an untouched anchor
unresolved (AMBIGUOUS or collision-held) in the parent's compile and matched in the case's - or a
join added), `expectation_met`, `expectation_not_met`. A class that applies to no pair is
`not_applicable` with 0 cases. Exit 0; 1 when an arm or a fault class has DIVERGED,
a phantom, a compile error (pairs), an unmet or `joined` case, or a by-construction figure that
is off or not exercised; 2 when a flag or the base is unusable, with nothing written.
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
from collections.abc import Sequence
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
from benchmark.u06_equivalence.faults import (
    LINEAGE_CLASS,
    FaultCase,
    generate,
    not_applicable,
)
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
# the paths `_paths` can name; `fact_keys.refusal` has two detectors
DECLARED_PATHS = ("keyed", "unchanged", "no_previous", "refused:D-MISSING", "refused:D-DUP")
States = dict[tuple[str, str], str]
Measured = tuple[CaseResult, Counter[str] | None, dict[str, str] | None, States | None]


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
        counts.update(dict.fromkeys((f"declared_documents_{p}" for p in DECLARED_PATHS), 0))
        counts.update(f"declared_documents_{path}" for path in paths.values())
    return counts


def _arm_case(
    before: Docs, after: Docs, *, arm: Arm, requested_at: datetime, scope: dict[str, str]
) -> Measured:
    """`run_case` for one arm, keeping what the counts need and each incremental unit's identity
    state by (source, anchor). A compile that raises is that case's HOLD named by the exception
    type only, exactly as `run_case`; judging is not caught."""
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
            None,
        )
    if len(seen) != 1:
        raise RuntimeError(f"expected one previous world, observed {len(seen)}")
    paths = _paths(
        seen[0], incremental, after, declarations, scope.get("tenant_id", DEFAULT_TENANT)
    )
    counts = _counts(seen[0], incremental, paths, declared=bool(declarations))
    units = incremental.candidate.units
    states: States = {(unit.source_id, unit.anchor): unit.identity_state for unit in units}
    if len(states) != len(units):
        raise RuntimeError("two incremental units share one (source, anchor)")
    return judge(incremental, cold), counts, paths, states


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


def _met(expected: str, verdict: str) -> bool:
    return verdict == "HOLD" if expected == "hold" else verdict in ("EQUAL", "HOLD")


def _anchors(docs: Docs, tenant: str) -> dict[tuple[str, str], tuple[str, Any]]:
    """(source, anchor) -> what a fault can change about that unit: its region and its document's
    title (part of the unit's path). The anchor is the compiler's: native object id, else region."""
    return {
        (_source(d, tenant), r.native_object_id or r.region_id): (d.title, r)
        for d in docs
        for r in d.regions
    }


def _lineage(
    parent: Measured, case: Measured, parent_after: Docs, case_after: Docs, tenant: str
) -> dict[str, Any] | None:
    """D12-D13r, from what the two incremental compiles returned (None when either raised).
    `abstention_lost`: anchors the fault did not touch (same region, same title) that the parent
    pair's incremental compile left unresolved (AMBIGUOUS or collision-held) and the case's
    matched. `joins_added`: cross-key MATCHED and cross-key MODIFIED_CLAIM above the parent
    pair's counts."""
    (_, parent_counts, _, parent_states), (_, counts, _, states) = parent, case
    if parent_counts is None or counts is None or parent_states is None or states is None:
        return None
    before, after = _anchors(parent_after, tenant), _anchors(case_after, tenant)
    untouched = [key for key, value in before.items() if after.get(key) == value]
    if any(key not in parent_states or key not in states for key in untouched):
        raise RuntimeError("an anchor of the after side has no incremental unit")
    lost = sum(parent_states[k] == "unresolved" and states[k] == "matched" for k in untouched)
    return {
        "abstention_lost": lost,
        "joins_added": {
            name: max(counts[name] - parent_counts[name], 0)
            for name in ("cross_key_matched", "modified_claim_cross_key")
        },
    }


def _outcome(
    case: FaultCase, result: CaseResult, parent: CaseResult, lineage: dict[str, Any] | None
) -> str:
    """D12-D13r: for LINEAGE_CLASS a verdict inside the expectation is met only if no abstention
    is lost and no join is added (else `joined`, whatever the parent; lineage not measured is not
    met). A HOLD that adds no reason to its parent's HOLD is `parent_already_held` and never
    counts as met."""
    lineage_class = case.fault_class == LINEAGE_CLASS and result.verdict != "DIVERGED"
    if (
        lineage_class
        and lineage is not None
        and (lineage["abstention_lost"] or any(lineage["joins_added"].values()))
    ):
        return "joined"
    if result.verdict == parent.verdict == "HOLD" and set(result.hold_reasons) <= set(
        parent.hold_reasons
    ):
        return "parent_already_held"
    if lineage_class and lineage is None:
        return "expectation_not_met"
    return "expectation_met" if _met(case.expected, result.verdict) else "expectation_not_met"


_FAULT_COLUMNS = (
    "cases",
    "equal",
    "hold",
    "diverged",
    "phantom",
    "expectation_met",
    "expectation_not_met",
    "joined",
    "parent_already_held",
    "abstention_lost",
    "joins_added_cross_key_matched",
    "joins_added_modified_claim_cross_key",
    "lineage_not_measured",
)


def _run_faults(
    cases: Sequence[FaultCase],
    base: Sequence[tuple[Docs, Docs]],
    case_ids: Sequence[str],
    parents: Sequence[Measured],
    skipped: Sequence[str],
    *,
    arm: Arm,
    requested_at: datetime,
    scope: dict[str, str],
    sink_path: Path,
) -> tuple[dict[str, Any], list[CaseResult], int]:
    """Per class report, the case results, and how many documents of the evaluated fault cases
    (not `parent_already_held`) took the keyed path. `parents[k]` is this arm's measurement of
    base pair k."""
    declared = {item.connector_type for item in DECLARATIONS} if arm == "candidate" else set()
    tenant = scope.get("tenant_id", DEFAULT_TENANT)
    classes: dict[str, Counter[str]] = {}
    touched_paths: dict[str, Counter[str]] = defaultdict(Counter)
    results: list[CaseResult] = []
    keyed_documents = 0
    with sink_path.open("w", encoding="utf-8", newline="\n") as sink:
        for case in cases:
            measured = _arm_case(
                case.before_docs, case.after_docs, arm=arm, requested_at=requested_at, scope=scope
            )
            result, _, paths, _ = measured
            results.append(result)
            parent = parents[case.parent_pair_id]
            parent_after = base[case.parent_pair_id][1]
            lineage = _lineage(parent, measured, parent_after, case.after_docs, tenant)
            outcome = _outcome(case, result, parent[0], lineage)
            # a case not counted as met is not counted as exercise either (WO-D12-16r A)
            counted = outcome != "parent_already_held"
            keyed = sum(path == "keyed" for path in (paths or {}).values())
            keyed_documents += keyed if counted else 0
            touched = _touched(case, parent_after, tenant)
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
            bucket[outcome] += 1
            if lineage is None:
                bucket["lineage_not_measured"] += 1
            else:
                bucket["abstention_lost"] += lineage["abstention_lost"]
                for name, added in lineage["joins_added"].items():
                    bucket[f"joins_added_{name}"] += added
            if counted:
                bucket["declared_documents_touched"] += len(mine)
                bucket["declared_documents_exercised"] += mine.count("keyed")
                touched_paths[case.fault_class].update(mine)
            else:  # shown in its own column, never mixed into the exercise figures
                bucket["parent_already_held_declared_documents_touched"] += len(mine)
            line = {
                "case_id": case.case_id,
                "fault_class": case.fault_class,
                "parent_case_id": case_ids[case.parent_pair_id],
                "expected": case.expected,
                **asdict(result),
                "touched_declared_paths": dict(Counter(mine)),
                "declared_documents_keyed": None if paths is None else keyed,
                "outcome": outcome,
                "abstention_lost": None if lineage is None else lineage["abstention_lost"],
                "joins_added": None if lineage is None else lineage["joins_added"],
            }
            sink.write(json.dumps(line) + "\n")
    for name in skipped:
        classes[name] = Counter()  # not_applicable: 0 cases, never met, never dropped
    report: dict[str, Any] = {}
    for name, bucket in classes.items():
        row: dict[str, Any] = {k: bucket[k] for k in _FAULT_COLUMNS}
        held = bucket["parent_already_held"]
        evaluated = bucket["cases"] - held
        status = f"expectation met in {bucket['expectation_met']} of {evaluated} cases"
        if held:
            status += f", {held} parent_already_held"
        # never a pass for a class no evaluated case exercised: on the candidate arm, one that
        # reached no declared document's keyed path outside the parent-held cases
        if not evaluated or (arm == "candidate" and not bucket["declared_documents_exercised"]):
            status = "not exercised" + (f"; {held} parent_already_held" if held else "")
        if arm == "candidate":
            for column in (
                "declared_documents_touched",
                "declared_documents_exercised",
                "parent_already_held_declared_documents_touched",
            ):
                row[column] = bucket[column]
            row["touched_declared_paths"] = dict(sorted(touched_paths[name].items()))
        if bucket["joined"]:
            status += f"; joined in {bucket['joined']} of {bucket['cases']} cases"
        row["status"] = "not_applicable" if name in skipped else status
        report[name] = row
    return report, results, keyed_documents


def _figure(value: int | None, why: str, name: str, denominator: int | None) -> dict[str, Any]:
    """A by-construction figure with its denominator: `not exercised` (never held) when nothing
    could have made it more than 0."""
    held = "held" if value == 0 else "not held"
    return {
        "value": value,
        "expected": 0,
        "why": why,
        "denominator": {name: denominator},
        "status": held if denominator else "not exercised",
    }


def _both_arms(
    loaded: Loaded,
    *,
    requested_at: datetime,
    scope: dict[str, str],
    faults: list[FaultCase],
    skipped: Sequence[str],
    out: Path,
) -> tuple[dict[str, Any], bool]:
    arms: dict[str, Any] = {}
    rows: dict[str, list[tuple[str, CaseResult]]] = {}
    fault_reports: dict[str, Any] = {}
    fault_results: list[CaseResult] = []
    fault_keyed = 0
    for arm in ARMS:
        rows[arm] = []
        parents: list[Measured] = []
        total: Counter[str] = Counter()
        without = 0
        with (out / f"results.{arm}.jsonl").open("w", encoding="utf-8", newline="\n") as sink:
            for case, before, after in loaded:
                measured = _arm_case(before, after, arm=arm, requested_at=requested_at, scope=scope)
                parents.append(measured)
                result, counts, _, _ = measured
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
            fault_reports[arm], results, keyed = _run_faults(
                faults,
                base,
                ids,
                parents,
                skipped,
                arm=arm,
                requested_at=requested_at,
                scope=scope,
                sink_path=out / f"faults.{arm}.jsonl",
            )
            fault_results += results
            if arm == "candidate":
                fault_keyed += keyed
    cand = arms["candidate"]
    pair_keyed = cand["counts"].get("declared_documents_keyed")  # None: no pair was measured
    disagreements = cand["hold_by_reason"].get("COMPILE_ERROR:FactKeyDisagreement", 0) + sum(
        "COMPILE_ERROR:FactKeyDisagreement" in r.hold_reasons for r in fault_results
    )
    # A figure no case measured is None, never 0, and does not hold; nor does a figure whose
    # denominator is 0 or None ("not exercised").
    by_construction: dict[str, dict[str, Any]] = {
        "candidate.cross_key_matched_on_keyed_documents": _figure(
            cand["counts"].get("cross_key_matched_on_keyed_documents"),
            "a keyed unit is offered only to the previous unit with its own key (ADR-010 §4)",
            "declared_documents_keyed",
            pair_keyed,
        ),
        "candidate.modified_claim_cross_key_on_keyed_documents": _figure(
            cand["counts"].get("modified_claim_cross_key_on_keyed_documents"),
            "a cross-key modification needs a cross-key match, which the keyed path never makes",
            "declared_documents_keyed",
            pair_keyed,
        ),
        "candidate.fact_key_disagreements": _figure(
            disagreements,
            "the compiler raises FactKeyDisagreement rather than publish a keyed world its "
            "diff disagrees with (ADR-010 §5); pairs and faults",
            "declared_documents_keyed",
            (pair_keyed or 0) + fault_keyed,
        ),
    }
    if LINEAGE_CLASS in fault_reports.get("candidate", {}):
        dup = fault_reports["candidate"][LINEAGE_CLASS]
        by_construction[f"faults.candidate.{LINEAGE_CLASS}.declared_documents_exercised"] = _figure(
            dup["declared_documents_exercised"],
            "the pinned key pattern rejects the fault's '-dup' suffix, so the faulted "
            "document is refused (D-MISSING) and stays on today's path (D12-D12b)",
            "declared_documents_touched",
            dup["declared_documents_touched"],
        )
    held = all(item["status"] == "held" for item in by_construction.values())
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
            row["diverged"] or row["phantom"] or row["expectation_not_met"] or row["joined"]
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
    rows: list[tuple[str, CaseResult]] = []
    try:  # the whole base is read, verified and the faults generated before anything is written
        raw = args.manifest.read_bytes()
        manifest = json.loads(raw)
        scope = {
            k: manifest[k] for k in ("tenant_id", "workspace_id", "collection_id") if k in manifest
        }
        if not all(isinstance(value, str) for value in scope.values()):
            raise TypeError("a scope field is not a string")
        requested_at = datetime.fromisoformat(manifest["requested_at"])
        if requested_at.utcoffset() is None:
            raise ValueError("requested_at carries no timezone")
        loaded = [
            (c, _load(args.manifest.parent, c["before"]), _load(args.manifest.parent, c["after"]))
            for c in manifest["cases"]
        ]
        if not loaded or not all(
            isinstance(c["case_id"], str) and isinstance(c["stratum"], str) and (b or a)
            for c, b, a in loaded
        ):
            raise ValueError("no cases, or a case without case_id, stratum or any document")
        faults = (
            generate([(b, a) for _, b, a in loaded], n=args.faults, seed=args.fault_seed)
            if args.faults
            else []
        )
    except ManifestHashMismatch as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as exc:
        # the type only: a validation message can carry document text
        print(f"REFUSED: unusable base ({type(exc).__name__})", file=sys.stderr)
        return 2
    if args.fact_key_mode == "candidate":
        skipped = not_applicable(faults, args.faults)
        args.out.mkdir(parents=True, exist_ok=True)
        report, failed = _both_arms(
            loaded,
            requested_at=requested_at,
            scope=scope,
            faults=faults,
            skipped=skipped,
            out=args.out,
        )
        if args.faults:
            report["fault_cases"], report["fault_seed"] = len(faults), args.fault_seed
            report["fault_cases_requested"] = args.faults
        report.update(_provenance(raw))
        (args.out / "summary.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8", newline="\n"
        )
        print(json.dumps(report, indent=2))
        return 1 if failed else 0
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "results.jsonl").open("w", encoding="utf-8", newline="\n") as sink:
        for case, before, after in loaded:
            result = run_case(before, after, requested_at=requested_at, **scope)
            rows.append((case["stratum"], result))
            line = {"case_id": case["case_id"], "stratum": case["stratum"], **asdict(result)}
            sink.write(json.dumps(line) + "\n")
    summary = {**summarize(rows), **_provenance(raw)}
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8", newline="\n"
    )
    print(json.dumps(summary, indent=2))
    compile_error = _compile_error([r for _, r in rows])
    return 1 if summary["diverged"] or summary["phantom_total"] or compile_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
