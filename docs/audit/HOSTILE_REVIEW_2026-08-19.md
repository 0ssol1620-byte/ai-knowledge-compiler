# Hostile review — patent examiner, paper reviewer, reproducibility red-team

Written adversarially and against our own work. The rule for this document: a
finding is only allowed to be closed by a *change*, not by an explanation. Where
a finding stands open, it is listed as open and carries a severity.

Reviewed artifacts: `docs/ip/PATENT_CLAIM_SET_v1_2026-08-19.md`,
`docs/ip/PATENT_SPECIFICATION_v1_2026-08-19.md`,
`docs/paper/MANUSCRIPT_v1_2026-08-19.md`, `docs/ip/CLAIM_EVIDENCE_MATRIX.md`,
`docs/evidence/FAILED_AND_SUPERSEDED_LEDGER.md`,
`docs/repro/EXECUTION_INDEX_2026-08-19.json`, and the receipts they cite.

Updated 2026-08-19 for H1-E2 (identity tie path-dependence), H1-F (retrospective
real-corpus equivalence), H1-G (atomic promotion contract audit) and the
reproducibility execution index.

---

## Part 1 — Hostile patent examiner

### P1. "This is incremental compilation with extra words." — ADDRESSED

*Objection.* Elements 1–6 of claim B1 describe make with a content hash.
Dependency-typed rebuild is Bazel. Rejection under obviousness.

*Response.* The distinguishing elements are 5's structural sub-limitation and
7–9. A build system invalidates on *input change*; the distinguishing case here
is a change that alters only unit order, produces no content-level change, and
must still invalidate a position-dependent artifact. Element 8 — an artifact
declaring a structural dependency without declared structural coverage is
*unverifiable rather than passing* — has no analogue in a build cache, which
treats a cache hit as a pass. The specification carries a measured instance of
the failure that occurs without it.

*Residual.* The examiner may still argue that a build system with a
"structure hash" input reaches the same place. The answer must be that element 7
verifies the *whole candidate state* before activation rather than each target
at build time, and that the gate's ordering is a limitation. Counsel should
expect this to be the fight.

### P2. "Claim B1 element 10 is a business rule." — PARTIALLY OPEN

*Objection.* Authority ranking, applicability scope and permission filtering are
administrative rules, not technical.

*Response.* Element 10 is drafted as a *filter composed with the activated state
identifier*, and B6 adds the evidence-conditioned override and the
equal-authority conflict marking, which are mechanisms with defined outputs, not
policies. The permission sub-limitation is technical in a testable sense: an
excluded unit's identifier is not revealed, and that was measured at 500/500.

*Open, severity medium.* In jurisdictions that treat governance logic as
non-technical, B6 may need to be recast around the *abstention* behaviour — the
system declining to answer — rather than around authority ordering.

### P3. "Functional result, not mechanism." — CLOSED BY CHANGE

*Objection.* "Computing an affected set" and "verifying the candidate state" are
results.

*Action taken.* Element 5 was drafted to name the traversal seed and the edge
typing explicitly; element 7 enumerates the four checks and their order. The
drafting rule is stated in §0 of the claim set so a later edit cannot quietly
re-broaden it.

### P4. "Is the equivalence evidence actually sufficient?" — PARTIALLY CLOSED

*Objection.* The equivalence holdout is a **generated** corpus. Nine topologies
chosen by the inventors are not a proof of general equivalence.

*Response.* Conceded, and stated as a limitation rather than defended. The
holdout establishes that the mechanism is correct on adversarial structures we
could construct, including 64-deep chains, cross-document edges and diamonds
with conflicting semantic and structural channels. It does not establish
correctness on arbitrary graphs, and no claim asserts that.

*New evidence.* H1-F froze an all-stored rule over the 28 natural
English-Wikipedia revision pairs already present across the Family B corpora and
re-ran the current pinned implementation without network access. Selective state
matched the full-rebuild oracle in **28/28 pairs with stale = 0**; 11 pairs
contained semantic changed logical ids under the evaluation adapter.

*Still open, severity medium.* H1-F is retrospective, one source family and one
evaluation graph adapter. It closes the literal "no real-corpus arm" objection,
not arbitrary-graph or cross-source-family equivalence.

### P7. "Your atomic activation claim is a unit test." — PARTIALLY OPEN

*Objection.* Claim B1 elements 7-9 assert an ordered gate and an atomic
activation. The supporting evidence (H1-G) is a sealed audit of 21 contract
behaviours over 49 tests. Tests are not a demonstration that activation is
atomic under real failure.

*Response.* Conceded, and the receipt states its own boundary rather than
leaving it to be found: controlled implementation and unit-contract evidence
only. What the audit does establish is specific and enumerable — a checksum
mismatch, an integrity failure, an unexecuted permission check, a missing or
failing equivalence check, an unstaged object, a tampered receipt seal, and a
receipt bound to a prior world or another artifact each refuse to publish; a
failed publish leaves the previous ACTIVE state in place and emits no event; a
successful publish emits exactly one manifest-hash-bound event; and an untracked
builder cannot reach HIGH_INTEGRITY.

That is enablement-grade support for the *ordering and refusal* limitations,
which is what elements 7-9 actually recite. Elements 7-9 do not recite crash
safety, and the claim set must not be amended to imply it.

*Open, severity medium.* Not demonstrated: process crash mid-transaction;
partial database, network or storage failure; multi-node concurrent
publication. The word "atomic" in the specification therefore describes the
conditional single-step activation of a verified candidate, not a distributed
transaction guarantee, and counsel should expect that distinction to be probed.

*Also unchanged:* a builder that never records an input class cannot be caught
by receipt binding alone. The only available guarantee is fail-closed or
degraded handling of untracked builders. This is the same boundary as P6 and it
has not moved.

### P5. "Claim A3 has no evidence." — OPEN BY DESIGN

Cause-conditioned recovery has a pre-registration and no executed arm. It is
marked in the claim set as resting on enablement alone, and counsel is told so
explicitly. **Severity high if filed without that flag**; the flag is present.

### P6. "The seal is doing work you have not earned." — CLOSED

An earlier framing risked implying the build receipt evidenced consumption
completeness. It does not: a wrong input set can be sealed perfectly. This is
now an explicit non-claim in §6 of the claim set and a limitation in the
manuscript.

---

## Part 2 — Hostile paper reviewer

### R1. "Cherry-picking: you report the cells that passed." — CLOSED

All nine holdout cells are reported, including the two that over-rebuild (400
and 454 false invalidations), and the over-rebuild is explicitly *not* netted out
of the reported saving. The retained-failure ledger is an appendix, not a
footnote.

### R2. "The speedup hides the identity cost." — CLOSED BY CONSTRUCTION

This is the sharpest available objection and the manuscript raises it against
itself in §4.3, in bold, before a reviewer can. The two stages are reported in
separate tables and the matrix records "any end-to-end speedup figure that folds
identity cost into the ratio" as forbidden wording. The `MemoryError` is printed
in the results table rather than omitted.

### R3. "Leakage." — CLOSED FOR W6, OPEN AS A GENERAL RISK

W6 v1 was killed by its own binding upper-bound gate and is reported as
invalidated. The v3 candidate manifest was frozen before any revision outcome was
seen. *Open, severity low:* the A9 holdout's discovery/holdout split is
documented but was not audited by an outside party.

### R4. "Post-hoc tuning." — CLOSED, WITH DISCLOSURE

Two protocol amendments exist in H1-E. Both are recorded, both state what changed
and why, and **neither moved an acceptance criterion**: one replaced a
falsification arm that could not separate by construction, the other cut repeat
counts under a wall-clock bound while keeping scale coverage. The A9 evaluator
defect is disclosed as a post-unsealing correction rather than presented as the
original result.

### R5. "Synthetic-only." — PARTIALLY OPEN, NARROWED

*Objection after H1-F.* The paper is no longer synthetic-only: §4.1.1 now reports
28/28 selective/full equivalence on previously acquired natural Wikipedia
revision pairs. But Living Knowledge's broad mechanism space still relies mainly
on generated corpora, and the real arm is retrospective and single-source-family.

*Response.* Conceded and labelled throughout. The three evidence classes are
defined in §3.2 and every result carries one.

*Open, severity high — still the single biggest weakness of the paper.* Natural
revision equivalence is now measured in one English-Wikipedia source family, but
cross-source amendment relationships, layout/language diversity, and natural
authority/temporal/lineage distributions remain untested. The honest framing is
"mechanism correctness established; one-source real-corpus regression added;
broad external validity not established."

### R9. "Which of these mechanisms is actually load-bearing?" — MOSTLY CLOSED

*Objection.* The paper describes several mechanisms and shows the system working
with all of them enabled. That is not evidence any individual one matters.

