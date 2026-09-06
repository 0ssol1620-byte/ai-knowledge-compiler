# LEGACY matching semantics — extracted invariants

**Status: EXPLORATORY extraction, not a frozen-endpoint experiment.** No claim is
promoted from this document. Its purpose is to make "preserve LEGACY's semantics
exactly" a specification that a later, properly frozen experiment can be run
against — P2-13 §4.1 asked for exactly this before any implementation.

Evidence: `receipts/legacy-invariant-probe-2026-08-19.json`. Every statement
below is either a code citation or a probe result; nothing is asserted from
reading alone.

---

## 1. What LEGACY actually is

`assign_one_to_one(policy=LEGACY)`, `identity.py:1000-1071`:

1. build the **dense** N x M score matrix, `score_pair` for every (incoming,
   previous) pair;
2. `_max_weight_matching` — Hungarian over that matrix, padded to
   `max(rows, cols)` with zero weight, maximising total weight;
3. for each row, compute the runner-up over columns **not taken by any other
   row** in the global assignment;
4. apply the bands (`decide_pair`) to the assigned pair.

A row the matching leaves unassigned falls through to `engine.resolve(unit, [])`
and becomes **NEW**.

### Two structural facts that drive everything

**(a) The runner-up is global.** `taken = {col for row, col in assignment.items()
if row != index}` (line 1050). Whether a column counts as competition for row *i*
depends on what *every other row* took. The tie guard therefore reads a global
property, not a local one.

**(b) Exclusivity manufactures NEW.** A row that loses a contended column to
another row is not scored against a second-best — it is assigned nothing and
returns NEW. NEW is thus produced by the *global one-to-one constraint*, not by a
low score.

---

## 2. Probe results — which invariants hold

Seven cases: ordinary, equal-score tie, split, merge, split-and-merge, identical
candidate set, contended column.

| invariant | holds? | violating cases |
|---|---|---|
| **I1 / I10 determinism** — same input, same output | **HOLDS** | — |
| **I-CANDIDATE-ORDER, classification + logical id** | **HOLDS** | — |
| **I-CANDIDATE-ORDER, reported candidate attribution** | **VIOLATED** | equal_score_tie, identical_candidate_set |
| **I-ROW-ORDER** — permuting incoming rows | **HOLDS** | — |
| **I-DECOMPOSITION** — splitting the row window | **VIOLATED** | split, split_and_merge |

**The decomposition probe is the positive control and it separates**, so the
nulls above are citable. This is the H1-I Amendment 1 rule applied in advance.

### 2.1 The good news, and it is load-bearing for P2-13

**Permuting the candidate list does not change any unit's match classification or
logical id.** LEGACY's *identity* semantics are order-invariant with respect to
candidate enumeration order.

That matters because every sparse strategy changes candidate enumeration order by
construction. This result says that alone is not disqualifying.

### 2.2 The bad news, stated exactly

**Row-window decomposition changes classification.** On both `split` and
`split_and_merge`, row 1 is **NEW** in the whole window and **AMBIGUOUS** when the
window is split:

    whole window   row 1 -> (new, n2)
    decomposed     row 1 -> (ambiguous, None)

Mechanism: in the whole window row 1 loses the contended column to row 0 under
global exclusivity, is assigned nothing, and returns NEW. Alone in its half it
wins that column and lands in the ambiguous band.

**This is the formal explanation of the H1-E/H1-E2 veto.** BLOCKED prunes
candidates into path-root buckets, which changes which rows compete for which
columns, which changes exclusivity outcomes, which flips the classification. And
because an AMBIGUOUS decision carries `logical_id=None`, the next revision seeds a
fresh identity and the lineage forks **permanently** — which is why 8 residual
divergences became 8/8 future-path divergences rather than washing out.

### 2.3 A semantics that is not a semantics

Under exact ties, which previous unit is reported in `candidates` depends on the
order of the `previous` list. `_max_weight_matching` has **no explicit tie-break**
among equal-weight optimal assignments; the winner falls out of the Hungarian
iteration order and the zero-padding.

