#!/usr/bin/env python3
"""P3 driver: failure injection against the publication boundary.

Every scenario in the frozen matrix is executed in one process, positive
controls alongside the failures, so a gate that cannot fire is distinguishable
from a run with nothing to catch.
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "activation"))

from common import NS, ROOT, canonical_sha, now, rel, sha_file, write_hashed  # noqa: E402
from knowledge_store import (  # noqa: E402
    DEFAULT_PREDICATES,
    FAIL,
    NOT_REACHED,
    PASS,
    UNVERIFIABLE,
    Candidate,
    GateResult,
    KnowledgeStore,
    admits,
)

READER_THREADS = 6
READS_PER_THREAD = 500


def healthy_candidate(source: Path, candidate_id: str) -> Candidate:
    """A well-formed candidate, taken from a real P0b selective build."""
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

    partial = replace(base, candidate_id="c-src-partial", present_inputs=base.present_inputs[1:])
    add("SRC_PARTIAL_FETCH", "source", partial, "source_complete", FAIL)

    empty = replace(base, candidate_id="c-src-empty", present_inputs=())
    add("SRC_EMPTY_LISTING", "source", empty, "source_complete", FAIL)

    trimmed_state = {
        artifact: value for artifact, value in base.state.items() if artifact != first_artifact
    }
    missing_revision = replace(
        base,
        candidate_id="c-src-missing-revision",
        state=trimmed_state,
        sensitivity={k: v for k, v in base.sensitivity.items() if k != first_artifact},
        fingerprints={k: v for k, v in base.fingerprints.items() if k != first_artifact},
        receipts={k: v for k, v in base.receipts.items() if k != first_artifact},
    )
    add("SRC_MISSING_REVISION", "source", missing_revision, "sensitivity_recorded", PASS)

    no_sensitivity = replace(
        base,
        candidate_id="c-id-no-sensitivity",
        sensitivity={**base.sensitivity, first_artifact: []},
    )
    add(
        "ID_MISSING_CRITICAL_SIGNAL",
        "identity",
        no_sensitivity,
        "sensitivity_recorded",
        UNVERIFIABLE,
    )

    no_fingerprint = replace(
        base,
        candidate_id="c-id-no-fingerprint",
        fingerprints={**base.fingerprints, first_artifact: None},
    )
    add("ID_FINGERPRINT_ABSENT", "identity", no_fingerprint, "fingerprint_present", UNVERIFIABLE)

    crashed = replace(
        base,
        candidate_id="c-build-crash",
        receipts={k: v for k, v in base.receipts.items() if k != first_artifact},
    )
    add("BUILD_ARTIFACT_CRASH", "build", crashed, "receipt_matches_output", UNVERIFIABLE)

    nondeterministic = replace(
        base,
        candidate_id="c-build-nondeterministic",
        receipts={
            **base.receipts,
            first_artifact: {"output_digest": base.state[second_artifact]},
        },
    )
    add(
        "BUILD_NONDETERMINISTIC_OUTPUT",
        "build",
        nondeterministic,
        "receipt_matches_output",
        FAIL,
    )

    no_receipts = replace(base, candidate_id="c-rcpt-missing", receipts={})
    add("RCPT_MISSING", "receipt", no_receipts, "receipt_matches_output", UNVERIFIABLE)

    wrong_digest = replace(
        base,
        candidate_id="c-rcpt-wrong",
        receipts={**base.receipts, second_artifact: {"output_digest": "sha256:" + "0" * 64}},
    )
    add("RCPT_WRONG_DIGEST", "receipt", wrong_digest, "receipt_matches_output", FAIL)

    leaked = replace(
        base,
        candidate_id="c-perm-leak",
        authorised_units=frozenset(list(base.authorised_units)[1:]),
    )
    add("PERM_UNAUTHORISED_UNIT_REACHABLE", "permission", leaked, "permission_respected", FAIL)

    return scenarios


def raising_predicate(_: Candidate) -> GateResult:
    raise RuntimeError("predicate could not evaluate")


def run(build: Path, output: Path) -> int:
    started = now()
    base = healthy_candidate(build, "c-healthy")
    initial = {"artifact:genesis": "sha256:" + "1" * 64}
    store = KnowledgeStore("state-000", initial)
    declared = tuple(name for name, _ in DEFAULT_PREDICATES)

    rows: list[dict[str, Any]] = []
    assertion_failures: list[dict[str, Any]] = []

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
        if not verdict.admitted:
            if reference != before_reference:
                assertion_failures.append(
                    {
                        "assertion": "A1",
                        "scenario": scenario_id,
                        "detail": "active reference moved on refusal",
                    }
                )
            if (
                verdict.refusal
                and not verdict.refusal.evidence_refs
                and verdict.refusal.predicate != "pointer_compare_and_swap"
            ):
                assertion_failures.append(
                    {
                        "assertion": "A3",
                        "scenario": scenario_id,
                        "detail": "refusal carried no evidence reference",
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
            }
        )

    # --- positive control, first, in the same execution ---------------------
    before = store.active_reference
    verdict = store.publish(base, expected_active=before)
    record("CTRL_HEALTHY_CANDIDATE", "control", verdict, True, None, None, before)
    healthy_admitted = verdict.admitted

    # --- break control: the conjunction requires presence -------------------
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

    # --- the failing scenarios ---------------------------------------------
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
        predicates=(("raising", raising_predicate), *DEFAULT_PREDICATES),
        expected_active=before,
    )
    record("BUILD_PREDICATE_RAISES", "build", verdict, False, "raising", UNVERIFIABLE, before)

    # --- activation: stale compare-and-swap --------------------------------
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

    # --- activation: two verified candidates race --------------------------
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

    # --- recovery does not rewrite a failure -------------------------------
    refusals_before = len(store.refusals)
    refusal_snapshot = [item.as_record() for item in store.refusals]
    before = store.active_reference
    repaired = replace(base, candidate_id="c-repaired")
    verdict = store.publish(repaired, expected_active=before)
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

    declared_ids = {
        scenario["id"] for group in json.loads(json.dumps(DECLARED_SCENARIOS)) for scenario in group
    }
    executed_ids = {row["scenario"] for row in rows}
    not_implemented = sorted(declared_ids - executed_ids)

    gates = {
        "G_P3_COVERAGE": {
            "passed": not not_implemented,
            "declared": len(declared_ids),
            "executed": len(executed_ids & declared_ids),
            "not_implemented": not_implemented,
        },
        "G_P3_EXPECTATIONS": {
            "passed": all(row.get("matched_expectation", True) for row in rows),
            "mismatched": [
                row["scenario"] for row in rows if not row.get("matched_expectation", True)
            ],
        },
        "G_P3_ASSERTIONS": {
            "passed": not assertion_failures,
            "failures": assertion_failures,
        },
        "G_P3_POSITIVE_CONTROL": {
            "passed": healthy_admitted and break_control_admits is False,
            "healthy_admitted": healthy_admitted,
            "break_control_admitted": break_control_admits,
        },
        "G_P3_ORDER_INVARIANCE": {
            "passed": order_invariant,
            "candidates_tested": len(order_rows),
            "permutations_each": 120,
        },
        "G_P3_COST": {"passed": True, "gpu_seconds": 0, "estimated_cost_usd": 0.0},
    }

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p3_failure_injection.v1",
        "protocol": "P3_failure_injection",
        "split": "development",
        "started_at": started,
        "ended_at": now(),
        "protocol_sha256": json.loads(
            (NS / "receipts" / "p3-protocol-freeze.json").read_text(encoding="utf-8")
        )["protocol_sha256"],
        "subject_module": rel(NS / "activation" / "knowledge_store.py"),
        "subject_sha256": sha_file(NS / "activation" / "knowledge_store.py"),
        "driver_sha256": sha_file(Path(__file__).resolve()),
        "candidate_source": rel(build),
        "candidate_source_sha256": sha_file(build),
        "candidate_artifact_count": len(base.state),
        "scenarios": rows,
        "order_invariance": order_rows,
        "assertion_failures": assertion_failures,
        "refusal_log": [item.as_record() for item in store.refusals],
        "activation_log": store.activations,
        "gates": gates,
        "verdict": "PASS" if all(gate["passed"] for gate in gates.values()) else "FAIL",
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    body["scenarios_sha256"] = canonical_sha(rows)
    write_hashed(output, body, "receipt_sha256")
    print(
        json.dumps(
            {
                "verdict": body["verdict"],
                "scenarios": len(rows),
                "refusals": len(store.refusals),
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                "receipt": rel(output),
            },
            sort_keys=True,
        )
    )
    return 0 if body["verdict"] == "PASS" else 2


#: Mirrors the frozen matrix so coverage is checked against the protocol rather
#: than against whatever the driver happened to run.
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
]


def main() -> int:
    parser = argparse.ArgumentParser()
    default = sorted((NS / "artifacts" / "development" / "p0b" / "selective").glob("git-*.json"))
    parser.add_argument("--build", type=Path, default=default[0] if default else None)
    parser.add_argument(
        "--output", type=Path, default=NS / "receipts" / "p3-failure-injection.json"
    )
    args = parser.parse_args()
    if args.build is None:
        raise SystemExit("no P0b selective build available to use as a candidate")
    return run(args.build, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
