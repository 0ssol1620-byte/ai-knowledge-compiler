#!/usr/bin/env python3
"""H1-K -- extract LEGACY's observable matching semantics, by probing not asserting.

P2-13 asks for a sparse matcher that preserves LEGACY's semantics *exactly*.
Before any such matcher can be designed, "LEGACY's semantics" has to be a
specification rather than a description of one implementation. This file
establishes which candidate invariants LEGACY actually satisfies.

The distinction that motivates it, from reading `assign_one_to_one`:

  * the tie guard compares against a runner-up drawn from the **globally
    available** columns -- `taken` is computed over the whole assignment, so
    whether a column counts as a rival for row i depends on what every other row
    took; and
  * `_max_weight_matching` has **no explicit tie-break** among equal-weight
    optimal assignments. Which optimum it returns falls out of the Hungarian
    iteration order and of the zero-padding to `max(rows, cols)`.

If LEGACY is not itself invariant under candidate reordering, then "preserve
LEGACY exactly" does not mean "preserve a semantics" -- it means "reproduce this
implementation bit for bit", which is a materially harder and more fragile
requirement, and P2-13's framing has to change to say so.

Nothing here is a new matcher. This probes the existing one.
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
IDENT = ROOT / "packages" / "cir-python" / "src" / "akc_cir" / "identity.py"
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalUnitFingerprint,
    MatchingPolicy,
    assign_one_to_one,
)


def unit(
    lid: str,
    text: str,
    path: tuple[str, ...] = ("Doc", "Sec"),
    anchor: str = "",
    identifier: str | None = None,
) -> LogicalUnitFingerprint:
    return LogicalUnitFingerprint.of(
        logical_id=lid,
        text=text,
        document_path=path,
        anchor=anchor or lid,
        explicit_identifier=identifier,
    )


def outcome(decisions) -> list[dict[str, Any]]:
    """Row-attached outcome. Position matters: this is not a multiset."""
    return [
        {
            "row": i,
            "match": d.match.value,
            "logical_id": d.logical_id,
            "score": round(d.score, 6),
            "candidates": list(d.candidates),
            "relation": d.relation.value if d.relation else None,
        }
        for i, d in enumerate(decisions)
    ]


def run(incoming, previous, policy=MatchingPolicy.LEGACY):
    return assign_one_to_one(
        list(incoming), list(previous),
        resolver=LogicalIdentityResolver(), policy=policy,
    )


# --- probe cases ------------------------------------------------------------


def case_ordinary():
    prev = [unit("u1", "alpha beta gamma"), unit("u2", "delta epsilon zeta")]
    inc = [unit("n1", "alpha beta gamma"), unit("n2", "delta epsilon zeta")]
    return "ordinary_one_to_one", inc, prev


def case_equal_score_tie():
    """Two previous units identical in every signal but their logical_id."""
    prev = [unit("u1", "same text here"), unit("u2", "same text here")]
    inc = [unit("n1", "same text here")]
    return "equal_score_tie", inc, prev


def case_split():
    prev = [unit("u1", "alpha beta gamma delta epsilon")]
    inc = [unit("n1", "alpha beta gamma"), unit("n2", "delta epsilon")]
    return "split", inc, prev


def case_merge():
    prev = [unit("u1", "alpha beta gamma"), unit("u2", "delta epsilon")]
    inc = [unit("n1", "alpha beta gamma delta epsilon")]
    return "merge", inc, prev


def case_split_and_merge():
    prev = [
        unit("u1", "alpha beta gamma delta"),
        unit("u2", "epsilon zeta eta theta"),
    ]
    inc = [
        unit("n1", "alpha beta"),
        unit("n2", "gamma delta epsilon zeta"),
        unit("n3", "eta theta"),
    ]
    return "split_and_merge", inc, prev


def case_identical_candidates():
    prev = [unit("u1", "x y z"), unit("u2", "x y z"), unit("u3", "x y z")]
    inc = [unit("n1", "x y z"), unit("n2", "x y z")]
    return "identical_candidate_set", inc, prev


def case_contended_column():
    """Two rows whose best candidate is the same column.

    This is where the global `taken` set decides the runner-up, so it is the
    case any component decomposition is most likely to change.
    """
    prev = [unit("u1", "shared core text"), unit("u2", "unrelated other text")]
    inc = [unit("n1", "shared core text"), unit("n2", "shared core text!")]
    return "contended_column", inc, prev


CASES = [
    case_ordinary, case_equal_score_tie, case_split, case_merge,
    case_split_and_merge, case_identical_candidates, case_contended_column,
]


# --- invariant probes -------------------------------------------------------


def probe_candidate_order(name, inc, prev) -> dict[str, Any]:
    """I-ORDER: is the row-attached outcome invariant to candidate order?

    Permuting `previous` does not change the problem: the same units are on
    offer. If the outcome changes, candidate enumeration order is part of the
    semantic state and no reordering-based optimisation is safe.
    """
    base = outcome(run(inc, prev))
    divergent = []
    perms = list(itertools.permutations(range(len(prev))))
    for perm in perms[:24]:
        permuted = [prev[i] for i in perm]
        got = outcome(run(inc, permuted))
        if got != base:
            divergent.append({"permutation": list(perm), "outcome": got})
    return {
        "case": name,
        "permutations_tried": min(len(perms), 24),
        "baseline": base,
        "divergent_count": len(divergent),
        "invariant_holds": not divergent,
        "examples": divergent[:2],
    }


#: The facets a sparse replacement would have to preserve, separated because
#: they are not equally load-bearing and the first probe conflated them. A
#: difference in which tied candidate is *reported* is not the same failure as a
#: difference in what a unit *is*.
FACETS = {
    "classification_and_identity": lambda d: (d["match"], d["logical_id"]),
    "candidate_attribution": lambda d: (d["match"], d["logical_id"], tuple(d["candidates"])),
    "full_row_outcome": lambda d: tuple(sorted(d.items(), key=lambda kv: kv[0])),
}


def probe_candidate_order_by_facet(name, inc, prev) -> dict[str, Any]:
    """I-ORDER split by facet.

    The first version of this probe compared whole rows and reported the tie
    cases as violations. They are -- but only in the reported candidate tuple.
    Whether the match classification and logical id also move is a different
    question with a different consequence for P2-13, so it is asked separately
    rather than folded into one boolean.
    """
    base = outcome(run(inc, prev))
    perms = list(itertools.permutations(range(len(prev))))[:24]
    out: dict[str, Any] = {"case": name, "permutations_tried": len(perms)}
    for facet, key in FACETS.items():
        divergent = []
        base_key = [key(d) for d in base]
        for perm in perms:
            got = outcome(run(inc, [prev[i] for i in perm]))
            got_key = [key(d) for d in got]
            if got_key != base_key:
                divergent.append(
                    {
                        "permutation": list(perm),
                        "baseline": [list(map(str, k)) for k in base_key],
                        "permuted": [list(map(str, k)) for k in got_key],
                    }
                )
        out[facet] = {
            "divergent_count": len(divergent),
            "invariant_holds": not divergent,
            "examples": divergent[:2],
        }
    return out


def probe_row_order(name, inc, prev) -> dict[str, Any]:
    """I-ROWORDER: does permuting incoming rows change each row's own outcome?

    Compared after mapping back to the original row, so a pure relabelling is
    not counted as a divergence.
    """
    base = {d["row"]: d for d in outcome(run(inc, prev))}
    divergent = []
    perms = list(itertools.permutations(range(len(inc))))
    for perm in perms[:24]:
        permuted = [inc[i] for i in perm]
        got = outcome(run(permuted, prev))
        remapped = {perm[d["row"]]: d for d in got}
        for original_row, d in remapped.items():
            b = base[original_row]
            if (d["match"], d["logical_id"]) != (b["match"], b["logical_id"]):
                divergent.append(
                    {
                        "permutation": list(perm),
                        "row": original_row,
                        "baseline": {"match": b["match"], "logical_id": b["logical_id"]},
                        "permuted": {"match": d["match"], "logical_id": d["logical_id"]},
                    }
                )
    return {
        "case": name,
        "permutations_tried": min(len(perms), 24),
        "divergent_count": len(divergent),
        "invariant_holds": not divergent,
        "examples": divergent[:2],
    }


def probe_determinism(name, inc, prev, repeats: int = 5) -> dict[str, Any]:
    """I1/I10: same input, same output, repeatedly."""
    base = outcome(run(inc, prev))
    stable = all(outcome(run(inc, prev)) == base for _ in range(repeats))
    return {"case": name, "repeats": repeats, "invariant_holds": stable}


def probe_decomposition(name, inc, prev) -> dict[str, Any]:
    """I-DECOMP: does splitting the window into halves preserve row outcomes?

    This is the *positive control* for the whole exercise. Component
    decomposition is the obvious sparse strategy, and if it changes outcomes
    here then the instrument can detect the class of error P2-13 must avoid --
    which is what makes a later null meaningful.
    """
    if len(inc) < 2:
        return {"case": name, "applicable": False, "invariant_holds": None}
    base = {d["row"]: d for d in outcome(run(inc, prev))}
    half = len(inc) // 2
    left = outcome(run(inc[:half], prev))
    right = outcome(run(inc[half:], prev))
    divergent = []
    for d in left:
        b = base[d["row"]]
        if (d["match"], d["logical_id"]) != (b["match"], b["logical_id"]):
            divergent.append({"row": d["row"], "facet": "classification_and_identity",
                              "whole": b, "decomposed": d})
    for d in right:
        row = d["row"] + half
        b = base[row]
        if (d["match"], d["logical_id"]) != (b["match"], b["logical_id"]):
            divergent.append({"row": row, "whole": b, "decomposed": d})
    return {
        "case": name,
        "applicable": True,
        "divergent_count": len(divergent),
        "invariant_holds": not divergent,
        "examples": divergent[:3],
        "note": (
            "decomposition splits ROWS while leaving every candidate on offer to "
            "both halves, so any divergence is caused by the global one-to-one "
            "constraint and the global runner-up, not by hiding candidates"
        ),
    }


def sha256_file(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def canonical_sha256(v: Any) -> str:
    body = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> int:
    exp = Path(__file__).resolve().parents[1]
    out = exp / "receipts" / "legacy-invariant-probe-2026-08-19.json"

    results: dict[str, Any] = {}
    for builder in CASES:
        name, inc, prev = builder()
        results[name] = {
            "incoming": [u.logical_id for u in inc],
            "previous": [u.logical_id for u in prev],
            "I_DETERMINISM": probe_determinism(name, inc, prev),
            "I_CANDIDATE_ORDER": probe_candidate_order(name, inc, prev),
            "I_CANDIDATE_ORDER_BY_FACET": probe_candidate_order_by_facet(name, inc, prev),
            "I_ROW_ORDER": probe_row_order(name, inc, prev),
            "I_DECOMPOSITION": probe_decomposition(name, inc, prev),
        }

    def holds(key):
        vals = [
            r[key]["invariant_holds"]
            for r in results.values()
            if r[key]["invariant_holds"] is not None
        ]
        return {
            "all_cases_hold": all(vals),
            "cases_violating": [
                n for n, r in results.items() if r[key]["invariant_holds"] is False
            ],
        }

    def facet_holds(facet):
        vals = {
            n: r["I_CANDIDATE_ORDER_BY_FACET"][facet]["invariant_holds"]
            for n, r in results.items()
        }
        return {
            "all_cases_hold": all(vals.values()),
            "cases_violating": [n for n, v in vals.items() if not v],
        }

    summary = {
        "I_DETERMINISM": holds("I_DETERMINISM"),
        "I_CANDIDATE_ORDER_classification_and_identity": facet_holds(
            "classification_and_identity"
        ),
        "I_CANDIDATE_ORDER_candidate_attribution": facet_holds("candidate_attribution"),
        "I_CANDIDATE_ORDER": holds("I_CANDIDATE_ORDER"),
        "I_ROW_ORDER": holds("I_ROW_ORDER"),
        "I_DECOMPOSITION": holds("I_DECOMPOSITION"),
    }

    receipt: dict[str, Any] = {
        "schema": "tavonel.legacy-invariant-probe.v1",
        "experiment": "H1-K-LEGACY-INVARIANT-EXTRACTION-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "identity_module_sha256": sha256_file(IDENT),
        "purpose": (
            "Establish which candidate invariants LEGACY actually satisfies, "
            "before any sparse replacement is designed against them."
        ),
        "policy_under_test": "LEGACY",
        "blocked_policy_touched": False,
        "cases": results,
        "summary": summary,
        "instrument_separation": {
            "note": (
                "I_DECOMPOSITION is the positive control: it is the obvious "
                "sparse strategy and the one H1-E2 vetoed. If it never diverges "
                "here the probe cannot detect the error class P2-13 must avoid, "
                "and every other null in this receipt is uncitable."
            ),
            "decomposition_separates": bool(summary["I_DECOMPOSITION"]["cases_violating"]),
        },
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for key, val in summary.items():
        state = "HOLDS" if val["all_cases_hold"] else "VIOLATED"
        print(f"{key:<20} {state:<9} violating={val['cases_violating']}")
    print(f"decomposition separates: {receipt['instrument_separation']['decomposition_separates']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
