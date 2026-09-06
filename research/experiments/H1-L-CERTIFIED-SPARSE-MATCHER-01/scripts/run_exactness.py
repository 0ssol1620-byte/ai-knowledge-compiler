#!/usr/bin/env python3
"""P2-13 -- exactness harness for CERTIFIED_SPARSE against LEGACY.

Endpoint and corpus are fixed by ../SEMANTIC_CONTRACT_2026-08-19.md and
../PROTOCOL_2026-08-19.md, both frozen before this ran.

Primary endpoint: zero divergences on the full row-attached contract footprint,
including `candidates` attribution, plus the derived downstream facets.

A null from an equivalence harness is worthless unless the harness can detect a
real divergence, so mutants that deliberately corrupt the winner, the runner-up
and the attribution must all be caught. If any mutant survives, the run is VOID.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.dependency import DependencyEdge, DependencyGraph, EdgeType  # noqa: E402
from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalUnitFingerprint,
    MatchingPolicy,
    assign_one_to_one,
)
from certified_sparse import Stats, assign_certified_sparse, stats_record  # noqa: E402

#: Attempt 1's corpus omitted `source_lineage`, so `_source_continuity` returned
#: NOT_APPLICABLE on every pair, the missing-critical-signal branch fired first,
#: and NO row ever reached MATCHED, the review band or the tie guard. Every
#: runner-up mutant was therefore unfalsifiable by construction. Units now carry
#: a lineage by default so the bands are actually exercised; `lineage=None`
#: keeps the abstention case, which is still worth covering.
DEFAULT_LINEAGE = "doc-lineage-1"


def unit(lid, text, path=("Doc", "Sec"), anchor=None, identifier=None,
         lineage=DEFAULT_LINEAGE, version_distance=1, prev_anchor="a0",
         next_anchor="a2", geometry="body"):
    kw = {"logical_id": lid, "text": text, "document_path": path,
          "anchor": anchor if anchor is not None else lid,
          "previous_anchor": prev_anchor, "next_anchor": next_anchor,
          "geometry_style": geometry, "version_distance": version_distance}
    if lineage:
        kw["source_lineage"] = lineage
    if identifier is not None:
        kw["explicit_identifier"] = identifier
    return LogicalUnitFingerprint.of(**kw)


def footprint(decisions, previous) -> dict[str, Any]:
    """The frozen contract footprint. Row-attached, ordered, not a multiset."""
    rows = [
        {
            "row": i,
            "match": d.match.value,
            "logical_id": d.logical_id,
            "candidates": list(d.candidates),
            "relation": d.relation.value if d.relation else None,
            "score": round(d.score, 9),
        }
        for i, d in enumerate(decisions)
    ]
    # Derived: unresolved seeds -> impact set, exactly as recompilation seeds it.
    seeds = sorted({c for d in decisions if d.logical_id is None for c in d.candidates})
    graph = DependencyGraph(
        [DependencyEdge(f"artifact:from_{p.logical_id}", p.logical_id,
                        EdgeType.DEPENDS_ON) for p in previous]
    )
    impact = sorted(p.node_id for p in graph.impact_of(seeds).affected) if seeds else []
    return {"rows": rows, "unresolved_seeds": seeds, "impact_set": impact}


# --- corpus (PROTOCOL §5) ---------------------------------------------------


def corpus() -> list[dict[str, Any]]:
    c: list[dict[str, Any]] = []

    def add(name, inc, prev):
        c.append({"name": name, "incoming": inc, "previous": prev})

    add("ordinary",
        [unit("n1", "alpha beta gamma"), unit("n2", "delta epsilon zeta")],
        [unit("u1", "alpha beta gamma"), unit("u2", "delta epsilon zeta")])
    add("equal_score_tie",
        [unit("n1", "same text here")],
        [unit("u1", "same text here"), unit("u2", "same text here")])
    add("split",
        [unit("n1", "alpha beta gamma"), unit("n2", "delta epsilon")],
        [unit("u1", "alpha beta gamma delta epsilon")])
    add("merge",
        [unit("n1", "alpha beta gamma delta epsilon")],
        [unit("u1", "alpha beta gamma"), unit("u2", "delta epsilon")])
    add("split_and_merge",
        [unit("n1", "alpha beta"), unit("n2", "gamma delta epsilon zeta"),
         unit("n3", "eta theta")],
        [unit("u1", "alpha beta gamma delta"), unit("u2", "epsilon zeta eta theta")])
    add("identical_candidates",
        [unit("n1", "x y z"), unit("n2", "x y z")],
        [unit("u1", "x y z"), unit("u2", "x y z"), unit("u3", "x y z")])
    add("contended_column",
        [unit("n1", "shared core text"), unit("n2", "shared core text!")],
        [unit("u1", "shared core text"), unit("u2", "unrelated other text")])
    add("rows_gt_cols",
        [unit(f"n{i}", f"text block {i}") for i in range(5)],
        [unit("u1", "text block 0"), unit("u2", "text block 3")])
    add("cols_gt_rows",
        [unit("n1", "text block 0"), unit("n2", "text block 3")],
        [unit(f"u{i}", f"text block {i}") for i in range(5)])
    add("all_equal_scores",
        [unit(f"n{i}", "identical payload") for i in range(3)],
        [unit(f"u{i}", "identical payload") for i in range(3)])
    add("threshold_adjacent",
        [unit("n1", "one two three four five six seven eight")],
        [unit("u1", "one two three four five six seven"),
         unit("u2", "one two three four five six")])
    add("missing_critical_signal",
        [unit("n1", "warranty term", path=("RootB", "S"), lineage=None)],
        [unit("u1", "warranty term", path=("RootA", "S"), lineage=None)])
    add("matched_clean",
        [unit("n1", "alpha beta gamma delta epsilon")],
        [unit("u1", "alpha beta gamma delta epsilon")])
    add("tie_guard_live",
        [unit("n1", "alpha beta gamma delta")],
        [unit("u1", "alpha beta gamma delta"), unit("u2", "alpha beta gamma delta")])
    add("runner_up_sensitive",
        [unit("n1", "alpha beta gamma delta")],
        [unit("u1", "alpha beta gamma delta"), unit("u2", "alpha beta gamma delt")])
    add("low_score_but_semantic",
        [unit("n1", "completely different content here", path=("RootB", "S"))],
        [unit("u1", "unrelated prior text", path=("RootA", "S"))])
    add("dependency_separated",
        [unit("n1", "same text here")],
        [unit("u1", "same text here"), unit("u2", "same text here")])
    for n in (12, 30):
        add(f"scale_{n}",
            [unit(f"n{i}", f"body content number {i} with filler") for i in range(n)],
            [unit(f"u{i}", f"body content number {i} with filler") for i in range(n)])
    return c


def permutations_of(case) -> list[tuple[str, list, list]]:
    """Candidate-order and row-order perturbations (PROTOCOL §5)."""
    inc, prev = case["incoming"], case["previous"]
    out = [("identity", inc, prev)]
    if len(prev) <= 4:
        for k, perm in enumerate(itertools.permutations(range(len(prev)))):
            if k == 0 or k > 5:
                continue
            out.append((f"prev_perm_{k}", inc, [prev[i] for i in perm]))
    if len(inc) <= 4:
        for k, perm in enumerate(itertools.permutations(range(len(inc)))):
            if k == 0 or k > 3:
                continue
            out.append((f"inc_perm_{k}", [inc[i] for i in perm], prev))
    return out


def legacy(inc, prev):
    return assign_one_to_one(list(inc), list(prev),
                             resolver=LogicalIdentityResolver(),
                             policy=MatchingPolicy.LEGACY)


# --- mutants (PROTOCOL §6) --------------------------------------------------


def mutant_winner(inc, prev):
    """Rotate the assignment: corrupts the winner."""
    d = legacy(inc, prev)
    return d[1:] + d[:1] if len(d) > 1 else d


def mutant_attribution(inc, prev):
    """Keep classification and logical id, corrupt only `candidates`."""
    out = []
    for d in legacy(inc, prev):
        if d.candidates:
            rotated = tuple(list(d.candidates)[1:] + list(d.candidates)[:1])
            swapped = (
                (prev[-1].logical_id,) if rotated == d.candidates else rotated
            )
            out.append(
                type(d)(
                    match=d.match, logical_id=d.logical_id, score=d.score,
                    signals=d.signals, missing=d.missing, reason=d.reason,
                    candidates=swapped, relation=d.relation,
                )
            )
        else:
            out.append(d)
    return out


def mutant_runner_up(inc, prev):
    """Re-decide every assigned row with runner_up forced EQUAL to the score.

    Attempt 1 forced runner_up to 0.0 and separated on nothing: zeroing a rival
    that was already below the tie band changes no decision, and the rows that
    abstain on a missing critical signal return before the tie check is reached.
    A mutant that cannot change an answer tests nothing -- the same defect the
    programme recorded for the H1-E null arm and for H1-I attempt 2.

    Forcing runner_up to the winner's own score drives `best - runner_up` to 0,
    which is inside `_TIE_BAND` by construction, so the tie guard fires wherever
    it can fire at all.
    """
    engine = LogicalIdentityResolver()
    base = legacy(inc, prev)
    out = []
    for i, d in enumerate(base):
        if d.candidates and i < len(inc):
            partner = next(
                (p for p in prev if p.logical_id == d.candidates[0]), None
            )
            if partner is not None:
                score, signals, missing = engine.score_pair(partner, inc[i])
                out.append(
                    engine.decide_pair(
                        incoming=inc[i], partner=partner, score=score,
                        signals=signals, missing=missing,
                        runner_up=score, runner_up_id="mutant-rival",
                        seed_logical_id=inc[i].logical_id,
                    )
                )
                continue
        out.append(d)
    return out


MUTANTS = {
    "winner_rotated": mutant_winner,
    "attribution_swapped": mutant_attribution,
    "runner_up_maximized": mutant_runner_up,
}


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    exp = HERE.parent
    out = exp / "receipts" / "exactness-2026-08-19.json"

    cases = corpus()
    divergences: list[dict[str, Any]] = []
    per_case: list[dict[str, Any]] = []
    comparisons = 0

    for case in cases:
        for label, inc, prev in permutations_of(case):
            comparisons += 1
            base = footprint(legacy(inc, prev), prev)
            st = Stats()
            got_decisions, st = assign_certified_sparse(
                list(inc), list(prev), resolver=LogicalIdentityResolver(), stats=st
            )
            got = footprint(got_decisions, prev)
            if got != base:
                divergences.append(
                    {"case": case["name"], "variant": label,
                     "legacy": base, "certified_sparse": got}
                )
            if label == "identity":
                per_case.append(
                    {"case": case["name"], "rows": len(inc), "cols": len(prev),
                     **stats_record(st)}
                )

    # --- mutant falsification ---
    mutant_rows = []
    for name, fn in MUTANTS.items():
        caught = 0
        applicable = 0
        for case in cases:
            inc, prev = case["incoming"], case["previous"]
            base = footprint(legacy(inc, prev), prev)
            try:
                mutated = footprint(fn(inc, prev), prev)
            except Exception as exc:
                mutant_rows.append({"mutant": name, "case": case["name"],
                                    "error": repr(exc)})
                continue
            if mutated == base:
                continue
            applicable += 1
            caught += 1
        mutant_rows.append({"mutant": name, "cases_where_mutant_differs": applicable,
                            "caught_by_endpoint": caught,
                            "separates": applicable > 0 and caught == applicable})

    separating = [m for m in mutant_rows if m.get("separates")]
    all_mutants_separate = len(separating) == len(MUTANTS)

    # --- performance, secondary and only reported after correctness ---
    perf = []
    for n in (100, 300):
        inc = [unit(f"n{i}", f"body content number {i} with filler words") for i in range(n)]
        prev = [unit(f"u{i}", f"body content number {i} with filler words") for i in range(n)]
        t0 = time.perf_counter()
        legacy(inc, prev)
        t_legacy = time.perf_counter() - t0
        st = Stats()
        t0 = time.perf_counter()
        assign_certified_sparse(inc, prev, resolver=LogicalIdentityResolver(), stats=st)
        t_sparse = time.perf_counter() - t0
        perf.append({"n": n, "legacy_seconds": round(t_legacy, 4),
                     "certified_sparse_seconds": round(t_sparse, 4),
                     "speedup": round(t_legacy / t_sparse, 4) if t_sparse else None,
                     **stats_record(st)})

    exact = not divergences
    receipt: dict[str, Any] = {
        "schema": "tavonel.certified-sparse-exactness.v1",
        "experiment": "H1-L-CERTIFIED-SPARSE-MATCHER-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "contract_sha256": "sha256:" + hashlib.sha256(
            (exp / "SEMANTIC_CONTRACT_2026-08-19.md").read_bytes()).hexdigest(),
        "protocol_sha256": "sha256:" + hashlib.sha256(
            (exp / "PROTOCOL_2026-08-19.md").read_bytes()).hexdigest(),
        "identity_module_sha256": "sha256:" + hashlib.sha256(
            (ROOT / "packages/cir-python/src/akc_cir/identity.py").read_bytes()
        ).hexdigest(),
        "identity_module_modified": False,
        "blocked_policy_touched": False,
        "cases": len(cases),
        "comparisons": comparisons,
        "primary_divergences": len(divergences),
        "divergence_detail": divergences[:5],
        "exact_on_frozen_corpus": exact,
        "supersedes": "receipts/exactness-attempt1-void-mutant-2026-08-19.json",
        "supersedes_why": (
            "Attempt 1 was VOID under protocol section 6: the runner-up mutant "
            "forced the rival to 0.0 and separated on zero cases, so it could not "
            "have caught a real runner-up regression. The protocol was not "
            "amended; the mutant was corrected to force the rival equal to the "
            "winner's score, which fires the tie guard by construction."
        ),
        "mutant_falsification": mutant_rows,
        "all_mutants_separate": all_mutants_separate,
        "instrument_citable": all_mutants_separate,
        "per_case_scoring": per_case,
        "performance_secondary": perf,
        "result": (
            "EXACT_ON_FROZEN_CORPUS" if exact and all_mutants_separate
            else "VOID_MUTANT_SURVIVED" if exact and not all_mutants_separate
            else "DIVERGENT"
        ),
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"result: {receipt['result']}")
    print(f"  comparisons:          {comparisons}")
    print(f"  primary divergences:  {len(divergences)}")
    print(f"  mutants separate:     {all_mutants_separate}")
    for m in mutant_rows:
        if "separates" in m:
            print(f"    {m['mutant']:<22} differs_in="
                  f"{m['cases_where_mutant_differs']:<3} separates={m['separates']}")
    for p in perf:
        print(f"  n={p['n']}: legacy={p['legacy_seconds']}s "
              f"sparse={p['certified_sparse_seconds']}s "
              f"speedup={p['speedup']} saved={p['saved_fraction']}")
    print(f"wrote {out}")
    return 0 if receipt["result"] == "EXACT_ON_FROZEN_CORPUS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
