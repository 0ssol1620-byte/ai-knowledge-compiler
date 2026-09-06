#!/usr/bin/env python3
"""P3b driver: the P3 injection matrix against a boundary with a legible exception path.

Same seventeen scenarios, same expectations, same assertions — plus the three
the P3b protocol adds, and two scenarios aimed squarely at where a naive repair
falls back to an empty evidence tuple.

P3 v1's driver, subject and receipt are untouched. This runs beside them.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "activation"))

from common import NS, canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from knowledge_store_p3b import (  # noqa: E402
    ARTIFACTS,
    DEFAULT_PREDICATES,
    FAIL,
    INPUTS,
    NOT_REACHED,
    PASS,
    POINTER_EVIDENCE_PREDICATES,
    UNVERIFIABLE,
    Candidate,
    GateResult,
    KnowledgeStore,
    RefusalEvent,
    RefusalWithoutEvidence,
    admits,
)

PROTOCOL = NS / "protocols" / "P3b_refusal_legibility.yaml"
SUBJECT = NS / "activation" / "knowledge_store_p3b.py"
READER_THREADS = 6
READS_PER_THREAD = 500

REQUIRED_REFUSAL_FIELDS = (
    "predicate",
    "state",
    "reason_code",
    "candidate_state_id",
    "candidate_state_digest",
    "evaluation_id",
    "evidence_refs",
)


def healthy_candidate(source: Path, candidate_id: str) -> Candidate:
    build = json.loads(source.read_text(encoding="utf-8"))
    state = {
        artifact: value
        for artifact, value in build["state"].items()
        if not value.startswith("UNVERIFIABLE")
    }
    sensitivity = {
        artifact: build["artifact_detail"][artifact]["sensitivity"] for artifact in state
    }
    units = sorted(
        {artifact.split(":", 1)[1] for artifact in state if artifact.startswith("section:")}
    )
    return Candidate(
        candidate_id=candidate_id,
        state=state,
        sensitivity=sensitivity,
        fingerprints={artifact: "fp:" + artifact for artifact in state},
        receipts={artifact: {"output_digest": value} for artifact, value in state.items()},
        declared_inputs=tuple(units),
        present_inputs=tuple(units),
        authorised_units=frozenset(units),
        reachable_units=frozenset(units),
    )


def replace(candidate: Candidate, **changes: Any) -> Candidate:
    fields = {
        "candidate_id": candidate.candidate_id,
        "state": dict(candidate.state),
        "sensitivity": dict(candidate.sensitivity),
        "fingerprints": dict(candidate.fingerprints),
        "receipts": dict(candidate.receipts),
        "declared_inputs": candidate.declared_inputs,
        "present_inputs": candidate.present_inputs,
        "authorised_units": candidate.authorised_units,
        "reachable_units": candidate.reachable_units,
    }
    fields.update(changes)
    return Candidate(**fields)


def injections(base: Candidate) -> list[dict[str, Any]]:
    first_artifact = sorted(base.state)[0]
    second_artifact = sorted(base.state)[1]
    scenarios: list[dict[str, Any]] = []

    def add(
        scenario_id: str, category: str, candidate: Candidate, predicate: str, state: str
    ) -> None:
        scenarios.append(
            {
                "id": scenario_id,
                "category": category,
                "candidate": candidate,
                "expected_predicate": predicate,
                "expected_state": state,
                "expected_admitted": state == PASS,
            }
        )

    add(
        "SRC_PARTIAL_FETCH",
        "source",
        replace(base, candidate_id="c-src-partial", present_inputs=base.present_inputs[1:]),
        "source_complete",
        FAIL,
    )
    add(
        "SRC_EMPTY_LISTING",
        "source",
        replace(base, candidate_id="c-src-empty", present_inputs=()),
        "source_complete",
        FAIL,
    )
    add(
        "SRC_MISSING_REVISION",
        "source",
        replace(
            base,
            candidate_id="c-src-missing-revision",
            state={k: v for k, v in base.state.items() if k != first_artifact},
            sensitivity={k: v for k, v in base.sensitivity.items() if k != first_artifact},
            fingerprints={k: v for k, v in base.fingerprints.items() if k != first_artifact},
            receipts={k: v for k, v in base.receipts.items() if k != first_artifact},
        ),
        "sensitivity_recorded",
        PASS,
    )
    add(
        "ID_MISSING_CRITICAL_SIGNAL",
        "identity",
        replace(
            base,
            candidate_id="c-id-no-sensitivity",
            sensitivity={**base.sensitivity, first_artifact: []},
        ),
        "sensitivity_recorded",
        UNVERIFIABLE,
    )
    add(
        "ID_FINGERPRINT_ABSENT",
        "identity",
        replace(
            base,
            candidate_id="c-id-no-fingerprint",
            fingerprints={**base.fingerprints, first_artifact: None},
        ),
        "fingerprint_present",
        UNVERIFIABLE,
    )
    add(
        "BUILD_ARTIFACT_CRASH",
        "build",
        replace(
            base,
            candidate_id="c-build-crash",
            receipts={k: v for k, v in base.receipts.items() if k != first_artifact},
        ),
        "receipt_matches_output",
        UNVERIFIABLE,
    )
    add(
        "BUILD_NONDETERMINISTIC_OUTPUT",
        "build",
        replace(
            base,
            candidate_id="c-build-nondeterministic",
            receipts={
                **base.receipts,
                first_artifact: {"output_digest": base.state[second_artifact]},
            },
        ),
        "receipt_matches_output",
        FAIL,
    )
    add(
        "RCPT_MISSING",
        "receipt",
        replace(base, candidate_id="c-rcpt-missing", receipts={}),
        "receipt_matches_output",
        UNVERIFIABLE,
    )
    add(
        "RCPT_WRONG_DIGEST",
        "receipt",
        replace(
            base,
            candidate_id="c-rcpt-wrong",
            receipts={
                **base.receipts,
                second_artifact: {"output_digest": "sha256:" + "0" * 64},
            },
        ),
        "receipt_matches_output",
        FAIL,
    )
    add(
        "PERM_UNAUTHORISED_UNIT_REACHABLE",
        "permission",
        replace(
            base,
            candidate_id="c-perm-leak",
            authorised_units=frozenset(list(base.authorised_units)[1:]),
        ),
        "permission_respected",
        FAIL,
    )
    return scenarios


def raising_predicate(_: Candidate) -> GateResult:
    # The message deliberately contains something that must never reach a
    # refusal record: A7 fails if any part of it does.
    raise RuntimeError("SENSITIVE-FRAGMENT-DO-NOT-RECORD /etc/secret token=abc123")


def run(build: Path) -> int:
    started = now()
    base = healthy_candidate(build, "c-healthy")
    initial = {"artifact:genesis": "sha256:" + "1" * 64}
    store = KnowledgeStore("state-000", initial)
    declared = tuple(name for name, _, _ in DEFAULT_PREDICATES)

    rows: list[dict[str, Any]] = []
    assertion_failures: list[dict[str, Any]] = []

    def check_refusal_contract(scenario_id: str, verdict: Any) -> dict[str, Any]:
        refusal = verdict.refusal
        if refusal is None:
            return {}
        record = refusal.as_record()
        missing = [
            field
            for field in REQUIRED_REFUSAL_FIELDS
            if not record.get(field)
            and not (field == "evidence_refs" and refusal.predicate in POINTER_EVIDENCE_PREDICATES)
        ]
        if missing:
            assertion_failures.append(
                {
                    "assertion": "A6",
                    "scenario": scenario_id,
                    "detail": "refusal missing required fields: " + ",".join(missing),
                }
            )
        if not refusal.evidence_refs and refusal.predicate not in POINTER_EVIDENCE_PREDICATES:
            assertion_failures.append(
                {
                    "assertion": "A3",
                    "scenario": scenario_id,
                    "detail": "refusal carried no evidence reference",
                }
            )
        blob = json.dumps(record, ensure_ascii=False)
        leaked = [
            token
            for token in ("SENSITIVE-FRAGMENT", "/etc/secret", "token=abc123", "Traceback")
            if token in blob
        ]
        if leaked:
            assertion_failures.append(
                {
                    "assertion": "A7",
                    "scenario": scenario_id,
                    "detail": "exception text reached the refusal record: " + ",".join(leaked),
                }
            )
        return {
            "refusal_required_fields_present": not missing,
            "refusal_missing_fields": missing,
            "refusal_reason_code": refusal.reason_code,
            "refusal_evidence_ref_count": len(refusal.evidence_refs),
            "refusal_evidence_sample": list(refusal.evidence_refs[:3]),
            "refusal_evaluation_id": refusal.evaluation_id,
            "refusal_candidate_state_digest": refusal.candidate_state_digest,
            "exception_text_leaked": leaked,
        }

    def record(
        scenario_id: str,
        category: str,
        verdict: Any,
        expected_admitted: bool,
        expected_predicate: str | None,
        expected_state: str | None,
        before_reference: str,
    ) -> None:
        actual_predicate = verdict.refusal.predicate if verdict.refusal else None
        actual_state = verdict.refusal.state if verdict.refusal else PASS
        matched = verdict.admitted == expected_admitted and (
            expected_predicate is None
            or expected_admitted
            or (actual_predicate == expected_predicate and actual_state == expected_state)
        )
        reference, state = store.read()
        if not verdict.admitted and reference != before_reference:
            assertion_failures.append(
                {
                    "assertion": "A1",
                    "scenario": scenario_id,
                    "detail": "active reference moved on refusal",
                }
            )
        if verdict.admitted and any(
            item.state in (NOT_REACHED, UNVERIFIABLE) for item in verdict.results
        ):
            assertion_failures.append(
                {
                    "assertion": "A4",
                    "scenario": scenario_id,
                    "detail": "admitted with an unevaluated predicate",
                }
            )
        rows.append(
            {
                "scenario": scenario_id,
                "category": category,
                "expected_admitted": expected_admitted,
                "expected_predicate": expected_predicate,
                "expected_state": expected_state,
                "actual_admitted": verdict.admitted,
                "actual_predicate": actual_predicate,
                "actual_state": actual_state,
                "matched_expectation": matched,
                "gate_states": {item.predicate: item.state for item in verdict.results},
                "active_reference_before": before_reference,
                "active_reference_after": reference,
                "active_state_readable": bool(state),
                **check_refusal_contract(scenario_id, verdict),
            }
        )

    # --- positive control ---------------------------------------------------
    before = store.active_reference
    verdict = store.publish(base, expected_active=before)
    record("CTRL_HEALTHY_CANDIDATE", "control", verdict, True, None, None, before)
    healthy_admitted = verdict.admitted

    trimmed = tuple(item for item in verdict.results if item.predicate != "source_complete")
    break_control_admits = admits(trimmed, declared)
    rows.append(
        {
            "scenario": "CTRL_BREAK_THE_GATE",
            "category": "control",
            "expected_admitted": False,
            "actual_admitted": break_control_admits,
            "matched_expectation": break_control_admits is False,
            "detail": "admission evaluated against a result set with one predicate removed",
        }
    )

    for scenario in injections(base):
        before = store.active_reference
        verdict = store.publish(scenario["candidate"], expected_active=before)
        record(
            scenario["id"],
            scenario["category"],
            verdict,
            scenario["expected_admitted"],
            scenario["expected_predicate"],
            scenario["expected_state"],
            before,
        )

    # --- a predicate that raises -------------------------------------------
    before = store.active_reference
    verdict = store.publish(
        replace(base, candidate_id="c-predicate-raises"),
        predicates=(("raising", raising_predicate, ARTIFACTS), *DEFAULT_PREDICATES),
        expected_active=before,
    )
    record("BUILD_PREDICATE_RAISES", "build", verdict, False, "raising", UNVERIFIABLE, before)
    raise_reason_first = verdict.refusal.reason_code if verdict.refusal else None

    # --- a predicate that raises while its domain is empty -------------------
    before = store.active_reference
    empty_domain = replace(
        base,
        candidate_id="c-raise-empty-domain",
        state={},
        sensitivity={},
        fingerprints={},
        receipts={},
        declared_inputs=(),
        present_inputs=(),
        authorised_units=frozenset(),
        reachable_units=frozenset(),
    )
    verdict = store.publish(
        empty_domain,
        predicates=(("raising", raising_predicate, INPUTS), *DEFAULT_PREDICATES),
        expected_active=before,
    )
    record("RAISE_ON_EMPTY_DOMAIN", "build", verdict, False, "raising", UNVERIFIABLE, before)

    # --- a predicate that raises in every position ---------------------------
    position_rows: list[dict[str, Any]] = []
    reason_codes: set[str] = set()
    for position in ("first", "last"):
        for index in range(len(DEFAULT_PREDICATES)):
            name, _, domain = DEFAULT_PREDICATES[index]
            others = tuple(
                item for offset, item in enumerate(DEFAULT_PREDICATES) if offset != index
            )
            swapped = (name + "_raising", raising_predicate, domain)
            order = (swapped, *others) if position == "first" else (*others, swapped)
            probe = KnowledgeStore("s0", initial)
            outcome = probe.publish(
                replace(base, candidate_id="c-raise-" + position + "-" + name),
                predicates=order,
                expected_active="s0",
            )
            refusal = outcome.refusal
            ok = (
                not outcome.admitted
                and refusal is not None
                and bool(refusal.evidence_refs)
                and refusal.reason_code.startswith("PREDICATE_RAISED:")
                and bool(refusal.evaluation_id)
                and bool(refusal.candidate_state_digest)
            )
            if refusal is not None and refusal.reason_code.startswith("PREDICATE_RAISED:"):
                reason_codes.add(refusal.reason_code)
            if not ok:
                assertion_failures.append(
                    {
                        "assertion": "A6",
                        "scenario": "RAISE_IN_EVERY_POSITION",
                        "detail": position + ":" + name,
                    }
                )
            position_rows.append(
                {
                    "position": position,
                    "predicate": name,
                    "admitted": outcome.admitted,
                    "refusing_predicate": refusal.predicate if refusal else None,
                    "reason_code": refusal.reason_code if refusal else None,
                    "evidence_ref_count": len(refusal.evidence_refs) if refusal else 0,
                    "contract_satisfied": ok,
                }
            )
    if len(reason_codes) > 1:
        assertion_failures.append(
            {
                "assertion": "A8",
                "scenario": "RAISE_IN_EVERY_POSITION",
                "detail": "reason codes differed: " + ",".join(sorted(reason_codes)),
            }
        )
    if raise_reason_first is not None and reason_codes and raise_reason_first not in reason_codes:
        assertion_failures.append(
            {
                "assertion": "A8",
                "scenario": "BUILD_PREDICATE_RAISES",
                "detail": "reason code not stable across scenarios",
            }
        )
    rows.append(
        {
            "scenario": "RAISE_IN_EVERY_POSITION",
            "category": "build",
            "expected_admitted": False,
            "actual_admitted": any(row["admitted"] for row in position_rows),
            "positions_tested": len(position_rows),
            "all_contracts_satisfied": all(row["contract_satisfied"] for row in position_rows),
            "distinct_reason_codes": sorted(reason_codes),
            "matched_expectation": all(row["contract_satisfied"] for row in position_rows),
            "detail_rows": position_rows,
        }
    )

    # --- activation ---------------------------------------------------------
    before = store.active_reference
    verdict = store.publish(replace(base, candidate_id="c-act-stale"), expected_active="state-000")
    record(
        "ACT_CAS_STALE_EXPECTATION",
        "activation",
        verdict,
        False,
        "pointer_compare_and_swap",
        FAIL,
        before,
    )

    before = store.active_reference
    outcomes: list[Any] = []
    barrier = threading.Barrier(2)

    def contend(name: str) -> None:
        candidate = replace(base, candidate_id=name)
        barrier.wait()
        outcomes.append(store.publish(candidate, expected_active=before))

    threads = [
        threading.Thread(target=contend, args=("c-race-" + str(index),)) for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    admitted_count = sum(1 for item in outcomes if item.admitted)
    refused = [item for item in outcomes if not item.admitted]
    rows.append(
        {
            "scenario": "ACT_CONCURRENT_CANDIDATE",
            "category": "activation",
            "expected_admitted": False,
            "expected_predicate": "pointer_compare_and_swap",
            "expected_state": FAIL,
            "actual_admitted": admitted_count == 2,
            "admitted_count": admitted_count,
            "actual_predicate": refused[0].refusal.predicate if refused else None,
            "actual_state": refused[0].refusal.state if refused else None,
            "matched_expectation": admitted_count == 1
            and bool(refused)
            and refused[0].refusal.predicate == "pointer_compare_and_swap",
            "active_reference_after": store.active_reference,
        }
    )

    # --- recovery does not rewrite a failure --------------------------------
    refusals_before = len(store.refusals)
    refusal_snapshot = [item.as_record() for item in store.refusals]
    before = store.active_reference
    verdict = store.publish(replace(base, candidate_id="c-repaired"), expected_active=before)
    survived = [item.as_record() for item in store.refusals][:refusals_before] == refusal_snapshot
    if not survived:
        assertion_failures.append(
            {
                "assertion": "A5",
                "scenario": "RCPT_OVERWRITTEN_AFTER_REFUSAL",
                "detail": "a refusal event changed",
            }
        )
    rows.append(
        {
            "scenario": "RCPT_OVERWRITTEN_AFTER_REFUSAL",
            "category": "receipt",
            "expected_admitted": True,
            "actual_admitted": verdict.admitted,
            "earlier_refusals_survived_verbatim": survived,
            "refusal_count": len(store.refusals),
            "matched_expectation": verdict.admitted and survived,
        }
    )

    # --- concurrent readers -------------------------------------------------
    published = {reference: dict(state) for reference, state in store._states.items()}
    observations: list[bool] = []
    stop = threading.Event()

    def reader() -> None:
        local = []
        for _ in range(READS_PER_THREAD):
            reference, state = store.read()
            local.append(reference in published and state == published[reference])
            if stop.is_set():
                break
        observations.extend(local)

    def writer() -> None:
        for index in range(12):
            candidate = replace(base, candidate_id="c-stream-" + str(index))
            store.publish(candidate, expected_active=store.active_reference)
            published[candidate.candidate_id] = dict(candidate.state)
        stop.set()

    reader_threads = [threading.Thread(target=reader) for _ in range(READER_THREADS)]
    writer_thread = threading.Thread(target=writer)
    for thread in reader_threads:
        thread.start()
    writer_thread.start()
    for thread in reader_threads:
        thread.join()
    writer_thread.join()
    mixed = observations.count(False)
    if mixed:
        assertion_failures.append(
            {
                "assertion": "A2",
                "scenario": "ACT_CONCURRENT_READERS",
                "detail": str(mixed) + " mixed reads",
            }
        )
    rows.append(
        {
            "scenario": "ACT_CONCURRENT_READERS",
            "category": "activation",
            "reads": len(observations),
            "reader_threads": READER_THREADS,
            "mixed_state_observations": mixed,
            "matched_expectation": mixed == 0 and len(observations) >= 2000,
        }
    )

    # --- order invariance ---------------------------------------------------
    order_rows: list[dict[str, Any]] = []
    order_invariant = True
    probes = [("healthy", base)] + [
        (scenario["id"], scenario["candidate"]) for scenario in injections(base)
    ]
    for name, candidate in probes:
        decisions: set[bool] = set()
        refusing: set[str] = set()
        for permutation in itertools.permutations(DEFAULT_PREDICATES):
            probe = KnowledgeStore("s0", initial)
            outcome = probe.publish(candidate, predicates=permutation, expected_active="s0")
            decisions.add(outcome.admitted)
            if outcome.refusal:
                refusing.add(outcome.refusal.predicate)
        if len(decisions) != 1:
            order_invariant = False
        order_rows.append(
            {
                "candidate": name,
                "permutations": 120,
                "decision_invariant": len(decisions) == 1,
                "decision": sorted(decisions),
                "refusing_predicates_seen": sorted(refusing),
            }
        )

    # --- structural enforcement, demonstrated ------------------------------
    try:
        RefusalEvent(
            "c-probe",
            "sensitivity_recorded",
            UNVERIFIABLE,
            (),
            "PROBE",
            "state-000",
            "eval:probe",
            "c-probe",
            "sha256:" + "0" * 64,
        )
        enforcement = {"raised": False, "exception": None}
    except RefusalWithoutEvidence as error:
        enforcement = {"raised": True, "exception": type(error).__name__}
    # and the named exemption still constructs
    try:
        RefusalEvent(
            "c-probe",
            "pointer_compare_and_swap",
            FAIL,
            (),
            "PROBE",
            "state-000",
            "eval:probe",
            "c-probe",
            "sha256:" + "0" * 64,
        )
        enforcement["exempt_predicate_constructs"] = True
    except RefusalWithoutEvidence:
        enforcement["exempt_predicate_constructs"] = False

    declared_ids = {row["id"] for group in DECLARED_SCENARIOS for row in group}
    executed_ids = {row["scenario"] for row in rows}
    not_implemented = sorted(declared_ids - executed_ids)

    refusal_log = [item.as_record() for item in store.refusals]
    refusals_without_evidence = [
        item
        for item in refusal_log
        if not item["evidence_refs"] and item["predicate"] not in POINTER_EVIDENCE_PREDICATES
    ]

    gates = {
        "G_P3B_COVERAGE": {
            "passed": not not_implemented,
            "declared": len(declared_ids),
            "executed": len(executed_ids & declared_ids),
            "not_implemented": not_implemented,
        },
        "G_P3B_EXPECTATIONS": {
            "passed": all(row.get("matched_expectation", True) for row in rows),
            "mismatched": [
                row["scenario"] for row in rows if not row.get("matched_expectation", True)
            ],
        },
        "G_P3B_ASSERTIONS": {
            "passed": not assertion_failures,
            "failures": assertion_failures,
            "refusals_without_evidence": refusals_without_evidence,
        },
        "G_P3B_POSITIVE_CONTROL": {
            "passed": healthy_admitted and break_control_admits is False,
            "healthy_admitted": healthy_admitted,
            "break_control_admitted": break_control_admits,
        },
        "G_P3B_ORDER_INVARIANCE": {
            "passed": order_invariant,
            "candidates_tested": len(order_rows),
            "permutations_each": 120,
        },
        "G_P3B_STRUCTURAL_ENFORCEMENT": {
            "passed": bool(enforcement["raised"])
            and bool(enforcement["exempt_predicate_constructs"]),
            **enforcement,
        },
        "G_P3B_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p3b_refusal_legibility.v1",
        "protocol": "P3b_refusal_legibility",
        "split": "development",
        "started_at": started,
        "ended_at": now(),
        "subject_module": rel(SUBJECT),
        "subject_sha256": sha_file(SUBJECT),
        "p3_v1_subject_untouched": {
            "module": rel(NS / "activation" / "knowledge_store.py"),
            "sha256": sha_file(NS / "activation" / "knowledge_store.py"),
            "note": "P3 v1 stands at FAIL; nothing here amends or re-scores it",
        },
        "candidate_source": rel(build),
        "candidate_source_sha256": sha_file(build),
        "candidate_artifact_count": len(base.state),
        "scenarios": rows,
        "scenarios_sha256": canonical_sha(rows),
        "order_invariance": order_rows,
        "assertion_failures": assertion_failures,
        "refusal_log": refusal_log,
        "activation_log": store.activations,
        "gates": gates,
        "verdict": "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL",
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    written = write_immutable(
        "p3b-refusal-legibility", body, tool=Path(__file__).resolve(), protocol=PROTOCOL
    )
    print(
        json.dumps(
            {
                "verdict": body["verdict"],
                "scenarios": len(rows),
                "refusals": len(refusal_log),
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                **written,
            },
            sort_keys=True,
        )
    )
    return 0 if body["verdict"] == "PASS" else 2


DECLARED_SCENARIOS = [
    [{"id": "SRC_PARTIAL_FETCH"}, {"id": "SRC_EMPTY_LISTING"}, {"id": "SRC_MISSING_REVISION"}],
    [{"id": "ID_MISSING_CRITICAL_SIGNAL"}, {"id": "ID_FINGERPRINT_ABSENT"}],
    [
        {"id": "BUILD_ARTIFACT_CRASH"},
        {"id": "BUILD_NONDETERMINISTIC_OUTPUT"},
        {"id": "BUILD_PREDICATE_RAISES"},
    ],
    [
        {"id": "RCPT_MISSING"},
        {"id": "RCPT_WRONG_DIGEST"},
        {"id": "RCPT_OVERWRITTEN_AFTER_REFUSAL"},
    ],
    [
        {"id": "ACT_CONCURRENT_CANDIDATE"},
        {"id": "ACT_CAS_STALE_EXPECTATION"},
        {"id": "ACT_CONCURRENT_READERS"},
    ],
    [{"id": "PERM_UNAUTHORISED_UNIT_REACHABLE"}],
    [{"id": "CTRL_HEALTHY_CANDIDATE"}, {"id": "CTRL_BREAK_THE_GATE"}],
    [{"id": "RAISE_ON_EMPTY_DOMAIN"}, {"id": "RAISE_IN_EVERY_POSITION"}],
]


def main() -> int:
    parser = argparse.ArgumentParser()
    default = sorted((NS / "artifacts" / "development" / "p0c" / "selective").glob("git-*.json"))
    parser.add_argument("--build", type=Path, default=default[0] if default else None)
    args = parser.parse_args()
    if args.build is None:
        raise SystemExit("no selective build available to use as a candidate")
    return run(args.build)


if __name__ == "__main__":
    raise SystemExit(main())
