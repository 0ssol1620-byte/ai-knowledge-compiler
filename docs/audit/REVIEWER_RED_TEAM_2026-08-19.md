# Reviewer red team — three independent rejections

**Posture: each reviewer is trying to reject the paper.** No rebuttals are
written. Where a criticism is right, the manuscript is changed; where it is
wrong, the reason is recorded so the same objection is not re-litigated.

Severity: **CRITICAL** (reject), **MAJOR** (major revision), **MINOR**.

---

# Reviewer A — systems and architecture

## A1 · MAJOR — "the contribution is an incremental build system with extra steps"

The paper's own related work concedes that incremental rebuild, typed lineage and
bitemporal filtering are prior art. Strip those and what remains is: infer
identity, then verify before publishing. Neither is novel alone.

**Assessment: the criticism is fair and the paper was not answering it clearly
enough.** The distinguishing fact — that a naive combination *fails*, and we have
our own reproduced defect proving it — was in the failure analysis rather than in
the introduction where the contribution is claimed.

**Change applied:** the introduction now names the three properties that separate
this from a build system (identity is inferred not given; edges are typed by
change kind; abstention is a required outcome) and states the measured failure
that motivates the second.

## A2 · MAJOR — "atomic promotion is oversold"

A systems reviewer reads "atomic" and expects a failure model, a recovery
protocol, and a crash test. There is none.

**Assessment: correct, and this was live in the claim language too.**

**Change applied:** the word is gone from the claim, the specification section
heading, and the manuscript abstract. What is claimed and reported is
single-state-transition activation with no partially-visible state, evidenced by
a contract audit — with the boundary stated in the same breath.

**Correction, third pass.** Those three surfaces were the ones checked, and the
sentence above named them as though they were all of them. The word survived in
three further places — the claim set's own Family B section heading, the
specification Summary, and the manuscript body — for a further session.
Recorded as **P19**, together with the same residue from the withdrawn *ordered*
limitation. Both are now closed, and withdrawn terms are added to the
machine-checked forbidden-wording registry at the moment of withdrawal rather
than described in prose.

## A3 · MINOR — "no comparison against a baseline system"

There is no comparison against another knowledge-compilation system.

**Assessment: correct and not fixable.** No comparable system exists to compare
against, and constructing a strawman would be worse. The paper does not claim
comparative superiority anywhere. **Recorded as a limitation, not fixed.**

---

# Reviewer B — empirical methodology (ML / IR)

## B1 · CRITICAL — "the sample sizes are inflated"

"22 constructed cells repeated 500 times" and "33,600 compared decisions" read as
large-n results. They are not: they are repetitions over a small number of
constructed units, and repetition bounds variance, not scope.

**Assessment: this is the most damaging methodological criticism available**, and
partially correct at the time it was raised.

**Change applied:** every table now carries `n_units` and `n_repetitions` as
**separate columns**, with a stated reading rule that repetitions never extend
scope. The abstract's governance sentence now carries the ablation
qualification. Table 1 marks which rows are constructed and which involve real
documents — only two of thirteen involve real documents.

**Residual, disclosed:** the 33,600 figure remains in the text as a decision
count, because it is the correct denominator for the divergence rate. It is
never presented as a sample size.

## B2 · MAJOR — "the real-corpus result is retrospective and single-family"

28 English Wikipedia revision pairs, all already stored, no fresh holdout. This
cannot support generalisation.

**Assessment: correct, and the paper already says so** — in the abstract, the
results section, the limitations and Table 1. **No change needed**, but recorded
here so a future edit does not weaken any of those four statements.

## B3 · MAJOR — "the null results are not obviously falsifiable"

Several headline results are zeros: 0 verdict divergences, 0 exactness
divergences, 0 stale artifacts. How does the reader know the instrument could
have returned anything else?

**Assessment: correct in general, and this programme has been bitten by it three
times** — a falsification arm that could not falsify, a permutation arm that
could not diverge, and an exactness corpus that could not reach the code paths
under test.

**Change applied:** the failure analysis now states the rule explicitly — a null
is uncitable until a positive control on the same instrument separates — and each
null in the results reports its control (12 of 24 orders; mutants separating on
10, 15 and 17 cases; 80 divergent decisions for the emptied candidate set).

## B4 · MINOR — "p = .032 with an interval containing zero is a weak headline"

