#!/usr/bin/env python3
"""H1-I -- measure whether the promotion gate's check *ordering* is load-bearing.

Protocol: ../PROTOCOL_2026-08-19.md, frozen before this ran.

`evaluate_promotion_gate` is Protected Core and is **not modified**. To sequence
the checks arbitrarily this file reimplements each of the four as an independent
predicate. That reimplementation is the obvious way to accidentally measure the
harness instead of the system, so the fidelity gate in `check_fidelity` is
binding: run in the canonical order the harness must reproduce the real gate's
verdict *and* its first failing step on every constructed state, or the run
reports no ordering result at all.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType  # noqa: E402
from akc_cir.promotion_gate import (  # noqa: E402
    GateOutcome,
    GateStep,
    # Imported rather than reimplemented. The harness needs to control the
    # *order* of the four checks, not to restate what each one means; attempt 1
    # restated this one and got the channel API wrong, which is what the
    # fidelity gate caught. Every internal the harness borrows instead of
    # paraphrasing is one fewer place it can diverge from what it measures.
    _declares_structural,
    artifact_input_fingerprint,
    evaluate_promotion_gate,
)
from akc_cir.recompilation import (  # noqa: E402
    ArtifactState,
    RecompilationPlan,
    RecompilationTarget,
)
from akc_cir.semantic_diff import (  # noqa: E402
    DiffLevel,
    DocumentShape,
    UnitSnapshot,
    diff_documents,
)

ART = "artifact:section:ku_a"
CANONICAL = (
    GateStep.CHANGES_ACCOUNTED,
    GateStep.RECOMPILE_COMPLETE,
    GateStep.INTEGRITY,
    GateStep.NO_STALE_CURRENT,
)


def _shape(blocks: int = 2) -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset({("Intro",)}),
        block_count=blocks,
        table_shapes=(),
        figure_refs=frozenset(),
    )


def _diff(before: str, after: str, unit: str = "ku_a"):
    return diff_documents(
        before_sha256="sha256:" + "1" * 64,
        after_sha256="sha256:" + "2" * 64,
        level=DiffLevel.SEMANTIC,
        before_shape=_shape(),
        after_shape=_shape(),
        before_units=[UnitSnapshot(logical_id=unit, text=before)],
        after_units=[UnitSnapshot(logical_id=unit, text=after)],
        source="h1i",
    )


def _plan(state: ArtifactState) -> RecompilationPlan:
    return RecompilationPlan(
        change_id="chg_h1i",
        targets=(RecompilationTarget(artifact_id=ART, state=state, reason="h1i"),),
        total_artifacts=1,
    )


def _graph(edge: EdgeType = EdgeType.DEPENDS_ON) -> DependencyGraph:
    return DependencyGraph([DependencyEdge(ART, "ku_a", edge)])


def _fp(unit_hash: str) -> str:
    return artifact_input_fingerprint(["ku_a"], {"ku_a": unit_hash})


# --- the six frozen states (PROTOCOL section 5) -----------------------------


def states() -> list[dict[str, Any]]:
    matching = {ART: _fp("h-same")}
    return [
        {
            "id": "S0",
            "intent": "all checks satisfiable; the only admissible state",
            "kwargs": dict(
                diff=_diff("two years", "three years"),
                graph=_graph(),
                plan=_plan(ArtifactState.CURRENT),
                rebuilt=[],
                current_input_fingerprints=dict(matching),
                expected_input_fingerprints=dict(matching),
                structural_coverage=[ART],
            ),
        },
        {
            "id": "S1",
            "intent": "a change names a unit absent from the dependency graph",
            "kwargs": dict(
                diff=_diff("two years", "three years", unit="ku_orphan"),
                graph=_graph(),
                plan=_plan(ArtifactState.CURRENT),
                rebuilt=[],
                current_input_fingerprints=dict(matching),
                expected_input_fingerprints=dict(matching),
                structural_coverage=[ART],
            ),
        },
        {
            "id": "S2",
            "intent": "an artifact marked for rebuild was not rebuilt",
            "kwargs": dict(
                diff=_diff("two years", "three years"),
                graph=_graph(),
                plan=_plan(ArtifactState.STALE),
                rebuilt=[],
                current_input_fingerprints=dict(matching),
                expected_input_fingerprints=dict(matching),
                structural_coverage=[ART],
            ),
        },
        {
            "id": "S3",
            "intent": (
                "consistent AND incomplete: rebuild missing, fingerprints all match"
            ),
            "note": "the audit named this as where an ordering effect would appear",
            "kwargs": dict(
                diff=_diff("two years", "three years"),
                graph=_graph(),
                plan=_plan(ArtifactState.STALE),
                rebuilt=[],
                current_input_fingerprints=dict(matching),
                expected_input_fingerprints=dict(matching),
                structural_coverage=[ART],
            ),
        },
        {
            "id": "S4",
            "intent": "carried-forward artifact whose input fingerprint disagrees",
            "kwargs": dict(
                diff=_diff("two years", "three years"),
                graph=_graph(),
                plan=_plan(ArtifactState.CURRENT),
                rebuilt=[],
                current_input_fingerprints={ART: _fp("h-after")},
                expected_input_fingerprints={ART: _fp("h-before")},
                structural_coverage=[ART],
            ),
        },
        {
            "id": "S5",
            "intent": "structural dependency without declared structural coverage",
            "kwargs": dict(
                diff=_diff("two years", "three years"),
                graph=_graph(EdgeType.DEPENDS_ON),
                plan=_plan(ArtifactState.CURRENT),
                rebuilt=[],
                current_input_fingerprints=dict(matching),
                expected_input_fingerprints=dict(matching),
                structural_coverage=[],
            ),
        },
    ]


# --- the four checks, as order-independent predicates ------------------------


def check_changes_accounted(k) -> tuple[bool, tuple[str, ...]]:
    diff, graph = k["diff"], k["graph"]
    seeds = list(diff.changed_logical_ids)
    for change in diff.unresolved:
        seeds.extend(change.candidates)
        if change.logical_id:
            seeds.append(change.logical_id)
    unknown = tuple(sorted(graph.impact_of(seeds).unknown_nodes)) if seeds else ()
    return (not unknown), unknown


def check_recompile_complete(k) -> tuple[bool, tuple[str, ...]]:
    planned = {
        t.artifact_id for t in k["plan"].targets if t.state is not ArtifactState.CURRENT
    }
    missing = tuple(sorted(planned - set(k["rebuilt"])))
    return (not missing), missing


def check_integrity(k) -> tuple[bool, tuple[str, ...]]:
    eq = k.get("equivalence")
    if eq is not None:
        return eq.equivalent, tuple(eq.diverged) + tuple(eq.stale_left_behind)
    if k.get("current_input_fingerprints") is not None:
        return True, ()
    return False, ()


def check_no_stale_current(k) -> tuple[bool, tuple[str, ...]]:
    plan, graph = k["plan"], k["graph"]
    cur = [t.artifact_id for t in plan.targets if t.state is ArtifactState.CURRENT]
    now_fp = k.get("current_input_fingerprints")
    was_fp = k.get("expected_input_fingerprints")
    stale: list[str] = []
    unver: list[str] = []
    if now_fp is not None and was_fp is not None:
        covered = set(k.get("structural_coverage") or ())
        for artifact in cur:
            now = now_fp.get(artifact)
            was = was_fp.get(artifact)
            if now is None or was is None:
                unver.append(artifact)
                continue
            if _declares_structural(graph, artifact) and artifact not in covered:
                unver.append(artifact)
                continue
            if now != was:
                stale.append(artifact)
    elif k.get("equivalence") is None:
        unver.extend(cur)
    if stale:
        return False, tuple(sorted(stale))
    if unver and k.get("equivalence") is None:
        return False, tuple(sorted(unver))
    return True, ()


CHECKS = {
    GateStep.CHANGES_ACCOUNTED: check_changes_accounted,
    GateStep.RECOMPILE_COMPLETE: check_recompile_complete,
    GateStep.INTEGRITY: check_integrity,
    GateStep.NO_STALE_CURRENT: check_no_stale_current,
}


# --- positive control (AMENDMENT 1) -----------------------------------------
# A deliberately order-dependent gate. This is NOT the system and is never
# evidence about it. It exists to answer one question: given a gate whose
# ordering genuinely IS load-bearing, does this harness detect it? Without that
# answer the null from the real check set is the H1-E non-separating arm again.


def control_checks() -> dict:
    """INTEGRITY passes if completeness has not run yet, fails once it has."""
    seen: list[str] = []

    def watched(step, fn):
        def run(k):
            seen.append(step.value)
            return fn(k)

        return run

    def order_dependent_integrity(k):
        if GateStep.RECOMPILE_COMPLETE.value in seen:
            return False, ("control:integrity-after-completeness",)
        return True, ()

    checks = {
        GateStep.CHANGES_ACCOUNTED: watched(
            GateStep.CHANGES_ACCOUNTED, check_changes_accounted
        ),
        GateStep.RECOMPILE_COMPLETE: watched(
            GateStep.RECOMPILE_COMPLETE, lambda k: (True, ())
        ),
        GateStep.INTEGRITY: watched(GateStep.INTEGRITY, order_dependent_integrity),
        GateStep.NO_STALE_CURRENT: watched(
            GateStep.NO_STALE_CURRENT, lambda k: (True, ())
        ),
    }
    return checks


def run_positive_control(state_kwargs) -> dict:
    divergences = []
    base = None
    for perm in itertools.permutations(CANONICAL):
        checks = control_checks()
        evaluated: list[str] = []
        promotable = True
        cause = None
        for step in perm:
            ok, _ = checks[step](state_kwargs)
            evaluated.append(step.value)
            if not ok:
                promotable = False
                cause = step.value
                break
        if base is None:
            base = promotable
        elif promotable != base:
            divergences.append(
                {
                    "order": [s.value for s in perm],
                    "promotable": promotable,
                    "cause": cause,
                }
            )
    return {
        "separates": bool(divergences),
        "divergence_count": len(divergences),
        "examples": divergences[:3],
    }


def run_ordered(k, order) -> dict[str, Any]:
    """Short-circuit exactly like the real gate: stop at the first failure."""
    evaluated: list[str] = []
    for step in order:
        ok, offending = CHECKS[step](k)
        evaluated.append(step.value)
        if not ok:
            return {
                "promotable": False,
                "first_failing_step": step.value,
                "offending": list(offending),
                "steps_evaluated": evaluated,
                "steps_not_reached": [
                    s.value for s in order if s.value not in evaluated
                ],
            }
    return {
        "promotable": True,
        "first_failing_step": None,
        "offending": [],
        "steps_evaluated": evaluated,
        "steps_not_reached": [],
    }


def real_gate(k) -> dict[str, Any]:
    report = evaluate_promotion_gate(**k)
    failing = [s for s in report.steps if s.outcome is GateOutcome.FAIL]
    return {
        "promotable": report.promotable,
        "first_failing_step": failing[0].step.value if failing else None,
    }


def check_fidelity(all_states) -> dict[str, Any]:
    rows = []
    for state in all_states:
        real = real_gate(state["kwargs"])
        harness = run_ordered(state["kwargs"], CANONICAL)
        agrees = (
            real["promotable"] == harness["promotable"]
            and real["first_failing_step"] == harness["first_failing_step"]
        )
        rows.append(
            {
                "state": state["id"],
                "real_gate": real,
                "harness_canonical": {
                    "promotable": harness["promotable"],
                    "first_failing_step": harness["first_failing_step"],
                },
                "agrees": agrees,
            }
        )
    return {"rows": rows, "all_agree": all(r["agrees"] for r in rows)}


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    exp = Path(__file__).resolve().parents[1]
    out = exp / "receipts" / "gate-ordering-permutation-2026-08-19.json"
    all_states = states()

    fidelity = check_fidelity(all_states)

    receipt: dict[str, Any] = {
        "schema": "tavonel.gate-ordering-ablation.v1",
        "experiment": "H1-I-GATE-ORDERING-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": sha256_file(exp / "PROTOCOL_2026-08-19.md"),
        "promotion_gate_module_sha256": sha256_file(
            ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "promotion_gate.py"
        ),
        "fidelity_gate": fidelity,
        "supersedes": {
            "receipt": "receipts/gate-ordering-attempt1-void-2026-08-19.json",
            "why": (
                "Attempt 1 was voided by this same fidelity gate: the harness "
                "paraphrased _declares_structural against the wrong channel API "
                "and admitted S5, which the real gate refuses. The protocol was "
                "not amended; the harness now imports the system helper."
            ),
        },
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }

    out.parent.mkdir(parents=True, exist_ok=True)

    if not fidelity["all_agree"]:
        receipt["result"] = "VOID_FIDELITY_GATE_FAILED"
        receipt["ordering_result_reported"] = False
        receipt["why"] = (
            "The harness did not reproduce the real gate in the canonical order. "
            "Per protocol section 6 the run is void and reports no ordering result."
        )
        receipt["receipt_sha256"] = canonical_sha256(receipt)
        out.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print("VOID: fidelity gate failed")
        for row in fidelity["rows"]:
            if not row["agrees"]:
                print("  ", row)
        print(f"wrote {out}")
        return 1

    perms = list(itertools.permutations(CANONICAL))
    evaluations = []
    verdict_divergences = []
    cause_divergences = []
    soundness_events = []

    for state in all_states:
        base = run_ordered(state["kwargs"], CANONICAL)
        rebuild_incomplete = not check_recompile_complete(state["kwargs"])[0]
        for perm in perms:
            got = run_ordered(state["kwargs"], perm)
            names = [s.value for s in perm]
            evaluations.append(
                {
                    "state": state["id"],
                    "order": names,
                    "promotable": got["promotable"],
                    "first_failing_step": got["first_failing_step"],
                }
            )
            if got["promotable"] != base["promotable"]:
                verdict_divergences.append(
                    {
                        "state": state["id"],
                        "order": names,
                        "canonical_promotable": base["promotable"],
                        "permuted_promotable": got["promotable"],
                    }
                )
            if got["first_failing_step"] != base["first_failing_step"]:
                cause_divergences.append(
                    {
                        "state": state["id"],
                        "order": names,
                        "canonical_cause": base["first_failing_step"],
                        "permuted_cause": got["first_failing_step"],
                    }
                )
            # E2(b): integrity judged against a rebuild that the completeness
            # check would have rejected, because it was never reached.
            evaluated = got["steps_evaluated"]
            if (
                rebuild_incomplete
                and GateStep.INTEGRITY.value in evaluated
                and GateStep.RECOMPILE_COMPLETE.value not in evaluated
            ):
                soundness_events.append(
                    {
                        "state": state["id"],
                        "order": names,
                        "what": (
                            "integrity was evaluated on a state whose rebuild is "
                            "incomplete; the completeness check was never reached"
                        ),
                    }
                )

    control = run_positive_control(all_states[0]["kwargs"])
    e1_null = not verdict_divergences
    receipt.update(
        {
            "result": (
                "ORDERING_NOT_LOAD_BEARING_FOR_VERDICT"
                if e1_null
                else "ORDERING_LOAD_BEARING_FOR_VERDICT"
            ),
            "ordering_result_reported": True,
            "states_evaluated": len(all_states),
            "permutations_per_state": len(perms),
            "total_evaluations": len(evaluations),
            "E1_verdict_divergences": verdict_divergences,
            "E1_verdict_divergence_count": len(verdict_divergences),
            "E1_null": e1_null,
            "E2_cause_divergences": cause_divergences,
            "E2_cause_divergence_count": len(cause_divergences),
            "E2_unsound_evaluation_events": soundness_events,
            "E2_unsound_evaluation_count": len(soundness_events),
            "evaluations": evaluations,
            "positive_control": control,
            "instrument_separates": control["separates"],
            "null_is_citable": control["separates"],
            "amendment_1": (
                "The permutation arm cannot return a divergence unless the four "
                "checks are order-dependent. The positive control establishes "
                "whether this harness can detect an ordering effect at all. If it "
                "does not separate, the null is uncitable and the ordering "
                "question stays unmeasured. See AMENDMENT_1_2026-08-19.md."
            ),
            "supersedes_attempt2": "receipts/gate-ordering-attempt2-nonseparating-2026-08-19.json",
            "narrowing_rule_triggered": e1_null and control["separates"],
            "narrowing_rule": (
                "PROTOCOL section 4: E1 null means claim B1 element 7's recitation "
                "of order is NOT supported as affecting the admitted/refused "
                "outcome and the claim must be narrowed. Defending the ordering "
                "limitation on the strength of this null is prohibited."
            ),
        }
    )
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"fidelity gate: {'PASS' if fidelity['all_agree'] else 'FAIL'}")
    print(f"result: {receipt['result']}")
    print(f"evaluations: {len(evaluations)}")
    print(f"E1 verdict divergences: {len(verdict_divergences)}")
    print(f"E2 cause divergences:   {len(cause_divergences)}")
    print(f"E2 unsound evaluations: {len(soundness_events)}")
    print(f"positive control separates: {control['separates']} "
          f"({control['divergence_count']} divergent orders)")
    print(f"null is citable: {control['separates']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