So under exact ties the selection among equal-weight optima is not fixed by any
semantic rule. Two statements must be kept apart here:

- **the problem specification does not define a unique optimum** — true;
- **the implementation is nondeterministic** — **false**, and not claimed. The
  repeat-determinism probe HOLDS. Iteration order and zero-padding select one
  optimum *repeatably*.

> **WITHDRAWN by Amendment 1.** This section originally concluded that the
> attribution therefore sits outside the semantics. That inference was wrong:
> "the implementation does not define it stably" and "it is not part of the
> contract" are different statements. The audit in
> `AMENDMENT_1_2026-08-19.md` found the field is consumed by selective
> recompilation and the promotion gate and is serialized into the diff record,
> so it **is** a contract. See §4 and §5 as amended.

Note what this does *not* say: `match` and `logical_id` were stable across every
permutation tried. The instability is confined to the reported attribution.

---

## 3. Answers to the four questions P2-13 §4.2 required

**Is candidate enumeration order part of the semantic state?**
For the reported tie attribution, **yes**. For match classification and logical
id, **no** — probed across all permutations of every case.

**At score equality, is deterministic row ordering the tie-breaker?**
In `resolve` there is an explicit one: `sorted(..., key=(-score, logical_id))`
(line 633). In `assign_one_to_one` there is **none** — the Hungarian's internal
iteration order decides, with no logical-id tie-break at the assignment level.
The two paths do not share a tie-breaking rule.

**When do global assignment and local decomposition differ?**
Whenever two rows contend for the same column and the global optimum awards it to
one of them. The loser returns NEW globally and can return AMBIGUOUS or MATCHED
locally. Demonstrated on `split` and `split_and_merge`.

**Why is the difference amplified in the next revision?**
AMBIGUOUS yields `logical_id=None`. The next revision therefore seeds a new
identity instead of continuing the existing one, so a single flipped
classification becomes a permanent lineage fork rather than a one-revision
discrepancy.

---

## 4. Consequence for the P2-13 design space

Assessed against §4.3's candidate directions. **These are design implications,
not results.**

| direction | assessment |
|---|---|
| **B. Exact component decomposition** | **Directly contradicted** unless the sufficient condition proves components never contend for a shared column. The probe shows contention is exactly where it breaks. |
| **A / E. Admissible upper-bound pruning, branch-and-bound** | **Still open, and the most promising.** These prune *edges that cannot win* while leaving the global one-to-one problem intact. The existing `PRUNED_CANDIDATE_SCORE_CEILING = 0.80` lemma is this kind of argument. |
| **C / F. Sparse generation with dense fallback; two-stage** | **Still open**, but the fallback trigger must be driven by *contention*, not by score uncertainty alone. A row can be confidently scored and still have its outcome decided by another row's assignment. |
| **D. Tie-preserving neighborhood expansion** | **Reassessed upward by Amendment 1.** Preserving tie attribution is not optional after all, so a strategy that explicitly preserves it is more valuable than first judged — but the target is the Hungarian selection over the caller's list order, which any reordering perturbs. |

**Recommended primary endpoint — as amended.** Row-attached exact equivalence on
**classification + logical id + candidate attribution**, plus future-path and
downstream impact/rebuild equivalence.

> The original recommendation demoted candidate attribution to a secondary,
> disclosed endpoint. **Amendment 1 withdrew that.** A different attribution
> produces a different rebuild set (`artifact:from_u1` vs `artifact:from_u2`)
> and a different serialized record, so it is externally observable and belongs
> in the primary endpoint.

Still a proposal, still not frozen. Freezing it is the first step of the next
experiment — and the amendment is the reason freezing it here would have been
premature.

---

## 5. What this document does not establish

- No new matcher exists, and none is proposed as viable.
- No claim about achievable speedup.
- `MatchingPolicy.BLOCKED` remains vetoed. Nothing here reinterprets H1-E2.
- Seven small constructed cases, not the H1-E residual 8, and not scale. A frozen
  protocol must include those; this extraction deliberately did not, because its
  job was to find out what to measure.