**Assessment: correct, and the paper already withdraws the magnitude claim
explicitly.** The association is reported, the effect size is not. **No change.**

## B5 · MAJOR — "selection of the 28 pairs is not described as leakage-free"

**Assessment: partially correct.** The pairs were all already stored, so there was
no selection *for* the result — but the paper should say that rather than leave
it inferable.

**Change applied:** the limitations now state that the corpus is all-stored, so
no selection was made after outcomes were visible, while noting that all-stored is
not the same as randomly sampled.

---

# Reviewer C — reproducibility and scientific claims

## C1 · CRITICAL — "reproducibility is asserted, not demonstrated"

Receipts, hashes and a manifest are described. But can a third party actually
re-run anything?

**Assessment: correct, and the honest answer is mostly no.** Exactly **1 of 23**
experiments has a recoverable original invocation.

**Change applied:** the reproducibility section now states this number plainly,
distinguishes current reproduction *templates* from historical invocation
recovery, and names two artifacts that are unreproducible in principle — a
receipt destroyed by our own tooling, and a partial acquisition directory. Any
version of this section that does not carry those three qualifications is a
regression.

## C2 · MAJOR — "code drift between measurement and publication"

Two receipts pin module hashes that no longer match.

**Assessment: correct, and it is disclosed rather than repaired.** The receipts
were not edited. A drift register classifies each as superseded or
claim-carrying, the claim citing the latter states the drift in its own text, and
the manifest gate fails on *undeclared* drift only.

**No change.** Editing the receipts to remove the mismatch would have been the
wrong repair, and is explicitly forbidden.

## C3 · CRITICAL — "the authors destroyed evidence and the paper mentions it in passing"

**Assessment: the destruction is correctly disclosed; the placement was too
quiet.**

**Change applied:** it is in the failure analysis with both hashes pinned, the
incident document, and the ledger. A reviewer who wants to verify the
regeneration can move the freeze receipt aside and re-run the audit — that
procedure is documented.

## C4 · MAJOR — "a claim was narrowed but the specification kept the old language"

**Assessment: correct — this was found by our own sweep, not by the reviewer, and
it happened twice.**

**Change applied:** claims, specification, manuscript and figures are now swept
together; a mechanical cross-document consistency audit runs over forbidden
wording, evidence-path liveness and status vocabulary; and a numeric audit binds
load-bearing figures in the prose to live receipts. Both are receipts themselves.

**Residual, disclosed:** neither tool checks semantic agreement, which is how the
defect survived. They narrow the manual surface; they do not replace it.

## C5 · MINOR — "the W6 experiment appears in the paper but was never run"

**Assessment: correct that it appears; incorrect that this is a problem.** It is
reported as NOT RUN with its blocker, in the abstract and in Table 5. Reporting a
declared-and-not-run experiment is what stops it from being quietly dropped.

**No change.**

---

---

# Second and third passes — what looping the review actually found

The three reviews above were run, their changes applied, and the package declared
ready. Two further passes were then run against the *corrected* state, on the
principle that a red team which stops at its first clean result has measured its
own patience rather than the work.

## B6 · CRITICAL — "your audit keeps finding defects, so why should I believe this pass is the last one?"

**Assessment: correct, and it is the strongest remaining objection to the paper.**
Pass two found a facet described as preserved that nothing had measured. Pass
three found three more: a failure cause inferred from a disk signature and never
verified, a scope sentence claiming twelve items while enumerating eleven, and a
"repository green" claim that named a subset of the test suite. The discovery
rate did not decline.

**Change applied:** §5.1 now states plainly that convergence has *not* been
demonstrated, accepts the inference that a further pass would likely find more,
and narrows what is claimed to what is actually supported — that every finding is
recorded with the receipt that closed it, and that none was closed by softening
the wording it contradicted.

**Not fixed, because it cannot be:** no amount of self-auditing establishes an
absence of defects. Recorded as a limitation.

## C6 · MAJOR — "a correction that introduces its own overclaim is worse than the original"

The sentence closing the pass-two finding claimed all twelve contract facets were
compared. It listed eleven, and the missing facet was the one the comparison
function never read.

**Assessment: correct.** It was written while explicitly rejecting "strongly
implied" reasoning, and it was checkable by counting.