*Response.* `docs/audit/ABLATION_COVERAGE_2026-08-19.md` maps each claimed
mechanism to ablation-shaped evidence that already exists: the structural
channel is ablated by the defect that occurred without it; the promotion gate by
the declaration and build-record mutation sweeps; the candidate index by the
falsification arm that empties it; and the tie guard by H1-E2, which vetoed a
promotion and is therefore the strongest available demonstration that a
mechanism is load-bearing.

*Open, severity low-medium, two specific gaps.* The **ordering** of the gate's
four checks is recited as a claim limitation but is supported by reasoning
rather than measurement, and the authority/temporal/lineage filters are not
individually ablated. Both are cheap and CPU-local; neither is started without a
frozen protocol, and the ordering protocol must accept in advance that a null
result narrows the claim.

### R6. "Unfair baseline." — NOT APPLICABLE / OPEN

No baseline comparison is claimed anywhere, because the endpoint that would have
required one (W6) did not run. This removes the objection and simultaneously is
the paper's largest missing result.

### R7. "Confidence intervals overstated." — CLOSED

The one interval that contains zero is reported as containing zero, the
magnitude claim built on it is withdrawn in the ledger, and the permitted
wording is fixed in the matrix so it cannot drift back.

### R8. "11,000 cases sounds impressive and means little." — CLOSED BY WORDING

Fair. 22 cells × 500 is 500 repetitions of 22 constructed scenarios, not 11,000
independent observations. The receipt's own `evidence_scope` says controlled
mechanism correctness only. The manuscript and claim matrix now lead with
**22 constructed mechanism cells**, state 500 deterministic repetitions per
cell, and retain 11,000 only as the execution count.

---

## Part 3 — Reproducibility red-team

### X1. Hashes — PASS

Every receipt carries `receipt_sha256`, its protocol's hash, and the hashes of
the code modules it exercised. The claim matrix generator re-verifies pinned
module hashes against live files and **refuses to emit** on mismatch. Verified
this session: the Family B holdout's pinned `dependency.py`, `recompilation.py`
and `semantic_diff.py` still hash to the recorded values.

### X2. Deterministic evaluator — PASS WITH HISTORY

Determinism is now a checked property and has its own receipt. It was not always
so; the failure is disclosed rather than hidden.

### X3. Frozen protocol and one-shot holdout — PASS

The Family B fresh-seed holdout was frozen (generator, seed hash, criteria,
code) before running, run once, and has not been re-run. This session verified
its hashes and **deliberately did not re-execute it**.

### X4. Superseded results preserved — PASS

Retained and pinned by hash from superseding receipts. The ledger is complete as
of this date.

### X5. Environment — OPEN / MITIGATED, severity medium

Receipts record Python version, platform and logical CPU count, and the
manifest now records a digest of the installed package set. **That digest is
not a lockfile and must not be described as one.** It is taken at
*manifest-build* time, not at experiment time, so it does not establish what was
installed when any given measurement ran. Calling it historical environment
provenance would be a false claim about a real artifact, which is worse than
having nothing.

Timings remain from a single uninstrumented desktop host under unknown
background load — in at least one case with two other jobs running concurrently.
Wall-clock figures are order-of-magnitude, not benchmarks.

*Stays open.* Closing it requires an experiment-time immutable environment lock
captured per run, which does not exist.

### X6. Seeds — PASS

Seeds are recorded, and the Family B holdout seed was hash-committed before
disclosure.

### X7. Exclusions — CLOSED BY CHANGE

W6 acquisition records per-title exclusion reasons; A9 records 51 of 800 pages
without an official score. The gap was that no single document enumerated the
exclusion rules across experiments.

`docs/repro/EXCLUSION_RULES_2026-08-19.md` now does, and the execution index
pins it by digest, so the enumeration cannot drift away from the package
without the index hash changing.

*Residual, not a finding:* the document enumerates rules; it does not re-derive
per-experiment exclusion counts from the raw data. A reviewer wanting those
reads them from each receipt.

### X8. Exact commands — CLOSED, BUT NOT AS "HISTORY RECOVERED"

`docs/repro/EXECUTION_INDEX_2026-08-19.json` now separates two things that were
previously conflated, and the distinction is the whole point:

- **Current reproduction route.** For every experiment, the runnable scripts and
  a command template. Templates are labelled `TEMPLATE_ONLY` and carry a warning
  that they are derived from current scripts and are *not evidence of the
  historical invocation*.
- **Historical exact invocation.** Recovered **only** where a repository
  artifact actually records it. Across 18 experiments this is true for exactly
  **one** (`H1-G-ATOMIC-PROMOTION-01`, whose receipt stores its argv, pinned by
  receipt digest), plus three experiments with exact commands recorded for this
  session's runs. The other 17 are marked
  `NOT_RECOVERABLE_FROM_REPOSITORY`.

**No command is reconstructed from argparse or help text and presented as
history.** The tool carries that as an explicit warning field.

*Closed as:* "current reproduction route and historical invocation recovery
status are separated and packaged." **Not** as "the exact historical commands
were recovered" — they largely were not, and the index says so in a countable
field rather than in prose.

---

## Open findings, consolidated

| id | severity | finding |
|---|---|---|
| R5 | **high** | one-source retrospective real-corpus regression exists; broad cross-source/layout/language external validity remains untested |
| P5 | high (mitigated) | Claim A3 has no empirical arm; flagged to counsel |
| P7 | medium | Atomic activation evidenced by contract audit only; crash/distributed failure not demonstrated |
| P2 | medium | Authority elements may read as business rules in some jurisdictions |
| P4 | medium | real-corpus equivalence now exists for retrospective English Wikipedia only; arbitrary/cross-source generalization remains open |
| X5 | medium | Package digest is manifest-time, not experiment-time; single-host timings |
| R9 | low-medium | Gate-check ordering recited as a limitation but unmeasured; per-filter governance ablations absent |
| R3 | low | A9 split not externally audited |

**No finding of severity high was closed by explanation.** R5 and P5 are
reported as limitations in the artifacts themselves, which is the only honest
disposition available without new evidence.

---

## P8 — a claim sentence outran the experiment behind it (self-found, corrected)

**Severity: high, because it is the failure mode this programme is built to
prevent and it still happened.**

`H1-I` measured that the promotion gate's acceptance conjunction is invariant to
evaluation order (0 divergences / 144 evaluations, positive control separating
on 12 of 24 orders). The sentence written into claim B1 element 7 immediately
afterwards said the four checks are **"mutually independent, each evaluated
against the candidate state rather than another check's output"**.

That does not follow. **Order-invariance does not entail independence** — a
conjunction of coupled predicates is still commutative, so 144 non-divergences
cannot distinguish the two. The experiment was run correctly and the protocol
was honoured; the defect was entirely in the prose written after the result.

**A static audit found the coupling that refutes it.** In the no-oracle branch
(`promotion_gate.py:317-330`) the INTEGRITY check records PASS with the detail
that integrity *"rests on the input fingerprints checked in the next step"*, and
the source comment states that step "may not be skipped". No data flows between
the two checks, but check 3's safety argument is discharged by check 4.

**Corrected.** Element 7 now recites *a sequence of candidate-state predicates
whose conjunctive acceptance result is invariant to evaluation order*. Mutual
independence is listed under "deliberately not claimed", and
`forbidden_wording` in the registry now blocks the phrase.

**What an examiner or reviewer should take from this:** the gap between a
measurement and the sentence that reports it is a separate attack surface from
the measurement itself, and it is not covered by protocol freezing, fidelity
gates or positive controls — all three were satisfied here. The mitigation is
that every claim's permitted wording is now checked against what its receipt
actually asserts, not against what the experiment was about.

---

## P9 — the identity-scalability story now has a negative result, and it must stay in

An earlier draft of this programme could have been read as "BLOCKED is fast, we
just need to fix the residual ties." `H1-L` tested that optimism and it did not
survive.

A matcher was built that preserves the **full** LEGACY contract — classification,
logical id, candidate attribution, runner-up, downstream impact. It is exact:
0 divergences over 50 comparisons, with all three mutants separating. It is also
**0.35–0.48x the speed of the dense baseline**, and computes *more* work, not less.

The cause is structural. Preserving the runner-up requires retaining
`min(M, N+1)` columns per row, because up to `N-1` columns can be taken by other
rows. For a square window — the common case — `N+1 > M`, so **no pruning is
admissible at all.**

**Why a reviewer should care:** the honest claim is not "identity matching scales"
but "the exclusivity semantics that make identity trustworthy are what make it
expensive, and we measured the trade rather than assuming it away." Any figure or
sentence that implies a solved scalability story is now contradicted by our own
receipt.

## P10 — W6's freeze and W6's recoverability are in tension, by construction

The acquisition script self-checks its own sha256 against the frozen title
manifest and exits if it moved. That is exactly the property that makes the
6,987-title cohort trustworthy — nobody can quietly re-tune acquisition after
seeing outcomes.

It also means **a safe resume cannot be implemented without breaking the freeze.**
Skip-on-exists, integrity validation and atomic writes all require editing the
script whose hash is pinned.

