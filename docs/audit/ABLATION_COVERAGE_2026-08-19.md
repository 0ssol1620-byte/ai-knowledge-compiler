# Ablation coverage — which load-bearing mechanisms are actually ablated

2026-08-19. Written to answer one question and not to generate work:

> For each mechanism the patent claims or the manuscript leans on, is there
> evidence that **removing it breaks something**, or only evidence that keeping
> it works?

A mechanism supported only by "the system passes with it enabled" is not
evidenced as load-bearing. It could be inert. An ablation is what separates the
two, and several already exist in this repository under other names — a
falsification arm, a mutation sweep and a reproduced defect are all ablations.
Re-running them under an "ablation" label would spend compute to learn nothing.

**Rule applied:** existing evidence is reused where its provenance holds; a new
experiment is proposed only where no ablation-shaped evidence exists.

---

## 1. Mechanisms with ablation evidence already

### 1.1 Structural change channel — claim B1 element 5

**Ablated by:** `B-STRUCTURE-ONLY-STALE-DEFECT`
(`structure-only-stale-diagnosis-2026-08-18.json`).

This is the strongest ablation in the programme and it was not designed as one.
The mechanism was *absent*, a reorder-only revision produced no changed logical
ids, the traversal seed was empty, and a stale position-aggregated artifact was
carried forward as CURRENT — `all_equivalent = False`, `stale_left_behind = 2`.

Removing the mechanism produces the exact failure the mechanism exists to
prevent, on the real implementation, with a receipt. **No new experiment.**

### 1.2 Promotion gate ordering and refusal — claim B1 elements 7-9

**Ablated by:** `declaration-mutation-2026-08-19.json`,
`build-record-mutation-2026-08-19.json`, and the 21 enumerated refusals in
`atomic-promotion-audit-2026-08-19.json`.

Mutation sweeps *are* ablations of the integrity checks: corrupt the declaration
or the build record and the gate must refuse. The H1-G audit enumerates each
refusal individually rather than asserting "the gate works", so each check is
separately evidenced as load-bearing.

**Gap, honest:** these ablate the *inputs* to the gate, not the gate's
**ordering**. The claim recites order as a limitation, and the argument for it
(an integrity check before completeness can pass an incomplete-but-consistent
state) is currently reasoning, not measurement. See §2.1.

### 1.3 Candidate index safety — claim B4

**Ablated by:** the `path_root_bucket_removed` falsification arm in
`shadow-equivalence-rerun-pinned-2026-08-19.json`.

Emptying the candidate set produces 80 divergent decisions where the intact
index produces zero. The comparator demonstrably separates, which is what makes
the zero meaningful. **No new experiment.**

Note the retained null arm (`identifier_and_anchor_union_removed`,
`separates: false`) is an ablation that *could not* separate by construction. It
is kept as a recorded null, not as evidence of safety.

### 1.4 Tie guard and critical-signal abstention — claim B3

**Ablated by:** the `near_tie` topology (H1-E) and, more sharply, by
**H1-E2**. H1-E2 is the ablation that mattered: it removed the assumption that a
tie permutation is harmless and found 8/8 of the residual permutations were
path-dependent into the next revision. That result **vetoed a promotion**, which
is the strongest possible demonstration that the mechanism is load-bearing.

**No new experiment.** This one already changed a decision.

### 1.5 Untracked-builder integrity ceiling

**Ablated by:** the H1-G contract behaviour "a builder without tracked capture
cannot reach HIGH_INTEGRITY; the permissive path yields DEGRADED_UNTRACKED".
Removing the ceiling is exactly the permissive path, and it is tested to produce
a degraded level rather than a trusted one.

---

## 2. Genuine gaps — no ablation evidence exists

Only two, and both are cheap and CPU-local. Neither is started here, because
starting an experiment without a frozen protocol is the failure mode this
programme is organised against.

### 2.1 Gate **ordering** — MEASURED 2026-08-19, claim narrowed

The claim recites the order of the four checks as a limitation. Nothing measures
that reordering them changes an outcome.

*What would evidence it:* a permutation ablation that runs the four checks in
each order against a candidate state that is internally consistent **and**
incomplete, and reports which orders admit it. If no order ever differs, the
ordering is not load-bearing and **the claim limitation should be narrowed** —
that outcome must be acceptable before the experiment is run, or it is not an
experiment.

*Protocol must freeze first:* the constructed candidate states, the definition
of "admitted", and the rule that a null result narrows the claim.

**Done — `H1-I-GATE-ORDERING-01`.** The protocol froze all three, including the
narrowing rule. All 24 orders over 6 states, 144 evaluations: **0 verdict
divergences.** The narrowing rule fired and claim B1 element 7 now recites
an *order-invariant conjunction of candidate-state predicates* rather than an
*ordered sequence*.

**Amendment 2 narrowed the wording a second time.** The sentence first written
after the null said the checks are "mutually independent". Order-invariance does
not entail independence, and a static audit found the coupling that proves it:
in the no-oracle branch the integrity check's pass is discharged by the staleness
check (`promotion_gate.py:317-330`). The experiment was run correctly; the error
was in the sentence written afterwards, which is a distinct failure mode.

Two things had to happen before that null could be used, and both are the point:

- attempt 1 was **voided by the harness fidelity gate**, which caught the
  harness paraphrasing an internal against the wrong channel API;
- attempt 2 passed fidelity but its permutation arm **could not separate by
  construction** — the same defect as the H1-E null arm. Amendment 1 added a
  positive control, which diverged on 12 of 24 orders, and only then did the
  null become citable.

