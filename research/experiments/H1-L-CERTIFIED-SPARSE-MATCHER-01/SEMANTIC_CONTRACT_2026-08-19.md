# P2-13 §1A — LEGACY's observable semantic contract, frozen

**Frozen 2026-08-19 before any replacement matcher was written.** This is the
specification an exact sparse matcher must reproduce. It is derived from code and
from H1-K's measurements, not from intent.

`MatchingPolicy.BLOCKED` is untouched and remains under the H1-E2 promotion veto.
Nothing here reinterprets it.

---

## 1. The contract — every facet a replacement must reproduce

For a window `(incoming[0..N), previous[0..M))` the observable footprint is the
**ordered, row-attached** tuple below. A multiset comparison is explicitly not
the endpoint.

### Per row `i`, in row order

| facet | source | why it is in the contract |
|---|---|---|
| `match` | `LogicalIdentityDecision.match` | the classification itself |
| `logical_id` | same | decides whether the next revision continues or seeds |
| `assigned_column` | `assignment[i]` | which previous unit was paired |
| `candidates` | `decision.candidates` | **H1-K Amendment 1: semantic, not diagnostic** |
| `relation` | `decision.relation` | `MOVED_FROM` vs `SAME_AS_VERSION` |
| `score` | `decision.score` | appears in the serialized record |

### Derived, whole-window

| facet | source |
|---|---|
| serialized semantic record | `SemanticChange.as_record()` for every change |
| `changed_logical_ids` | `SemanticDiff.changed_logical_ids` |
| unresolved seed set | `recompilation.py:250-253`, seeded from `candidates` |
| dependency impact set | `graph.impact_of(seeds)` |
| selective rebuild set | `plan_recompilation` targets and states |
| next-revision lineage | the decisions produced when the result is fed forward |

### Why `candidates` is in the primary endpoint

H1-K Amendment 1 measured it: with the same logical problem and `previous`
permuted, `candidates` moved from `['u1']` to `['u2']` and the impacted artifact
set moved from `artifact:from_u1` to `artifact:from_u2`. It seeds selective
recompilation and the promotion gate's changes-accounted check, and it is
serialized. It is a contract, not a diagnostic.

## 2. Determinism vs specification — kept apart

- The **problem** admits multiple equal-weight optimal assignments and no
  semantic rule selects among them.
- The **implementation** is *not* nondeterministic. H1-K's repeat probe HOLDS.
  Hungarian iteration order and zero-padding select one optimum repeatably.

A replacement must therefore reproduce **the selected optimum**, not merely *an*
optimum of equal weight. Returning a different equal-weight assignment is a
contract violation even though it is equally optimal.

## 3. What LEGACY computes, restated precisely

    S[i][j] = score_pair(previous[j], incoming[i])[0]          # dense, N x M
    A       = Hungarian(S)  padded to max(N,M) with weight 0   # row -> column
    for row i with c = A(i):
        taken     = { A(j) : j != i }
        rivals    = { (S[i][k], id_k) : k != c, k not in taken }
        runner_up = max(rivals, default=(0.0, None))
        decide_pair(partner=previous[c], score=S[i][c], runner_up=...)
    rows with no column -> resolve(unit, []) -> NEW

## 4. Exactness obligations for any pruning

Removing edge `(i, j)` is safe only if it changes none of:

1. the selected assignment `A` — not merely its total weight;
2. every row's assigned column;
3. every row's `runner_up` value **and** `runner_up_id`;
4. classification, `logical_id`, `candidates`, `relation`;
5. the derived whole-window facets in §1.

**Preserving the winner is insufficient**, measured: H1-K Amendment 2 flipped
`AMBIGUOUS -> NEW` in 8 of 8 cases by withholding a candidate that the 0.80
ceiling licenses pruning, while the ceiling's own claim ("cannot become MATCHED")
held throughout.

## 5. Two facts that constrain the algorithm

**(a) A row's assigned column can be arbitrarily low-ranked within that row.**
The assignment maximises total weight globally, so row `i` may be given a column
it scores poorly against because that frees a better column for another row.
**Therefore no pruning rule based on within-row score rank alone can be sound for
the winner.** This rules out "keep the top-K candidates per row" as an exact
strategy on its own.

**(b) The runner-up is bounded by row rank, but only weakly.** At most `N-1`
columns are taken by other rows, so row `i`'s runner-up is at worst its
`(N+1)`-th highest column. Keeping fewer than `N+1` per row cannot be sound for
the runner-up facet either.

## 6. The strategy this contract admits

Certification, not heuristic pruning:

1. compute a **cheap admissible upper bound** `U[i][j] >= S[i][j]`;
2. solve the assignment on a sparse subset;
3. **certify** with the LP dual: for every omitted edge, if
   `U[i][j] - u[i] - v[j] <= 0` the edge cannot enter any improving assignment,
   and it never needed its exact score computed;
4. any edge failing certification is restored and the solve repeats;
5. certify the runner-up per row by the same bound;
6. where certification cannot be completed, fall back to dense LEGACY.

The saving is in **not calling `score_pair`**, which is where the cost is. The
admissible bound uses only the cheap signals plus a length bound on the Jaccard
term.

Correctness does not depend on the bound being tight — only on it being an upper
bound. A loose bound costs speed, never exactness.

## 7. Frozen

This contract is fixed before the matcher exists. If the matcher cannot meet it,
the honest outcome is *exact sparse acceleration remains unresolved* — not a
relaxed contract.