The static audit found the script overwrites unconditionally, writes
non-atomically, keeps no checkpoint, and leaves undefined state after an
exception. So resuming into `corpus-v5` would risk the one pair it already holds.

**Resolution chosen:** acquire into a fresh `corpus-v6` under the *same* frozen
manifest and cutoffs, retaining `corpus-v5`'s single pair as failed-run evidence
and explicitly **not** copying it forward — copying it would make the cohort
depend on where the crash happened.

**What a reviewer should take from this:** immutability and recoverability are
not free together. We chose immutability and paid for it with a full
re-acquisition, and we are saying so rather than presenting a resumable pipeline
we do not have.

## P11 — A12's blocker is external to this environment, not merely unfinished

Restated precisely after a $0 audit: there is **no container runtime on this
host** (docker, podman, buildah, nerdctl all absent), and **no build recipe exists
for either Apache-2.0 A12 candidate**. A digest is the hash of pushed content and
cannot be authored.

Previous reclassifications moved A12 from "licence" to "internal runtime". This
moves it once more, to **external**: the work cannot be done here at all.
`gpu_spend_authorized` remains false and spend remains $0.

---

## P12 — the exactness result carries a disclosed protocol deviation, and a reviewer may discount it

`H1-L`'s protocol froze the corpus and forbade extending it after results were
seen. **The corpus was extended.** It had omitted `source_lineage`, so every pair
abstained on a missing critical signal and no row ever reached MATCHED, the
review band or the tie guard; two of three mutants were unfalsifiable and the run
was VOID under the protocol's own §6.

The repair added lineage and two band-covering cases. Divergences were 0 before
and after, so the correctness result did not move — but a reviewer who declines
the distinction between *repairing a void instrument* and *tuning a corpus* is
entitled to read the exactness claim as covering only the post-repair corpus.

**We do not argue that reviewer out of it.** The deviation is stated in the
amendment, in the registry limitations and in the ledger, and the void run is
retained. What we would resist is the stronger reading that the result is
worthless: the mutants now separate on 10, 15 and 17 cases respectively, which is
the property that makes any null here citable at all.

**Residual risk accepted:** the H1-E residual 8 cases are still not wired into
this corpus. That gap was declared in the protocol before the run, not discovered
after, and the claim's forbidden-wording list blocks any statement that the
exactness result covers them.

## P13 — "0 complete pairs" corrects a number we published one session earlier

The v5 health check recorded `pairs_materialized: 1`. That counted directories.
The directory lacks the `metadata.json` that acquisition writes last, so by the
completion semantics we then measured, it is an **incomplete** pair and
`corpus-v5` holds **zero** complete pairs.

Sequence worth noting, because it is the second correction on the same object:
first a session reported the corpus empty by inspecting a path that does not
exist; then a health check found one directory and called it a pair; then a
fixture established what "complete" means and the count went to zero.

Neither earlier receipt was edited. The health check is refined by a separate
receipt that says exactly what it refines and why.

**What a reviewer should take from this:** every W6 count we have published has
been wrong once. The endpoint status — NOT RUN — has never moved, which is the
only thing that would have affected a scientific conclusion.

---

## P14 — the specification asserted two things our own experiments disprove

Found by sweeping the specification against the current evidence rather than
against the draft it was written from. Both are **enablement-relevant**, which is
what makes them worse than prose errors.

**(a) "The sparse bipartite graph is decomposed into connected components and the
assignment is run per component, which is exact."** Withdrawn. It is exact only
with respect to the already-restricted candidate graph, not the unrestricted
problem. `H1-E` measured 8 residual divergences; `H1-E2` found all 8
path-dependent into the next revision. The embodiment is shadow-only under a
promotion veto, and the specification now discloses it as a **performance variant
that is not outcome-equivalent**.

An examiner reading the original sentence would have been told an optimisation
was exact when its own inventor's experiment says otherwise. That is the single
most damaging kind of error a specification can contain, and it survived four
sessions of review because nobody re-read the specification *against the
results*.

**(b) "The order matters: an integrity check that ran before completeness could
pass on a state that is internally consistent and incomplete."** Withdrawn.
`H1-I` measured 0 verdict changes across all 24 orderings on a separating
harness. The specification now states what the ordering actually buys —
diagnostic attribution, and the `NOT_REACHED` distinction that stops a
short-circuited run being read as verified.

**Process finding, which is the transferable part.** Claim text was narrowed
promptly when H1-I and H1-K landed; the specification was not swept at the same
time. A narrowing that updates the claims and leaves the specification asserting
the old, stronger property creates exactly the written-description mismatch a
hostile examiner looks for. **Any future narrowing must sweep claims,
specification, manuscript and figures in the same pass** — the figure caption
fixed in this session (Figure 3) was the same defect in a third place.

---

## P15 — we described a facet as preserved that nothing had measured

Found in a **second red-team pass over our own current state**, after the first
pass had already been declared complete.

The frozen semantic contract for the exact matcher lists next-revision lineage as
a facet of the observable footprint. The exactness harness stops at revision 1
and never computes it. A summary table nonetheless described future-path
exactness as "preserved on tested corpus".

**The wording turned out to be correct** — `run_future_path.py` now measures it
and finds 0 revision-2 divergences over 19 cases with 0 differing carry-forward
identifiers. **That is not a defence.** It was unsupported when written, and a
claim that happens to be true is still an overclaim if nothing established it.

**The generalisable failure.** It is the same shape as P14 and as the H1-I
"mutually independent" wording: a sentence written from what the mechanism
*should* do rather than from what a receipt *says*. Three occurrences now, in
three different documents, over four sessions — the pattern is not incidental.

**Mitigations now in place:**

- an audit binding load-bearing numbers in the prose to live receipts, which
  caught a stale receipt count within minutes of being written;
- a cross-document consistency audit over forbidden wording, evidence paths and
  status vocabulary;
- an explicit facet-by-facet table (H1-L Amendment 2) recording which contract
  facets are measured and which are not.

**Residual, closed rather than argued.** Amendment 2 listed three further
unmeasured facets — the serialized semantic record, `changed_logical_ids`, and
the selective rebuild set — and argued two of them were "strongly implied" by
facets that had been measured. That is the same reasoning this finding
penalises, so it was not relied on: `run_full_contract.py` measures all three and
reports `FULL_CONTRACT_EXACT`, 0 divergences across 19 cases. All twelve contract
facets are now compared directly, and the claim's scope says so.

---

## P16 — a failure's *cause* was inferred from its signature, and the inference was wrong

The same defect shape as P14/P15, applied to a diagnosis rather than a claim.

W6's v5 acquisition left one pair directory holding two wikitext files, no
`metadata.json`, and no completion sidecar. That signature was read as a killed
worker, and the static resume audit wrote it down as fact:

> "This matches the observed v5 death: 1 pair on disk, no completion sidecar."

**It was never verified.** The cause propagated into four documents — the
claim-evidence registry, the generated matrix, Table 5 and the program status —
as though it had been established.

**What actually happened.** The v6 run reproduced the signature *byte for byte*
(identical sha256 on both files, same directory name) and this time produced a
traceback: a deterministic `ValueError` at `acquire_w6_v3.py:376`, computing
`before_path.relative_to(EXP)`. `EXP` is absolute; the corpus path came from
`--corpus`, which both runs were given as repository-relative. The expression
raises on the first eligible page — after both wikitext files are written and
before `metadata.json`. Every part of the observed signature is explained by it.

**Why this one was expensive.** "The worker died" is an explanation that closes
an investigation: it implies bad luck, a long-running process, an unreliable
network, and it makes the right response "try again more carefully". Two runs
were spent that way, the second costing about five and a half hours of
rate-limited fetching. A defect explanation would have cost one reading of the
traceback — which no run had produced, because the first run was diagnosed
without one.

**Two things the correction did *not* require.** The sealed script is unchanged,
so the manifest's `acquisition_script_sha256` pin and the wrapper's frozen-bytes
check both still hold: the defect lives at the call site, and a probe using the
sealed module's own `page_dir` and `EXP` confirms an absolute `--corpus` makes
the same expression succeed. Neither failed corpus was deleted and neither
receipt was edited; the earlier audit is refined by a new receipt, not rewritten.
Its other eleven checks stand — including `state_after_exception: UNDEFINED`,
which described this failure mode correctly while the diagnosis beside it named
the wrong cause.

**What was done before retrying.** No W6 run had ever executed past that first
page, so the entire post-fetch half of the acquisition was untested. Rather than
spend another five hours discovering a second defect, the sealed `acquire()` was
run offline with only its fetch function substituted: 24 complete pairs, 0
incomplete, both receipts written, availability rule evaluated. That is a harness
control and nothing more — the synthetic pages were built to satisfy the
thresholds, so its `availability_reached` says nothing about Wikipedia.

