#!/usr/bin/env python3
"""P2-13 -- CERTIFIED_SPARSE: exact-semantics candidate elimination.

Contract: ../SEMANTIC_CONTRACT_2026-08-19.md, frozen before this was written.

Not a heuristic. The design follows contract §6: never prune on a guess, prune
only what a certificate proves irrelevant, and fall back to dense LEGACY the
moment certification cannot be completed.

Why this is not the BLOCKED policy again. BLOCKED bucketed candidates by path
root and hoped the buckets did not interact; H1-E2 measured that they do, and it
is vetoed. This policy never removes a candidate from the *problem*. It avoids
calling `score_pair` on pairs an admissible bound proves cannot matter, then
solves the same global assignment over the same candidate set. Where the bound
cannot certify, the exact score is computed after all.

The saving is in scoring calls avoided, not in problem size reduced. That is the
only kind of saving that can be exact here.

`identity.py` is not modified and `MatchingPolicy.BLOCKED` is not touched.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.identity import (  # noqa: E402
    LogicalIdentityResolver,
    LogicalUnitFingerprint,
    _max_weight_matching,
)

#: The one expensive signal. Everything else is O(1) on cached fields; the
#: Jaccard is O(len) and is what a large window pays for.
EXPENSIVE_SIGNAL = "semantic"


@dataclass
class Stats:
    exact_score_calls: int = 0
    bound_calls: int = 0
    edges_total: int = 0
    edges_certified_irrelevant: int = 0
    certification_rounds: int = 0
    fell_back_dense: bool = False
    fallback_reason: str = ""
    notes: list[str] = field(default_factory=list)


def _tokens(unit: LogicalUnitFingerprint) -> int:
    text = getattr(unit, "normalized_text", "") or ""
    return len(set(text.split()))


def jaccard_upper_bound(a: LogicalUnitFingerprint, b: LogicalUnitFingerprint) -> float:
    """Admissible: |A cap B| <= min(|A|,|B|) and |A cup B| >= max(|A|,|B|).

    So J = |A cap B| / |A cup B| <= min/max, computable from cached token counts alone.
    Equals 1.0 when both are empty, which is also the ceiling, so still an upper
    bound.
    """
    na, nb = _tokens(a), _tokens(b)
    if na == 0 and nb == 0:
        return 1.0
    hi = max(na, nb)
    return 1.0 if hi == 0 else min(na, nb) / hi


def score_upper_bound(
    engine: LogicalIdentityResolver,
    candidate: LogicalUnitFingerprint,
    incoming: LogicalUnitFingerprint,
    stats: Stats,
) -> float:
    """U >= score_pair(...)[0], computed without the Jaccard.

    Every cheap signal is evaluated exactly; the expensive one is replaced by its
    length bound. Renormalisation is over the same available-weight denominator
    the real scorer uses, so the substitution is monotone: raising one present
    signal to an upper bound raises the weighted mean to an upper bound.
    """
    stats.bound_calls += 1
    present, _missing = engine._signals(candidate, incoming)
    weights = engine.weights
    available = sum(weights[name] for name in present)
    if available <= 0.0:
        return 0.0
    total = 0.0
    for name, value in present.items():
        if name == EXPENSIVE_SIGNAL:
            total += weights[name] * jaccard_upper_bound(candidate, incoming)
        else:
            total += weights[name] * value
    return total / available


def exact_score(
    engine: LogicalIdentityResolver,
    candidate: LogicalUnitFingerprint,
    incoming: LogicalUnitFingerprint,
    stats: Stats,
) -> float:
    stats.exact_score_calls += 1
    return engine.score_pair(candidate, incoming)[0]


def assign_certified_sparse(
    incoming: list[LogicalUnitFingerprint],
    previous: list[LogicalUnitFingerprint],
    *,
    resolver: LogicalIdentityResolver | None = None,
    stats: Stats | None = None,
) -> tuple[list, Stats]:
    """Reproduce LEGACY's decisions while skipping provably irrelevant scoring.

    Returns the same decision list `assign_one_to_one(policy=LEGACY)` returns.
    """
    engine = resolver or LogicalIdentityResolver()
    st = stats or Stats()
    if not incoming:
        return [], st
    if not previous:
        return [engine.resolve(unit, []) for unit in incoming], st

    rows, cols = len(incoming), len(previous)
    st.edges_total = rows * cols

    # --- 1. cheap admissible bounds over every edge ------------------------
    ub = [
        [score_upper_bound(engine, previous[j], incoming[i], st) for j in range(cols)]
        for i in range(rows)
    ]

    # --- 2. seed set: contract §5 forbids within-row rank pruning for the
    # winner, and bounds the runner-up at the (N+1)-th column. Keep that many
    # by upper bound, which is the smallest set that can possibly be sound.
    keep_per_row = min(cols, rows + 1)
    kept: list[set[int]] = []
    for i in range(rows):
        order = sorted(range(cols), key=lambda j: (-ub[i][j], j))
        kept.append(set(order[:keep_per_row]))

    scores: list[list[float]] = [[0.0] * cols for _ in range(rows)]
    computed: list[list[bool]] = [[False] * cols for _ in range(rows)]

    def ensure(i: int, j: int) -> float:
        if not computed[i][j]:
            scores[i][j] = exact_score(engine, previous[j], incoming[i], st)
            computed[i][j] = True
        return scores[i][j]

    # --- 3. solve / certify / restore loop ---------------------------------
    for _round in range(rows + 2):
        st.certification_rounds += 1
        for i in range(rows):
            for j in kept[i]:
                ensure(i, j)
        # Omitted edges enter the solver at their upper bound. If the solver
        # never selects one, the assignment is optimal for the true matrix too,
        # because the true score is no larger.
        working = [
            [scores[i][j] if computed[i][j] else ub[i][j] for j in range(cols)]
            for i in range(rows)
        ]
        assignment = _max_weight_matching(working)

        # (a) an omitted edge was selected -> its bound was not conservative
        #     enough to dismiss it, so compute it for real and re-solve.
        uncertified = {
            (i, j) for i, j in assignment.items() if not computed[i][j]
        }
        # (b) runner-up certification: an omitted edge could be a row's rival.
        # A dual-based certificate was drafted here and removed: it proves an
        # edge cannot improve the *assignment*, which says nothing about whether
        # it could be a row's rival. The rival test below is the one that matters.
        for i in range(rows):
            c = assignment.get(i)
            taken = {col for r, col in assignment.items() if r != i}
            best_known_rival = max(
                (working[i][k] for k in range(cols) if k != c and k not in taken),
                default=0.0,
            )
            for j in range(cols):
                if computed[i][j] or j == c or j in taken:
                    continue
                # Could this omitted edge be the runner-up? Only if its bound
                # reaches the best known rival. Ties count: equal scores change
                # `runner_up_id`, which is part of the contract.
                if ub[i][j] >= best_known_rival:
                    uncertified.add((i, j))

        if not uncertified:
            st.edges_certified_irrelevant = sum(
                1 for i in range(rows) for j in range(cols) if not computed[i][j]
            )
            break
        for i, j in uncertified:
            kept[i].add(j)
    else:
        st.fell_back_dense = True
        st.fallback_reason = "certification did not converge; computing dense"
        for i in range(rows):
            for j in range(cols):
                ensure(i, j)
        assignment = _max_weight_matching(scores)

    # --- 4. decisions, identical in shape to LEGACY ------------------------
    final = [
        [scores[i][j] if computed[i][j] else ub[i][j] for j in range(cols)]
        for i in range(rows)
    ]
    assignment = _max_weight_matching(final)
    decisions = []
    for index, unit in enumerate(incoming):
        column = assignment.get(index)
        if column is None:
            decisions.append(engine.resolve(unit, []))
            continue
        taken = {col for row, col in assignment.items() if row != index}
        rivals = [
            (final[index][col], previous[col].logical_id)
            for col in range(cols)
            if col != column and col not in taken
        ]
        runner_up, runner_up_id = max(rivals, default=(0.0, None))
        score, signals, missing = engine.score_pair(previous[column], unit)
        st.exact_score_calls += 1
        decisions.append(
            engine.decide_pair(
                incoming=unit,
                partner=previous[column],
                score=score,
                signals=signals,
                missing=missing,
                runner_up=runner_up,
                runner_up_id=runner_up_id,
                seed_logical_id=unit.logical_id,
            )
        )
    return decisions, st


def stats_record(st: Stats) -> dict[str, Any]:
    saved = st.edges_total - st.exact_score_calls
    return {
        "edges_total": st.edges_total,
        "exact_score_calls": st.exact_score_calls,
        "bound_calls": st.bound_calls,
        "scoring_calls_saved": saved,
        "saved_fraction": round(saved / st.edges_total, 6) if st.edges_total else 0.0,
        "certification_rounds": st.certification_rounds,
        "fell_back_dense": st.fell_back_dense,
        "fallback_reason": st.fallback_reason,
    }