**Change applied:** the facet was measured directly, by observing the resolver's
own entry points rather than reconstructing the assignment — 0 divergences over
19 cases, with instrument liveness recorded beside the null. The route to the
result is reported in the paper, not just the result.

## C7 · MAJOR — "you report a test suite as green"

**Assessment: correct.** "Repository green, 696 passed" was the unit-test subset;
the full suite is 2,733 passed and 25 failed.

**Change applied:** both scopes are now reported with their commands. The
failures sit in a service area this evidence programme does not touch, and are
reported *without* being characterised as pre-existing — that characterisation
would need an investigation nobody has done, and asserting it would repeat the
exact defect pass three had just caught.

**What the wider command bought immediately:** it caught a receipt written that
same session declaring a retraction pointer with no pinned hash, which the
repository's own superseded-receipt contract rejects. The narrow command never
ran that contract.

---

# Outcome

| reviewer | pass | critical | major | minor | unresolved |
|---|---|---|---|---|---|
| A — systems | 1 | 0 | 2 | 1 | A3, not fixable and disclosed |
| B — methodology | 1 | 1 | 3 | 1 | B1 residual disclosed |
| C — reproducibility | 1 | 2 | 2 | 1 | C1/C2 disclosed, not repairable |
| B — methodology | 2–3 | 1 | 0 | 0 | **B6 unresolvable in principle** |
| C — reproducibility | 2–3 | 0 | 2 | 0 | — |

**No critical finding remains unaddressed by a change or an explicit
disclosure.** Four are unresolvable in principle — no comparable system to
benchmark against, 22 unrecoverable historical invocations, one destroyed
receipt, and the fact that self-auditing cannot establish an absence of defects
— and each is stated in the manuscript rather than managed out of it.

**On the count itself.** Passes two and three were run against a package already
declared ready, and found four more material defects between them. That number
belongs in this table rather than in a footnote: a review whose later passes are
empty has either converged or stopped looking, and this one has not converged.

---

# Reviewer D — skeptical methodology (fourth pass)

Reads only for one thing: places where inference wears the grammar of
measurement, where a design could have been conditioned on its outcome, and where
an interpretation was fixed after the result was seen.

## D1 · CRITICAL — "four of your five exactness nulls rest on one corpus, and two of its cases were added after you saw results"

The exact-matcher story now cites five zeros: the primary exactness run, the
H1-E topology replay, the future-path extension, the full-contract extension, and
the assigned-column extension. Presented in sequence they read as five
independent confirmations.

**They are not.** Three of the extensions import `corpus()` from the primary
harness, so four of the five share one constructed corpus of nineteen cases. Two
of those cases were added *after* the first runs failed to separate — a protocol
deviation the programme discloses, but whose consequence propagates into every
later null that reuses the corpus.

**Assessment: correct, and it is this session's own argument turned on its own
evidence.** The convergence protocol frozen this session says repeating one
detector is not independent evidence. The same reasoning applies to repeating one
corpus, and the paper had not said so.

**Change applied:** the exactness result is now reported as **one measurement
over one corpus, examined along twelve facets** — not as five results. Adding
facets to a comparison can only reveal divergence and never hide it, so the
facet-by-facet extensions genuinely strengthen the conclusion; what they cannot
do is broaden the corpus it holds over, and the paper says which of the two it
is claiming.

**Residual, disclosed:** the fifth zero, the H1-E topology replay, does use a
different generator at a pinned seed and is the only one that is corpus-independent.
It is reported as such rather than being averaged in with the others.

## D2 · MAJOR — "the explanation for the slowdown was constructed after the slowdown"

The `min(M, N+1)` account of why preserving the runner-up defeats sparsity is
elegant, and it was written after the measurement it explains.

**Assessment: partially correct.** The bound is a derivation from the matching
formulation and does not depend on the timing result; but nothing was
pre-registered predicting it, and it is presented in the results narrative where a
reader may take it as a tested hypothesis.

**Change applied:** it is labelled as a post-hoc structural account, and the
prohibition already in the tables — that impossibility of exact acceleration is
**not** established — is restated beside it.

## D3 · MAJOR — "you report a test suite without reporting the environment"

**Assessment: correct, and the omission was concealing 24 failures with a
non-product cause.** Addressed in §6 and in the build-status tooling, which now
records the interpreter and withholds *green* when it is not the project one.