**Standing consequence.** A cause recorded without a traceback, a log line or a
reproduction is a hypothesis, and belongs in a receipt labelled as one. Four
occurrences of this pattern are now recorded (P14, the H1-I wording, P15, P16);
the first three were claims about our own mechanisms, and this one shows the same
habit operating on our own failures.


---

## P17 — the sentence closing P15 was itself unsupported, and it enumerated eleven while claiming twelve

The correction to P15 said all twelve facets of the frozen matching contract were
compared and exact. **The list beside it named eleven.**

The missing one is `assigned_column` — "which previous unit was paired" — and it
is the single per-row facet the exactness comparison function never read. It had
been described as *indirectly implied* by `logical_id` and `candidates`.

**The indirect argument does not hold**, and not merely for want of evidence.
`logical_id` is read from the matched *partner*, so two distinct prior units
carrying the same identifier — a duplicate, a re-seed, a carry-forward collision
— are indistinguishable through it. Two policies could pair a row with different
columns, agree on every facet the comparison did read, and still have paired
different units.

**Measured rather than argued.** `assign_one_to_one` never returns its assignment
map and `identity.py` is Protected Core, so it was not edited. The resolver was
subclassed and its two entry points observed — `decide_pair(partner=…)` yields
the column by object identity, `resolve(unit, [])` marks an unassigned row — and
both policies call exactly those functions, so the column read is the one the
shipped code selected. Result: **0 divergences over 19 cases**.

**Liveness recorded with the null**, because two empty observation lists compare
equal and a probe that never fired would produce this same zero — the failure
that already voided an experiment here. 72 observations, 67 assigned columns, 5
unassigned rows.

**Disclosed limit.** The corpus carries no duplicate prior identifiers, so it
does not exercise the case that makes the indirect argument fail. The facet stays
measured directly rather than inferred.

**Why this is the sharpest instance of the pattern.** P14, the H1-I wording and
P15 were unsupported statements about mechanisms. This one is an unsupported
statement *inside the correction to P15*, written while explicitly rejecting
"strongly implied" reasoning — and a reader could have caught it by counting the
list. Four occurrences; the newest was produced by the fix for the third.

---

## P18 — "repository green" was asserted from a subset

The program status recorded **"repository green | 696 passed, 25 skipped"**.

That figure is `tests/unit` alone. A full-repository run is **2,733 passed, 25
failed, 31 skipped** — the failures in `services/api`, in areas this evidence
programme never touched, against a working tree that carried uncommitted
modifications to `services/` and `packages/` before this session began.

**What is and is not being claimed here.** The failures were not introduced by
this session's work, which wrote only under `docs/`, `tools/` and
`research/experiments/`. That is a statement about scope, not an investigation:
their cause has not been diagnosed, and calling them pre-existing without one
would be the same inference-as-fact habit recorded in P16.

**What was wrong was the label.** "Repository green" names a scope the command
never had. It now reads as the subset it is, and the full-suite state is recorded
beside it.

**One real defect did surface from running the wider suite** — a receipt written
this session declared a `supersedes` pointer with a directory-prefixed filename
and no pinned hash, which the repository's own superseded-receipt contract
rejects: a retraction bound to a filename alone stops applying the moment the
target is regenerated. Fixed by pinning the superseded bytes. The narrower
command would never have run that contract.

---

## P19 — two withdrawn limitations survived in five places, in documents a sweep had already declared clean

Two limitations were withdrawn on evidence, and both left residue.

**"Atomically"** was struck from claim element 9 because the evidence is a
contract audit of the publish path, not crash atomicity. The reviewer red team
recorded that "the word is gone from the claim, the specification section
heading, and the manuscript abstract." That was true of those three surfaces and
of nothing else. It survived in:

- the claim set's own Family B **section heading** — "verified atomic
  world-state activation", directly above the claim that no longer says it;
- the specification **Summary** — "activation is atomic and conditional on that
  gate", stated unqualified, more than three hundred lines before the paragraph
  that carefully narrows the word;
- the manuscript body — "Activation is atomic and conditional on all checks."

**"Ordered"** was withdrawn after the permutation study found 0 verdict
divergences over 144 evaluations, and the claim was narrowed to an order-invariant
conjunction. It survived in:

- the specification Summary — "verified by an **ordered** gate";
- the manuscript's **contribution 2** — "An ordered pre-activation verification
  gate", i.e. the withdrawn limitation recited as a contribution;
- the manuscript's §2.3 — "an ordered gate checks that…".

**Why the existing tooling did not catch it.** The cross-document consistency
audit checks a registry of *forbidden wording* per claim, and neither word was on
a forbidden list — the amendment notes recorded the change in prose without
adding the withdrawn term to the machine-checked list. The audit was green and
correct about what it checks. It was never asked about these two words.

**The pattern, again.** This is P14's shape a second time: a claim narrowed on
evidence while the surrounding documents keep the stronger word, and — worse — a
sweep recorded as complete that covered three surfaces and named itself general.
The sentence "claims, specification, manuscript and figures are now swept
together" was itself an inference from having done a sweep, not a measurement of
its coverage.

**Closed by:** all five occurrences rewritten to the measured formulation —
single-state-transition activation, and a conjunction whose acceptance result is
invariant to evaluation order. The register detector added this session
(`audit_inference_vs_measurement.py`) is a different instrument and would not
have caught these either; the correct fix is to add withdrawn terms to the
forbidden-wording registry at the moment of withdrawal, which is now the standing
rule.

---

## P20 — every test figure this programme published described the wrong environment

The full suite showed 24 failures in `services/api`. The available shortcuts were
all wrong: "probably pre-existing", "unrelated to this work", "known noise". Each
would have closed the investigation the way "the worker died" closed the last one
(P16).

**What it actually was.** The document-parsing sandbox launches its child with
`-I`. That flag implies `-s`, which excludes user site-packages. Under the global
interpreter this repository's dependencies live there, so the child could not
import them, exited non-zero, and the worker raised `PARSER_PROCESS_CRASH` —
after which every downstream assertion saw an analysis task still `queued`.

**Isolated causally rather than inferred**, by separating `-s` from the rest of
`-I`:

| command | result |
|---|---|
| `python -E -P -m akc_worker_document.sandbox_runner` | imports cleanly |
| `python -E -P -s -m akc_worker_document.sandbox_runner` | `ModuleNotFoundError` |
| `.venv python -I -c "import akc_worker_document.sandbox_runner"` | **IMPORT OK** |

**`-I` was not relaxed and must not be.** It is the sandbox boundary for hostile
documents, beside a sanitized environment, discarded streams and an optional
bubblewrap jail. Weakening a security invariant to turn a suite green is the
trade this repository exists to refuse.

**The finding is not the failures. It is that we never recorded the
interpreter.** "697 passed", "2,733 passed / 25 failed", "repository green" — all
of them were produced by an interpreter that is not this project's environment,
and none of them said so. A test result is a statement about an environment as
much as about a codebase, and ours omitted half the statement. That is P18's
shape at one level up: P18 was a result reported under a wider *scope* than it
had, and this is a result reported for a different *environment* than it had.

**A second defect surfaced in passing.** The global interpreter carries an
editable path file pointing at a **sibling checkout**
(`…-collection-plane-rehearsal`). Under it, importing the worker resolves to the
other repository; the test process masks this by inserting this repository's
paths first, but a subprocess launched with `-I` has no such insertion and would
execute the other checkout's code. Reported, not repaired — another checkout's
install is the operator's call, and quietly rewriting it is not this
repository's business.

**Closed by:** build status is now emitted by a tool that records the interpreter
and **withholds `repository_green` when it is not the project one** — verified by
running it under the global interpreter and watching it withhold. The readiness
checklist's build row is untickable from a narrower scope, and §6 of the
manuscript states that the interpreter is part of a result.

**Confirmed by re-running, not by argument.** Under the project environment the
full suite is **2,758 passed, 32 skipped, 0 failed**. All 24 failures resolve; 0
persist; 0 new ones appear; **0 remain UNKNOWN**. No test was edited, skipped or
marked xfail, and no sandbox flag was relaxed.

**What this cost, stated plainly.** Two of this programme's headline integrity
numbers were wrong for the whole of its existence, and they were wrong in the
direction of looking better. Nothing detected it until someone ran the wide
command and refused to accept the convenient explanation for what came back.

---

## P21 — an evidence-generating script in the repository could not run at all

Found by widening the lint scope from the paths this session touched to
`research/experiments` as a whole — the same move that found P20, applied to a
different tool.

`research/experiments/H1-IP-HARDENING-01/build_receipt.py` contains JSON literals
where Python literals belong:

    "synthetic_golden_excluded": true,
    "performance_conclusion_allowed": false,

The script raises `NameError` before writing anything. **It has never been able to
produce its receipt in this form.**