The mechanism is not inert; it is *commutative*. Order still determines which
refusal is reported. It does not determine whether one occurs.

### 2.2 Authority/temporal/lineage filters — MEASURED 2026-08-19, partially

`D-GOVERNANCE-LINEAGE-CONTROLLED` shows 22 cells passing with every filter
enabled. It does not show that removing the applicability filter, or the
evidence-override requirement, changes an answer.

*Risk if skipped:* an examiner or reviewer can ask whether the authority
ordering is doing any work beyond what the temporal filter already does, and the
current evidence cannot answer.

*What would evidence it:* disable one filter at a time over the same 11,000
controlled cases and report which cells flip. Cheap — the harness exists and is
deterministic.

**Done — `H1-J-GOVERNANCE-FILTER-ABLATION-01`, and the naive version of that
plan would have been wrong.** One-at-a-time ablation over a case set containing
a compliant alternative reports the permission, temporal and applicability
filters as doing nothing, because ranking elements 1-3 restate them. The
protocol therefore ran every filter against a *paired* state and a *solitary*
state where no compliant alternative exists.

| verdict | filters |
|---|---|
| essential — removal admits the violation | exclusion rule, conflict guard, explicit override, authority rank, source status, recency |
| **redundant but load-bearing** — masked when an alternative exists, sole refusal when none does | permission, temporal validity, applicability |
| **not measurable by this instrument** | ranking elements 1, 2, 3, 6 |

Two results changed claims. Ranking element 6 (specificity) is **provably
identical** to element 3 (scope match) for every admissible claim —
`scope_match` returns `len(scope)` unless it returns `-1`, and `specificity` is
defined as `len(scope)` — so it may not be recited as an independent ranking
element. And elements 1-3 are recorded as **NOT MEASURED**, which the protocol
distinguishes from measured-and-inert; their nulls are uncitable because their
positive controls did not separate.

§2.1 and §2.2 are now both closed. **§2.2 is closed partially and says so.**

---

### 1.6 Identity: global exclusivity — claim B1 element 2

**Ablated by:** `H1-K`'s decomposition probe, and by `H1-E2` before it.

Removing global exclusivity is exactly what window decomposition does, and it
flips `NEW -> AMBIGUOUS` on 2 of 7 constructed cases. `H1-E2` measured the
consequence on the real policy: 8 residual divergences, 8 of 8 path-dependent
into the next revision. The mechanism is not inert and the ablation changed a
promotion decision. **No new experiment.**

### 1.7 Identity: candidate restriction — claim B4

**Ablated by:** `H1-K` Amendment 2. Withholding a candidate the 0.80 bound
licenses pruning flipped `AMBIGUOUS -> NEW` in 8 of 8 cases, while the bound's own
guarantee ("cannot become MATCHED") held throughout. That is an ablation of the
restriction's *safety argument*, and it is why B4 now carries an explicit boundary.

### 1.8 Identity: the runner-up facet — no claim depends on it, and that is the finding

**Ablated by:** `H1-L`'s `runner_up_maximized` mutant, which separates on 17
cases. The facet is load-bearing for *exactness* but is not recited in any claim.
`H1-L` showed preserving it forbids sparsity on square windows.

---

## 2b. Remaining gaps after this session

§2.1 and §2.2 are closed. Mapping the mechanisms named as candidates for further
ablation:

| mechanism | already ablation-covered? |
|---|---|
| structural change channel | yes — §1.1, a reproduced defect |
| promotion gate integrity checks | yes — §1.2, mutation sweeps |
| gate ordering | yes — §2.1, measured null, claim narrowed |
| governance filters | partly — §2.2, 4 of 13 unmeasurable, disclosed |
| candidate index safety | yes — §1.3 and §1.7 |
| tie guard / critical-signal abstention | yes — §1.4, changed a decision |
| untracked-builder ceiling | yes — §1.5 |
| global exclusivity | yes — §1.6 |
| temporal interval handling | **covered indirectly** by §2.2's F2 filter ablation (redundant-but-load-bearing). A dedicated interval-arithmetic ablation would test a different thing — boundary handling — and no claim currently recites it. **Not a gap against the claim set.** |
| build receipt / provenance | **no ablation, and none is needed**: the claim already asserts only that the receipt evidences *what was declared*, not that the declaration was complete. There is no stronger property to ablate. |

**No further ablation is proposed.** Every remaining mechanism either has
ablation-shaped evidence, or supports a claim already drafted narrowly enough
that an ablation would test something the claim does not assert. Adding
experiments past that point grows the experiment count without growing evidence
quality, which §3 exists to prevent.

---

## 3. What this audit deliberately does not do

- It does not propose ablating mechanisms that no claim depends on. Coverage for
  its own sake is how experiment count grows without evidence quality growing.
- It does not re-run §1's experiments under new names.
- It does not treat §2's gaps as blocking. They weaken two specific claim
  limitations, and both limitations are currently stated conservatively enough
  that the gap is a narrowing risk rather than an overclaim.

## 4. Consequence for the current claim set

**No claim is withdrawn by this audit.** One was flagged and has since been
**narrowed**: claim B1's recitation of gate **ordering** rested on reasoning
rather than measurement (§2.1). The ablation was run, it returned a null, and the
limitation was narrowed rather than defended — element 7 now recites *mutually
independent* checks. Counsel should be told the narrowing was pre-committed in
the protocol, not chosen after seeing the result.

§2.2 remains open.
