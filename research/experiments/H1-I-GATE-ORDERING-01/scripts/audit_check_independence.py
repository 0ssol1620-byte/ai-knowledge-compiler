#!/usr/bin/env python3
"""H1-I Amendment 2 -- static audit: are the four gate checks *independent*?

Why this exists. The permutation run measured one thing:

    the conjunctive acceptance result is invariant to evaluation order.

The claim wording that followed it said something stronger -- "mutually
independent checks, each evaluated against the candidate state rather than
another check's output". Order-invariance does not entail independence. A
conjunction of coupled predicates can still be commutative. Registering the
stronger wording on the strength of the weaker result is exactly the overclaim
this programme is organised against, so the wording is audited against the
implementation here rather than inferred from the experiment.

Four questions, each answered from code:

  Q1  does any check consume another check's output as input?
  Q2  does an earlier check mutate candidate/world state a later check reads?
  Q3  is there indirect coupling via shared cache, mutable accumulator,
      exception state or other side effect?
  Q4  does short-circuiting affect only evaluation count and reported refusal
      reason, leaving boolean acceptance semantics untouched?

The mechanical checks below are what a reader can re-run. The read/write sets
are transcribed from the source with line citations so they can be checked by
eye against the same file; they are not inferred by the script, and the receipt
says so rather than dressing a manual reading up as static analysis.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
GATE = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "promotion_gate.py"
DEPS = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "dependency.py"

sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.promotion_gate import (  # noqa: E402
    GateOutcome,
    GateStep,
    PromotionGateReport,
    StepResult,
)

#: Methods that would mutate an input the gate is handed. If the gate never
#: calls one, no check can have altered what a later check reads.
MUTATORS = {"add", "append", "extend", "update", "setdefault", "pop", "clear",
            "remove", "insert", "discard", "__setitem__", "sort"}

#: Names the gate is allowed to mutate: its own local accumulators. Anything
#: else appearing as a mutation target is a finding, not a detail.
LOCAL_ACCUMULATORS = {"steps", "unverifiable", "stale_current", "unver",
                      "seeds", "found", "not_built", "planned", "current",
                      "rebuilt_set", "checked", "evaluated", "cycles",
                      "affected", "visited", "queue"}


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def gate_function(tree: ast.Module) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate_promotion_gate":
            return node
    raise SystemExit("evaluate_promotion_gate not found")


def q_module_level_mutable_state(tree: ast.Module) -> dict[str, Any]:
    """A module-level mutable object would be a channel between invocations."""
    offenders = []
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign):
            value = node.value
            if isinstance(value, ast.List | ast.Dict | ast.Set):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    # `__all__` is a module-level list and is not a coupling
                    # channel; attempt 1 flagged it and had to be corrected.
                    # Dunder names are export/metadata declarations, not state.
                    if isinstance(t, ast.Name) and not t.id.startswith("__"):
                        offenders.append({"name": t.id, "line": node.lineno})
    return {
        "question": "module-level mutable state in the gate module",
        "offenders": offenders,
        "clean": not offenders,
    }


def q_input_mutation(fn: ast.FunctionDef) -> dict[str, Any]:
    """Any call to a mutating method on something that is not a local accumulator."""
    findings = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in MUTATORS:
            continue
        target = func.value
        name = target.id if isinstance(target, ast.Name) else ast.unparse(target)
        if name not in LOCAL_ACCUMULATORS:
            findings.append({"target": name, "method": func.attr, "line": node.lineno})
    return {
        "question": "does the gate mutate any object it was handed?",
        "non_local_mutations": findings,
        "clean": not findings,
    }


def q_conjunction_is_the_verdict() -> dict[str, Any]:
    """`promotable` must be a conjunction over step outcomes, nothing else."""
    # Behavioural, not textual: a report with any non-PASS step is not promotable,
    # and NOT_REACHED must not count as a pass.
    all_pass = PromotionGateReport(
        steps=tuple(
            StepResult(s, GateOutcome.PASS)
            for s in (
                GateStep.CHANGES_ACCOUNTED,
                GateStep.RECOMPILE_COMPLETE,
                GateStep.INTEGRITY,
                GateStep.NO_STALE_CURRENT,
                GateStep.PROMOTABLE,
            )
        )
    )
    with_not_reached = PromotionGateReport(
        steps=(
            StepResult(GateStep.CHANGES_ACCOUNTED, GateOutcome.FAIL),
            StepResult(GateStep.RECOMPILE_COMPLETE, GateOutcome.NOT_REACHED),
            StepResult(GateStep.INTEGRITY, GateOutcome.NOT_REACHED),
            StepResult(GateStep.NO_STALE_CURRENT, GateOutcome.NOT_REACHED),
            StepResult(GateStep.PROMOTABLE, GateOutcome.NOT_REACHED),
        )
    )
    all_not_reached = PromotionGateReport(
        steps=tuple(
            StepResult(s, GateOutcome.NOT_REACHED)
            for s in (GateStep.CHANGES_ACCOUNTED, GateStep.PROMOTABLE)
        )
    )
    return {
        "question": (
            "is acceptance the conjunction of step outcomes, and can a "
            "short-circuited (NOT_REACHED) report ever be promotable?"
        ),
        "all_pass_is_promotable": all_pass.promotable,
        "short_circuited_report_is_promotable": with_not_reached.promotable,
        "all_not_reached_is_promotable": all_not_reached.promotable,
        "not_reached_counts_as_pass": all_not_reached.promotable,
        "clean": (
            all_pass.promotable
            and not with_not_reached.promotable
            and not all_not_reached.promotable
        ),
        "note": (
            "NOT_REACHED is a distinct outcome from PASS precisely so a "
            "short-circuited run cannot be read as a verified one. This is what "
            "makes short-circuiting safe for the verdict: skipping a check can "
            "only withhold a PASS, never supply one."
        ),
    }


# --- transcribed read/write sets (manual, cited, checkable by eye) -----------

READ_WRITE_SETS = {
    "1_changes_accounted": {
        "source_lines": "219-244",
        "reads": ["diff.changed_logical_ids", "diff.unresolved", "graph.impact_of"],
        "writes": ["steps"],
        "reads_another_checks_output": False,
    },
    "2_recompile_complete": {
        "source_lines": "275-294",
        "reads": ["plan.targets", "rebuilt_set"],
        "writes": ["steps"],
        "reads_another_checks_output": False,
    },
    "3_integrity": {
        "source_lines": "296-341",
        "reads": ["equivalence", "current_input_fingerprints"],
        "writes": ["steps"],
        "reads_another_checks_output": False,
    },
    "4_no_stale_current": {
        "source_lines": "343-401",
        "reads": [
            "plan.targets", "current_input_fingerprints",
            "expected_input_fingerprints", "graph (via _declares_structural)",
            "structural_coverage", "equivalence",
        ],
        "writes": ["stale_current", "unverifiable", "checked", "steps"],
        "reads_another_checks_output": False,
    },
}

#: The finding that decides the claim wording.
DELEGATION_FINDING = {
    "where": "promotion_gate.py:317-330, the INTEGRITY no-oracle branch",
    "what": (
        "When no full-rebuild oracle is supplied, check 3 records PASS with the "
        "detail 'no full-rebuild oracle; integrity rests on the input "
        "fingerprints checked in the next step'. The source comment states "
        "outright that check 4 'may not be skipped' for this reason."
    ),
    "why_it_matters": (
        "No value flows from check 4 to check 3 -- they are independent as "
        "data. But check 3's PASS is not self-supporting in that branch: its "
        "safety argument is discharged by check 4. Two predicates can be "
        "order-invariant in their conjunction while one's guarantee depends on "
        "the other being evaluated at all. 'Mutually independent' asserts the "
        "second property, and the permutation experiment measured only the "
        "first."
    ),
    "consequence": (
        "The claim wording is narrowed to what is actually established: a "
        "sequence of candidate-state predicates whose conjunctive acceptance "
        "result is invariant to evaluation order."
    ),
}


def main() -> int:
    exp = Path(__file__).resolve().parents[1]
    out = exp / "receipts" / "check-independence-static-audit-2026-08-19.json"

    tree = ast.parse(GATE.read_text(encoding="utf-8"))
    fn = gate_function(tree)

    q1 = {
        "question": "does any check consume another check's output as input?",
        "method": "manual read/write transcription with line citations, below",
        "answer": "no -- no check reads `steps` or any value another check produced",
        "caveat_see": "delegation_finding",
        "clean": True,
    }
    q2 = q_input_mutation(fn)
    q3_module = q_module_level_mutable_state(tree)
    q3_accum = {
        "question": "coupling via the function's own mutable accumulators?",
        "accumulators": {
            "steps": "append-only report log; read once, as `steps[-1].outcome`, "
                     "for control flow only (line 273) -- never as check input",
            "unverifiable": "written only by check 4; read only by check 4 and "
                            "the report constructor",
            "checked": "written only by check 4; report field only",
        },
        "clean": True,
    }
    q3_graph = {
        "question": "shared cache or memoisation inside graph.impact_of?",
        "finding": (
            "DependencyGraph.impact_of builds only local structures (seeds, "
            "visited, affected, cycles, queue). The sole mutator on the class is "
            "`add` (dependency.py:206-211), which the gate never calls. No "
            "memoisation, so no cross-check channel."
        ),
        "dependency_module_sha256": sha256_file(DEPS),
        "clean": True,
    }
    q3_exceptions = {
        "question": "coupling via exception state?",
        "finding": (
            "The gate raises nothing and catches nothing; refusal is expressed "
            "as a returned StepResult. There is no exception channel between "
            "checks."
        ),
        "clean": True,
    }
    q4 = q_conjunction_is_the_verdict()

    verdict_supported = all(
        q["clean"] for q in (q1, q2, q3_module, q3_accum, q3_graph, q3_exceptions, q4)
    )

    receipt: dict[str, Any] = {
        "schema": "tavonel.gate-check-independence-static-audit.v1",
        "experiment": "H1-I-GATE-ORDERING-01",
        "amendment": "AMENDMENT_2_2026-08-19.md",
        "generated_at": datetime.now(UTC).isoformat(),
        "promotion_gate_module_sha256": sha256_file(GATE),
        "purpose": (
            "Decide whether the static evidence supports the word 'independent' "
            "in the claim, given that the permutation experiment established "
            "only order-invariance of the conjunction."
        ),
        "Q1_reads_another_checks_output": q1,
        "Q2_mutates_inputs": q2,
        "Q3a_module_level_mutable_state": q3_module,
        "supersedes": {
            "receipt": "receipts/check-independence-attempt1-falsepositive-2026-08-19.json",
            "why": (
                "Attempt 1's module-state check flagged `__all__`, an export "
                "declaration rather than a coupling channel. Corrected to skip "
                "dunder names. The finding that decides the wording -- the "
                "check-3 delegation -- is identical in both runs and was not "
                "affected by this false positive."
            ),
        },
        "Q3b_local_accumulators": q3_accum,
        "Q3c_shared_cache_in_graph": q3_graph,
        "Q3d_exception_state": q3_exceptions,
        "Q4_short_circuit_semantics": q4,
        "read_write_sets": READ_WRITE_SETS,
        "delegation_finding": DELEGATION_FINDING,
        "mechanical_vs_manual": (
            "Q2, Q3a and Q4 are executed checks. Q1, Q3b, Q3c and Q3d are "
            "manual readings with line citations, recorded as such. Presenting a "
            "manual reading as static analysis would be the same category error "
            "this audit exists to correct."
        ),
        "result": (
            "ORDER_INVARIANCE_SUPPORTED_INDEPENDENCE_NOT_SUPPORTED"
            if verdict_supported
            else "STATIC_AUDIT_FOUND_ADDITIONAL_COUPLING"
        ),
        "supports_wording_mutually_independent": False,
        "supports_wording_order_invariant_conjunction": verdict_supported,
        "adopted_wording": (
            "a sequence of candidate-state predicates whose conjunctive "
            "acceptance result is invariant to evaluation order"
        ),
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"result: {receipt['result']}")
    print(f"  Q2 mutates inputs:            {'clean' if q2['clean'] else q2}")
    print(f"  Q3a module mutable state:     {'clean' if q3_module['clean'] else q3_module}")
    print(f"  Q4 short-circuit safe:        {q4['clean']}")
    print(f"     NOT_REACHED counts as pass: {q4['not_reached_counts_as_pass']}")
    print(f"  supports 'mutually independent': {receipt['supports_wording_mutually_independent']}")
    invariant = receipt["supports_wording_order_invariant_conjunction"]
    print(f"  supports order-invariance:       {invariant}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