**What that means for the receipt on disk.** `receipts/implementation.json` exists
and is dated 2026-08-16, and it does **not** contain the
`a12_primary_input_discovery` block the current script builds. The receipt was
produced by an earlier version of the generator, and the generator in the
repository cannot reproduce it. A receipt whose generator does not run is not
regenerable, and this programme's reproducibility section leans on regenerability.

**Why the fix is two changes, not one.** Correcting the literals makes the script
runnable — and a runnable script here would immediately **overwrite** the existing
receipt with output from different code, destroying a measured artifact. That is
not hypothetical: it is ledger entry 14, where a tooling change overwrote a
readiness receipt while reporting it had written elsewhere.

So the script now also **refuses to overwrite an existing receipt** unless
`--force` is passed deliberately, printing the existing hash and why it stopped.
Verified: it refuses, returns 2, and the receipt is byte-identical afterwards.

**Deliberately not done.** The receipt was not regenerated. Whether to supersede
a 2026-08-16 artifact with output from changed code is a decision that needs a
recorded reason, not a side effect of fixing a typo.

**The generalisable point.** Lint had been run on "the files I touched" for the
whole programme. That scope is a reasonable habit and it is also how a broken
generator sat in the evidence tree indefinitely. Both P20 and P21 came from
widening a command that had always been run narrowly.

---

## P22 — a term-level sweep reported clean while six surfaces asserted withdrawn propositions

P19 recorded that two withdrawn limitations survived in five places. The repair
was `WITHDRAWN_TERMS.yaml` and a term-leakage arm, and it worked: withdrawn-term
leakage has been 0 since. The gap P19 named — *prose is not a detector* — was
only half closed, because a term list is a detector for **words**, and the thing
withdrawn is a **proposition**.

`docs/ip/ASSERTION_REGISTRY.yaml` records assertions under canonical ids that do
not move when the wording does, each with a status (`ACTIVE` / `NARROWED` /
`WITHDRAWN`), an evidence class, the surfaces it may appear on, and — for an
active assertion — the surfaces it **must** appear on. `audit_assertion_registry.py`
compares surface content to assertion status.

**On its first execution it found six leaks, on five surfaces the term-level
audit reported 0/0/0 clean at the same moment:**

| surface | wording | assertion |
|---|---|---|
| `FIGURES` gate node | `Verification gate<br/>ordered, fail-closed` | `ASSERT_GATE_ORDER` |
| `FIGURES` activation node | `Atomic activation → ACTIVE` | `ASSERT_PROMOTION_ATOMICITY` |
| `FIGURES` promotion node | `→ ATOMIC ACTIVATION` | `ASSERT_PROMOTION_ATOMICITY` |
| `FIGURES` drawing rule 2 | `Atomic promotion is drawn as an ordered refusal` | both |
| `TABLES` row 5 | `Atomic promotion contract` | `ASSERT_PROMOTION_ATOMICITY` |
| `CLAIM_SET` element 7 | `verifying … by a sequence of candidate-state predicates whose … result is invariant to evaluation order` | `ASSERT_GATE_ORDER` |

The term audit was not wrong. None of the six is a registered withdrawn *term*,
so it was never asked about them. The last row is the clearest case: element 7
recited the narrowing and the withdrawn form **in one sentence**, and no listed
word appeared anywhere in it.

**The detector was wrong three times before it was right, and each is recorded
because a green from a detector that has been tuned is worth less than its first
red.**

1. **Backtick parity counted across the block.** A ` ```mermaid ` fence opened an
   inline-code span that never closed, so every node label in every diagram read
   as code. Two real leaks went silent. Parity is now counted within the line.
2. **The exemption lexicon was widened until it swallowed real leaks.** Adding
   `never as` and `*not* distributed` took the finding count to 0, and the run
   was briefly clean for the wrong reason. Block-level exemption cannot separate
   a caption **headed** `Atomic promotion` from a row saying `not distributed
   atomicity`, because both blocks contain a negation. Replaced with a
   sentence-local mention/use test: a negated mention is the disclaimer working;
   the label used as the document's own vocabulary is the leak.
3. **A pattern was added in the same change that repaired the text it targets.**
   That pattern had never fired. `historical_wording_control()` now runs the
   registry's live patterns against the wording element 7 actually carried and
   the wording that replaced it, and requires them to separate — 1 finding on the
   superseded text, 0 on the current. Recorded in the receipt, not in a message.

**Withdrawal-propagation control**, which is the thing P19's follow-up asked for:
a synthetic assertion is marked `WITHDRAWN`, its wording is left in a synthetic
surface, and a finding is **required**; the same surface with no such assertion
registered must come back clean; and the sentence recording the prohibition must
not fire. All three separate in the same execution, or the audit reports
`NOT_RUN` and none of its results may be cited.

**Convergence resets to 0 of 2.** Adding a pass changes what "every pass in §2"
denotes, and rounds 1–5 ran an instrument set with no assertion-level detector.
Carrying round 5's clean forward would count a round whose instruments could not
see what the next instrument found immediately — the retrospective-criterion
defect that invalidated round 1, arriving from the other side. Recorded as
protocol amendment 1, **before** the first round that includes pass I.

---

## P23 — claim B6 recited a limitation of an element that no longer exists

`B1-QUERY-FILTER-TO-B10` moved query-time filtering out of independent claim B1
into new dependent claim B10 on §101 grounds, on 2026-08-19. B1 has nine
elements. Claim B6 read:

> The method of B1, wherein the authority and applicability constraint of element
> 10 resolves two conflicting knowledge units…

**There is no element 10.** The constraint B6 depends on left B1 the same day and
is now recited in B10. A dependent claim reciting a limitation absent from its
parent has no antecedent basis, and the defect was a side effect of the move
rather than any decision about B6.

B6 now depends from B10 and is registered as `B6-DEPENDENCY-TO-B10`
(`DEPENDENCY_CHANGED` → `SCOPE_UNCERTAIN`), **counsel-flagged**: B6 now inherits
B10's filter limitations *and* B10's §101 exposure, which is narrower than it was
drafted to be. Whether to keep the dependency or restate the constraint inside B6
so it depends from B1 directly is prosecution strategy and is not decided here.

**Neither existing audit could have found this.** The direction audit checks that
a registered amendment's direction matches its operation; an amendment nobody
wrote is outside it. The cross-document audit checks wording, and a dangling
element number is well-formed wording.

---

## P24 — the amendment register's completeness was never measured, and cannot be

`audit_claim_amendments.py` is clean over seven amendments. Clean over *the
register*, which is a record someone chose to write.

`audit_amendment_coverage.py` measures coverage against the claim inventory
instead, and the result is not clean:

- **Two inventories, not one.** The claim set recites **10** numbered patent
  claims (A1–A3, B1–B10). The claim-evidence matrix carries **21** evidence
  claims in a separate namespace. "All 21 claims" refers to the evidence
  namespace; amendment direction is a property of the patent namespace.
  Reporting one count as coverage of the other overstates both, and this
  programme was one step from doing exactly that.
- **`B-SPECIFICITY-WITHDRAWN` targeted claim `B-ranking`, which does not exist.**
  The ordered authority ranking is recited in B6. A withdrawal that cannot be
  located to a claim cannot be checked against claim text, and its direction
  verdict is about nothing. Resolved by a `claim_aliases` map, so the resolution
  is machine-readable rather than a reader's inference.
- **Six of ten claims are `UNDETERMINED`** — A1, A2, B2, B3, B4, B5. They carry
  no registered amendment, and **`docs/ip/PATENT_CLAIM_SET_v1_2026-08-19.md` is
  git-ignored**, so there is no prior revision to diff. Whether they were never
  amended or amended without a record cannot be distinguished from the
  repository as it stands.

`UNDETERMINED` is reported, never "unamended". Absence of a record is not
evidence of absence, and the same substitution is what P2 named as the root
class.

### The first remedy proposed here was wrong, and recording why matters more than the fix

The first version of this entry said: *track the claim set in git, and every
later amendment falls within reach of a diff.*

**That would have broken a security control to make an audit greener.**
`docs/ip/.gitignore` is a fail-closed allowlist — `*`, then four negations —
under a founder instruction of 2026-08-11. Everything in that directory is
ignored unless argued in, because the risk being managed is the claim chart
nobody thought to add. The claim set is privileged claim-level material. It is
not untracked by oversight; it is untracked **on purpose**, and "so the audit can
diff it" is not an argument that beats that.

The proposal did not read as a violation while being written. It read as
housekeeping — which is exactly how the prohibited move looks from the inside:
a control becomes an obstacle, and the obstacle gets removed to reach a green.
Precedence in this repository is explicit that a red gate is first tested for
whether the thing belongs in a different layer.

**It does.** The chain needs a *digest*, and a digest is not claim text.
`CLAIM_AMENDMENTS.yaml` now pins `claim_set_baseline.sha256`, every later
amendment records `claim_set_sha256_after`, and `audit_amendment_coverage.py`
fails when the file on disk stops matching the last recorded value. The claim set
stays inside the ignore allowlist. The chain reports `INTACT`, and its control
runs the same state function over a matching digest, a differing digest and no
baseline, requiring three distinct states — an intact chain and a chain that
cannot break otherwise print the same word.

**What the chain does not do.** It detects change from the baseline forward. The
six `UNDETERMINED` claims stay `UNDETERMINED`: pinning a baseline is not a
history, and that gap is permanent. **Coverage over the patent namespace remains
bounded by the register's own completeness**, so the amendment audit may not be
described as complete across the claims.

---

## P25 — a narrowing reached the specification and stopped there

Every finding above concerns wording that **survived**. This one concerns wording
that **failed to arrive**, which no leak detector looks for.

`ASSERT_IDENTITY_EQUIVALENCE` was narrowed from "an identical multiset of
outcomes" to "eight path-dependent divergences, each a `NEW`/`AMBIGUOUS`
classification flip that forks lineage at the next revision". The specification
carries the full narrowed form, at length, with the mechanism and the receipt.

The manuscript's limitation 7 said only that the residual tied assignments "are
path-dependent across revisions".

That is the weaker half. *Path-dependent* alone reads as a scheduling artefact.
The substance of the narrowing is that each divergence is a **flip**, that
`AMBIGUOUS` carries no logical identifier, and that the next revision therefore
seeds a fresh identity instead of continuing an existing one — a permanent
lineage fork, not a permutation. A reader of the manuscript alone could not
recover why the shadow matcher is under a promotion veto.

**How it was found, and why not sooner.** The registry's presence check ran for
`ACTIVE` assertions only. A `NARROWED` assertion still stands in its narrower
form, and if that form is nowhere in a document that relies on it, the assertion
was not narrowed — it was lost. Extending the check to `NARROWED` surfaced this
on the first execution.

**A second defect surfaced in the same step.** The presence check searched raw
text, and markdown hard-wraps prose: "invariant to evaluation order" spans three
lines in the claim set, so a literal phrase search reported it **absent** from a
document that recites it in element 7. The check now matches against
whitespace-normalised text. Both directions are controlled — a genuinely absent
form yields exactly one finding, and a line-wrapped present one yields none.

**The generalisable point, and it is the same one as P22 from the other side.**
Propagation was verified in the direction that is easy to instrument: *did the
old wording survive anywhere?* The opposite question — *did the new wording
arrive everywhere?* — has no leak to detect, produces no match to count, and was
not asked for the entire programme.

---

## P26 — the abstract stated half the narrowing, in a sentence containing no withdrawn word

P25 was found by asking *did the new wording arrive?* This was found by asking a
narrower version of the same question: *did all of it arrive?*

After P25 repaired limitation 7, the registry's presence check passed — the
manuscript contained "classification flip" somewhere. **Presence anywhere in a
file satisfies presence.** The abstract, which is the most-read surface in the
package, still read:

> …but eight residual tied assignments were path-dependent across a later
> revision, so that faster matcher was not promoted.

Every word of that is true. It is also the withdrawn harmlessness framing
surviving without any withdrawn term: *path-dependent* alone reads as a
scheduling artefact, and the sentence omits that each divergence is a
`NEW`/`AMBIGUOUS` flip, that `AMBIGUOUS` carries no logical identifier, and that
the next revision therefore seeds a fresh identity — a permanent lineage fork.

`partial_forms` in the registry names, per assertion, a wording that states part
of it and the completion required in the same block. Four sites failed:

| surface | line | statement |
|---|---|---|
| `manuscript` | 54 | abstract |
| `claim_set` | 298 | H1-E2 promotion-veto note |
| `tables` | 28 | row 7, dense vs candidate-indexed |
| `tables` | 123 | tie guard / critical-signal abstention |

All four now carry the flip and the fork. The control uses the abstract's own
before and after text: 1 finding on the superseded sentence, 0 on its
replacement.

### A fourth detector defect, found by the finding it hid

`tables:123` did **not** fire on the first run. A markdown table is one paragraph
to a blank-line splitter, so the whole table was one block — and row 124 says
"may not be recited as independently necessary", which the exemption lexicon
matched. **One row's disclaimer exempted every other row in the same table**,
including a partial statement six rows away.

Table rows are now scoped as independent blocks, because they are independent
statements. The same coarseness applied to every check in this file: the leak
check, the mention/use test and the identifier test were all reading a whole
table as one context.

**Four detector defects are now recorded in this file** — mermaid-fence backtick
parity (P22), an exemption widened until the count reached zero (P22), a pattern
added in the same change as its fix (P22), and table-wide exemption scope
(here). Every one was found by treating a green as a question rather than an
answer, and three of the four were found within minutes of the detector first
reporting clean.

---

## P27 — evidence was bound to claim families, and an examiner objects to elements

`claim-evidence-matrix.yaml` binds each evidence claim to a patent *family* in a
free-text `patent` field. That is the right granularity for a paper. It is the
wrong one for prosecution: a §112 objection lands on a limitation, and "Family B"
does not say which limitation the evidence reaches.

`build_element_support_matrix.py` parses the claim recitals and each claim's
`**Evidence:**` block and reports support per element. **24 elements across 10
claims:**

| state | count | meaning |
|---|---|---|
| `ELEMENT_BOUND` | 11 | the Evidence block names evidence *for that element* |
| `CLAIM_LEVEL_ONLY` | 10 | evidence named for the claim, not scoped to elements |
| `EMBODIMENT_ONLY` | 2 | "implemented and unit-tested", no measured evidence claim |
| `UNSUPPORTED` | 1 | A3, which is `RESERVED, NOT SUPPORTED` by design |

**No non-reserved element is unevidenced.** The finding is granularity, and it
concentrates where it matters most:

- **A1 — all seven elements** are bound only by one claim-level citation of
  `A9-SELECTIVE-ACCEPTANCE-ASSOCIATION`, whose own status is `CONFIRMATORY` with
  a bootstrap interval containing zero.
- **B1 elements 1, 3 and 4** — the stable logical identifier, the classification
  of the difference into typed change kinds, and the dependency graph typed by
  change kind — are bound only at claim level. Elements 2, 5, 6, 7, 8 and 9 each
  carry a named receipt. **Those three are the elements the independent claim's
  technical character rests on**, and they are the three with the weakest written
  binding.

This is a statement about the **record**, not about the elements. Support may
exist and be unwritten — which is precisely what is worth knowing before a
filing rather than after an office action.

### Four parser defects, all found by reading the findings instead of counting them

The first run reported **13 unsupported elements**. Only one was real.

1. **A bullet wraps.** Reading the Evidence block line by line stranded the
   second identifier of "elements 7, 8, 9: `B-PROMOTION-GATE-STALE-BLOCK`, and
   `B-ATOMIC-PROMOTION-CONTRACT`" as unscoped. Parsed by bullet now.
2. **`AMBIGUOUS` was read as a dangling evidence id.** It is a classification
   value the claim recites in backticks. Evidence and experiment identifiers all
   carry a hyphen; bare uppercase words do not, and the pattern now requires one.
3. **`H1-K`, `H1-L`, `H1-E-IDENTITY-SCALABILITY-01` were read as dangling.** They
   name the experiment namespace — a directory, or a family by prefix — not the
   evidence-claim namespace. Resolved against `research/experiments/` directly.
4. **Claim-level and embodiment evidence were reported as no evidence.** This was
   the worst of the four: it reported seven of A1's elements as unevidenced when
   the claim carries a `CONFIRMATORY` result, and reported A2 and B2 as
   unevidenced when both openly state "implemented and unit-tested" as an
   embodiment-supported dependent claim. **An overstated finding is a defect in
   the same way an understated one is** — it spends the reader's trust and points
   at the wrong thing.

**The generalisable point.** Every detector added in this session reported more
findings on its first run than survived reading them, and every detector reported
fewer than the truth on some later run once a defect was fixed. Neither direction
is safe to accept unread. The count is not the result; the reading is.

---

## P28 — Family A's claims pointed at Family B's specification section

Every A-family element binding named `§4.6 The verification gate` as its written
description. §4.6 describes the **pre-activation gate over a candidate knowledge
state**: changes accounted for, recompilation complete, integrity, no stale
current. Family A's gate is over a **candidate representation of a document**:
two extraction configurations, an agreement signal, a stability signal, an
abstention.

They are different gates over different objects, and the pointer had been wrong
since the bindings file was written. The consequence is a §112(a) written-
description exposure on the independent claim of a whole family: an examiner
following the citation finds a description of something else.

**Why it survived a pass that was looking for exactly this.** Pass K checked
whether each element's *evidence* reached the limitation. It did not check
whether each element's *specification pointer* described the limitation. A
pointer to a real section that says the wrong thing passes an existence check.

**Closed 2026-08-20** by drafting specification §4.10, which describes the
Family A gate at the level the elements recite — including the definition of
"independent" as architecturally distinct configurations rather than statistical
error independence, which the claim set had been careful about and the
specification had never said. All A-family bindings now point there.

**What is not claimed by this repair.** That every remaining specification
pointer in the package is correct. One was checked because a statutory pass
asked the question; a systematic pointer-content audit has not been run and this
finding is the argument for one.

---

## P29 — the specification asserted an ordering property this programme had withdrawn

`ASSERT_GATE_ORDER` was narrowed on 2026-08-19 after H1-I permuted all 24 orders
of the four gate checks over 6 constructed states and found 0 verdict
divergences. The claim was amended, the manuscript was amended, and the assertion
registry recorded the narrowing with its forbidden wording.

Two sentences in the specification survived it:

- §4.6 opened with "Before activation, an **ordered sequence** of checks:";
- §6 stated that the four checks "may be extended but their **order** is
  material."

The second is not a wording leak. It is a plain assertion of the withdrawn
proposition, in the document an examiner reads for written description.

**Why the sweeps missed it.** The term-level sweep looks for phrases like
"ordered gate", "mutually independent", "in a prescribed order". "their order is
material" contains none of them. The assertion-level audit (built for exactly
this class after P22) checks declared surfaces against declared assertions, and
it reported clean — which means the check did not reach this sentence. That is a
gap in the detector, not a clean result, and it is recorded as such.

**Closed 2026-08-20.** §4.6 now recites a conjunction evaluated in the
implementation's sequence and accepted only when all checks pass; §6 now states
that order affects only which failed check is reported. Both cite H1-I.

**Standing consequence.** This is the *third* time a withdrawn proposition has
been found surviving in a document a sweep had declared clean (P19, P22, now
P29). The pattern is that each detector catches the form of the previous leak.
Nothing here establishes that the current detectors catch the next one.

---

## P30 — eight claim limitations recited more than their receipts contained

Pass K reported eight limitations whose recited scope exceeded the evidence
beneath them. This is not a leak or a wording defect; it is the claims having
been drafted from what the system does rather than from what was measured.

They are closed in three distinguishable ways, and the distinction is the whole
content of the finding:

| how | which | what it cost |
|---|---|---|
| recital amended down to the measurement | A1/1, A1/3, B1/1, B1/3, B1/4, B2/1 | **scope** — six removals, each broadening the claim it left |
| evidence produced | A2/1 | one controlled contract audit, `H1-M`, $0 |
| recital removed from the filing core | A1/7 → A5 | the limitation that turned a classifier into a system claim |

**The option not taken, named explicitly.** A1 element 7 recited admission of
accepted representations to a downstream trusted store. The live system has no
such boundary — the acceptance outcome enum has no consumer outside its own
module and unit tests — so the limitation could have been made auditable by
wiring one. That was refused. A mechanism built because a claim needs it is not
evidence about the product, and a reader who discovered the ordering later would
be right to discount everything else in the package.

**The honest accounting.** Eleven of twenty-four registered amendments are
broadenings. The direction of each is derived from its operation by a fixed
table, not asserted by its author, because an earlier pass recorded four
broadenings as narrowings and the mis-accounting hid where support was owed.

---

## P31 — three test failures were recorded and their identities were not

A full-suite run on 2026-08-20 reported `3 failed, 3031 passed, 68 skipped`. The
run used a summary-only traceback setting, so no test name was captured. A
re-run under the same interpreter over the same collection (3,102 items)
reported **3,034 passed, 68 skipped, zero failed**.

**What is recorded: the discrepancy.** Not a cause. The failing test identities
are unrecoverable, and every available explanation — resource contention with a
concurrently running suite, an ordering interaction, a filesystem race — is a
reconstruction from a signature, which is precisely the error P16 recorded.

**What was changed.** Nothing in the product, because nothing was identified. The
reporting invocation used for full-suite runs from here carries `-rf` so a next
occurrence names itself. That is the only defensible action available.

**What must not be said.** That the three failures were fixed, that they were
pre-existing, that they were unrelated, or that they were caused by contention.
None of those is established, and the last one is the tempting one.

---

## P32 — a withdrawn assertion was alive in a registry field no surface exposed

The claim-evidence registry carries a `paper_section` label on every row. Three
of them read `atomic world-state promotion` and `Atomic Promotion / Gate
composition`.

`ASSERT_PROMOTION_ATOMICITY` was narrowed on 2026-08-19 — "atomic" invites crash
atomicity, partial-failure recovery and multi-node consensus, none of which is
demonstrated — and its forbidden-wording pattern matches
`atomic(?:ally|ity)?[ -]+(?:promot|publish|activat|world|transition)`. The labels
matched it exactly.

**The detector had never seen them.** The assertion audit scans *surfaces*: the
claim set, the specification, the manuscript, the figures and the tables. A label
inside the registry that no surface printed was not on any of those, so it
reported clean for as long as the label stayed unprinted.

It surfaced the moment Appendix A stopped being a pointer. Expanding it into an
evidence index rendered `paper_section` into the manuscript, and the audit fired
on the same run — which is the mechanism working, but only because a document
happened to start quoting a field that had been sitting outside the scanned set.

**Closed 2026-08-20.** The labels are now `single-event world-state activation`
and `Single-event activation / Gate composition`, matching the amended claim
language. The matrix regenerated and the assertion audit is CLEAN.

**The finding that outlives the repair.** This is the fourth incident in the same
family (P19, P22, P29, P32), and the pattern is now explicit enough to state:
each detector scans the places the *previous* leak was found. The registries feed
the surfaces, and only the surfaces are scanned. Every generated document is a
potential promotion of an unscanned field into a scanned one, and there is no
guard that notices when the set of rendered fields grows.

**Not claimed:** that the registries are now clean. One field was checked because
a document started printing it. `evidence_note`, `permitted_wording`, `scope`,
`title` and the binding files' `limitation` and `unsupported_breadth` fields are
all registry prose that a future generated document could render, and none has
been swept against the assertion registry.

---

## P33 — the hand-over package's hash manifest verified nothing

`HASH_MANIFEST.sha256` is the file a recipient uses to establish that the package
they hold is the package that was built. The first three builds wrote it with
`Path.write_text`, which on Windows translates every newline to CRLF.

`sha256sum -c` reads each line as `<digest>  <path>` and takes everything after
the two spaces as the filename. With a trailing carriage return, every filename
became `evidence/CAMPAIGN_RESULTS.md\r` — a file that does not exist. The
verification result was **0 of 44 lines OK**, reported as 44 separate
"FAILED open or read" errors.

**The failure mode is the dangerous kind.** The manifest looked complete: 44
correct digests over 44 real files, every line well formed to a human eye. It was
unusable by the standard tool, and a recipient running the obvious command would
have concluded the package was corrupt rather than that the manifest was
malformed.

**Found by running the verification rather than by reading the code.** The
builder reported "hashed: 44 files" and exited zero, which is exactly what it
would report if the manifest were perfect. Nothing about the generator's output
distinguished the two states.

**Closed 2026-08-20** in two parts, and the second matters more than the first:

1. the manifest is written through `open(..., newline="")`, so no translation
   occurs;
2. **the builder now verifies the manifest it just wrote** — re-reads every line,
   re-hashes every named file, and raises if any line does not verify. External
   confirmation: `sha256sum -c` now reports 44 of 44 OK.

**The general lesson, which this programme keeps relearning.** A generator that
reports what it *intended* to write is not evidence about what it wrote. This is
the same shape as the guards that could not fire (P17, P21) and the receipt that
recorded a control run as a repository verdict (P31's neighbour): the output was
self-consistent and described something other than reality. The only reliable
correction is to make the producer consume its own product in the same execution.

---

## P34 — four rendering defects that every producer reported as success

The package went from "figures are specified" to "figures are rendered, the
documents are built, and the archive is testable". Four defects were found in
that work, and the thing they have in common is more useful than any of them
individually: **in all four cases the tool that produced the artifact reported
success, and the defect was only visible to a second program that opened the
file.**

**1. Every tall figure's PDF was three pages.** `mermaid-cli` places a diagram
on a fixed page and paginates what does not fit. Four of the eight paper figures
and five of the six drawing sheets were silently split, and a split figure in a
submission arrives cropped. The renderer exited zero on all of them. Closed with
`--pdfFit`, and the page count is now asserted per figure: exactly one page, read
back out of the file.

**2. Every image overran the right margin by 12 points.** The image width was
computed from the page's margin box, and reportlab's frame adds 6 pt of padding
inside each margin. Twelve points is small enough to look deliberate and large
enough to be a defect in a camera-ready copy. Found by checking each image's
bounding box against the page rather than by looking at a page.

**3. Every rendered SVG was fluid.** `mermaid-cli` emits `width="100%"` and puts
the real dimensions only in the `viewBox`. That is correct for a web page and
wrong for an asset that goes to a typesetter, a reviewer's viewer and a print
pipeline, each of which would size it differently. The vectors now carry an
intrinsic width and height taken from their own `viewBox`.

**4. The raster resolution was a claim, not a measurement.** "300 dpi" was the
scale flag passed to the renderer. The renderer clamps its viewport, so the wide
figures came out at 129–208 dpi while reporting the same flag. The resolution is
now computed from the raster's pixel width against the vector's width in inches,
written into the file's metadata, and re-read by the checker; a figure below the
floor is re-rendered with the scale corrected by its own shortfall.

**A fifth, found by looking rather than by checking.** Table cells were breaking
words mid-token — `n_repetitions` set as `n_repe` / `titions` — because column
widths were proportional to content length with no floor at the longest word.
That one had no detector and was caught by rasterising a page and reading it.
The column floor is now the widest word in the column, measured in the font it
is drawn in. **The lesson is not that the check was missing; it is that a check
written after a visual read is a different and narrower thing than the visual
read.**

**What was built as a result.** Three checkers that read files rather than ask
producers: `tools/release/verify_figures.py` (asset presence, one page per PDF,
measured dpi, monochrome on patent sheets, source-to-render label
correspondence, forbidden wording in rendered text),
`tools/release/verify_pdfs.py` (glyph coverage against the embedded fonts' cmaps,
text and image boxes inside the frame, no image over text, figure and table
references resolving, W6 boundary intact), and
`tools/release/selftest_submission_package.py` (eleven package checks, each with
a control that mutates a copy of the package and confirms the check fires).

**One check was wrong twice before it was right, and both errors are worth
recording.** The monochrome check first reported `#552222` on every drawing
sheet — dead CSS in mermaid's stylesheet for an `.error-icon` class no diagram
contains. Flagging it would have trained the reader to ignore the check. It now
counts a colour only if something in the document wears it. Then the
withdrawn-assertion check fired 60 times on the evidence matrix, the amendment
log and the experiment identifiers that *record* each withdrawal. Both were the
same mistake: **a second detector with looser semantics than the calibrated one
does not add safety, it adds noise.** The check now reads its terms from the
withdrawn-term registry that ships in the package and applies
`audit_cross_document_consistency.py`'s own exemption rule, scoped to the same
surfaces that audit scans — with a control confirming that the exemption still
exempts a correction note, because an exemption that widens silently reports the
same zero as a clean corpus.

**Not claimed:** that the rendered assets are correct diagrams. The checks
establish that every label in a source appears in its rendering, that nothing is
cropped, over-drawn or below resolution, and that the sheets are line art. Nobody
has looked at all fourteen and confirmed they say what the specifications mean
them to say. That reading is part of Pass A.

---
---

## Part 4 — hostile paper reviewer, 2026-08-20 pass

Eleven attacks, each answered from the package rather than from intent. Where an
attack lands, the answer says so and names where the concession lives.

### R1. Novelty — "this is make plus dbt plus a bitemporal database"

**Partly conceded, and the concession is in the paper's own §0-equivalent.** Each
component is prior art and is named as such. What is offered as novel is one
composition: a change classification carrying a **structure-only** kind, typed
edges seeded from it, and an activation gate with an **unverifiable** third
state distinct from pass and fail. The evidence that this is not the default
design is that this system shipped the structure-only staleness bug before
fixing it, and the defect is published as §4.4 rather than described as a
hypothetical.

**Where it still lands.** No prior-art search by a professional searcher has been
run. The novelty position is drafting discipline, not a search result, and the
paper says so.

### R2. Benchmark selection — "you chose corpora that flatter you"

**The controlled corpora are adversarial by construction** — 9 topologies
including 64-deep chains, cross-document dependencies and diamonds with
conflicting semantic and structural channels — and the equivalence oracle is an
*independent full rebuild*, not a stored expectation.

**Where it lands.** The natural-revision regression is 28 pairs from one source
family, and they are *every pair already stored*, not a sample drawn for the
test. We claim absence of outcome-dependent selection, which is checkable, and
explicitly not representativeness. Limitation 1 says the controlled corpora still
dominate.

### R3. Threshold provenance — "the 10% tie ceiling was chosen to pass"

**It was chosen and it failed.** The ceiling is pinned in a hashed freeze at
02:50:43Z; the holdout title manifest did not exist until 03:18:39Z and the
question set not until 08:51:48Z. v7 had measured 10.38% — *above* the ceiling —
so the number was set stricter than the observation that motivated it, and v7
would have failed it. The holdout measured 19/166 = 11.45% and the arms did not
run.

**The concession, stated in the paper and not softened:** 10% was a predeclared
operational validity threshold, not a theoretically derived constant. The
protocol contains no derivation and none is invented.

### R4. External validity — "retrospective Wikipedia is not organizational knowledge"

**Conceded.** It is one source family, retrospective, and acquired for a
different purpose. It is not evidence about contracts, policies or filings.
Limitation 1 and §5.0.1 both say so, and the sentence that would have called it
broad external validation is on the forbidden list.

### R5. W6 — "the comparative endpoint failed and you are hiding it"

**It did not fail. It was not measured.** No arm ran, no answer was generated, no
score exists; measured inference cost $0.00. A comparison that ran and came out
flat would be evidence about the system, and we would owe the reader that
number. There is no number, and the six phrasings that would imply one —
including "TAVONEL lost", "TAVONEL tied", "no advantage was found" — are on an
enforced forbidden list swept across the whole submission surface.

**Where it lands, hard.** The cohort is spent. It is development data now, and a
future comparative result needs a fresh untouched cohort at real cost. Nothing in
this programme unblocks it.

### R6. Sparse acceleration — "you buried a negative result"

**It is §4.9 and Table 3, with the number.** The exact certified sparse matcher
preserved the full contract and ran **0.35–0.48×** the dense baseline — slower.
The claim we may not make is that exact sparse acceleration is impossible; what
is established is that *one* certification strategy on *one* corpus removes the
sparsity advantage. The stronger sentence is on the forbidden list.

### R7. Identity path dependence — "your fast matcher rewrites history"

**Which is why it is not in production.** 8 divergences over 33,600 decisions,
each a NEW/AMBIGUOUS classification flip, **8 of 8** path-dependent into the next
revision, where AMBIGUOUS carries no logical identifier and the flip forks
lineage. The policy is shadow-only under a promotion veto, and the patent claim
that describes it (B4) carries the boundary in the claim set beside the claim,
not in a footnote.

### R8. Controlled implementation vs distributed guarantee — "your 'atomic' promotion proves nothing about crashes"

**Agreed, and the word was removed for that reason** on 2026-08-19. The claim
recites a single state-transition event; the receipt carries its own trust
boundary field; the paper's §4.7 states what was not exercised — process crash
mid-transaction, partial database/network/storage failure, multi-node concurrent
publication. The same discipline now applies to §4.10, which is a contract audit
and is labelled one in the figure, the table and the limitation.

### R9. Governance is partially supported — "your filters are decoration"

**Half conceded, from our own ablation.** `B-GOVERNANCE-FILTER-ABLATION` measured
the permission, temporal-validity and applicability filters as **redundant for
the verdict** whenever a compliant alternative exists, and the sole refusal only
when none does. The claim may not be prosecuted as though each filter were
independently necessary, and four ranking elements were **not measurable at all**
by that instrument and are recorded NOT MEASURED rather than "inert".

### R10. Provenance incidents — "your own receipts have defects"

**Four are published rather than repaired in place:** a gate receipt whose
run-class label is wrong (`W6-V8-GATE-01`); an endpoint sealer that silently
under-bound two receipts (`W6-V8-SEAL-01`); an instrumentation receipt whose
intermediate state was edited in place and is **lost**; and an acquisition
attempt that failed on its own invocation. The forbidden phrasings include
"every instrumentation version was preserved" and "fully write-once from first
creation", because neither is true.

**Where it lands.** A reviewer is entitled to weigh a package by the integrity of
its own instrumentation. Three W6 instrumentation defects in one run is not a
good number, and the paper reports it as a number rather than as a narrative.

### R11. Receipt overwrite history — "you have destroyed results"

**Twice, and both are named.** The `--self-test` control run wrote its
zero-scope receipt to the canonical build-status path, destroying two real
full-run snapshots (2026-08-19T23:44Z and 2026-08-20T09:56Z). They survive only
as numbers quoted in an incident record. **Neither is restored and neither is
claimed to be.** The defect is fixed — the control now writes to its own path —
and a regression test asserts the canonical receipt's bytes are unchanged across
a control run.

**Two receipts also do not self-verify** under the manifest's rule, both v8
question sets, from a hashing-convention mismatch rather than tampering. The
generator is frozen and digest-pinned and was not edited to make the number go
away.

---

**No attack above is answered by an argument the package does not contain.** Six
are conceded in whole or in part, and each concession points at the limitation or
the incident record that carries it. A reviewer who reads only the limitations
section will find every one of them there.
