# Compiling organizational knowledge: failure-driven representation repair, migration closure, and a frozen frame that stopped a successor study

**INTERNAL DRAFT — NOT FOR RELEASE.** IP gate CLOSED. No arXiv, no public
repository, no dataset, no demo. Every numbered claim in this document is bound
to a row of `paper/CLAIM_MATRIX.yaml` and through it to a sealed receipt. If a
sentence here says more than its row permits, the row is right and the sentence
is wrong.

---

## Abstract

We describe an evaluation programme for a knowledge compiler: a system that
turns document revisions into versioned artifacts a retrieval layer can serve.
The programme was built around a single discipline — every protocol frozen
before the data it scores exists, every result bound to an immutable receipt,
every threshold declared rather than measured — and the most useful thing it
produced is a list of things that turn out not to follow from each other.

Selective recompilation agreed with full recomputation on 34 development pairs
with no stale artifact escaping. On 43 pairs where the two agreed exactly, 26
were simultaneously source-coverage incomplete. Those two sentences are the
shape of the whole programme: **agreement between two build paths is not
evidence about the source they both read.**

Two later safety studies, designed as held-out and demoted to development
diagnostics by their own hygiene audit, both FAIL: a source front-end that
silently drops facts inside scopes it declares complete, and a second
implementation that diverges from the production path on 30.5% of pairs. Four of
those divergences were then confirmed as genuine selective stale escapes against
the production path alone — none of them caused by a missed substantive edit.

We then attempted a confirmatory model study on an exact-value question
endpoint. Three preregistered CPU preflights, each frozen before its cohort
existed, refused to start it: a cohort selected for semantic change could not
pose an exact-value question (274 of 296); sources selected for value-bearing
structure yielded no moved value under blind pair sampling (0 of 174); and a
complete walk of 2,271 fresh lineages searching revision history directly found
only three eligible cases. The study was not run. The programme spent 0 GPU
seconds and $0 of an
approved $40.

After a sequence of identity/change and uncertainty-quarantine instrument
failures, a fresh prospectively frozen migration-closure study evaluated 223
pairs from three source families. All eight declared invariants were exercised
and met with zero recorded violations. The cohort included six
resolver-established matches with differing revision-local raw identifiers and
six locally `NEW` decisions overridden by the independent quarantine surface.
This closes the predeclared migration contract on that cohort; it is not a
universal correctness result (C-34).

A later held-out source-fact study stopped one step earlier than scoring. Its
frozen frame was exhausted: all 1,698 candidates were considered and 245 were
admitted, but the Wikipedia family supplied 25 of its frozen quota of 70. The
frame verifier therefore marked the cohort non-scorable. No endpoint result was
computed, the shortfall was not redistributed, and no GPU run followed (C-33).

Three subsequently frozen independent-replication instruments stopped earlier
still, during metadata-only capacity measurement and before any payload was
opened. SFIR1 encountered a frozen Git-root HTTP 404; SFIR2 refused Git revision
chronology; and SFIR3 refused a recursive Git-tree response whose declared
`Content-Length` exceeded its frozen 16 MiB bound. None wrote a capacity
metadata artifact, froze a roster, acquired a cohort, computed a diff or
SourceFact, scored an endpoint, or authorised a model run. After the third
instrument refusal we did not immediately open SFIR4: redesigning again after
observing three successive failure modes would make the next instrument
increasingly a function of prior outcomes. GPU use therefore remains 0 seconds
and spend $0 (C-35).

> **Correction, 2026-08-27 (P-02).** SFIR4 has since been opened, and this
> paragraph's objection is the standard it was opened against rather than a
> reason it was not. Its design charter and spent-identity authority were frozen
> before any of its own data existed, and its criterion — the per-family
> threshold, the root set, the per-root cap, the cohort, the selection salt and
> the scorer — has not moved since.
>
> Three census attempts aborted before producing a number, and each correction
> that followed is recorded with the evidence that it was determined by an
> endpoint's behaviour rather than by an outcome: a renamed eCFR metadata field
> (INC-V2-095), a reserved CFR title that carries no edition date because it has
> no edition (INC-V2-096), and an unhandled `RemoteDisconnected` — which
> subclasses `ConnectionResetError`, not `URLError`, and so matched no handler
> (INC-V2-098). All three aborted *result-blind*: in each case no capacity
> quantity was computed, printed or written, and no receipt existed at the
> destination path, verified before anything was touched.
>
> One disclosure belongs here rather than in a footnote. Diagnosing INC-V2-096
> revealed that CFR title 35 contributes zero candidates — outcome information
> about one of fifty roots, learned before the census completed. It cannot be
> unlearned. What protects the study is that it changed nothing: the root set is
> charter-frozen and title 35 remains in it, and its disposition is computed by
> the adapter rather than chosen.
>
> **No SFIR4 capacity, roster, endpoint or acceptance result is claimed in this
> draft.** GPU use remains 0 seconds and spend $0.

---

## 1. What this paper claims, and what it does not

The contribution is not a system that works. It is a set of separations that
hold up when you look for them, and an account of an evaluation discipline
strict enough to stop its own headline experiment.

**Available:**

- mechanism evidence for selective recompilation and coverage on development data
- seventeen negative findings, each closing a door. They include held-out
  preflight refusals, endpoint infeasibility, a non-scorable exhausted frame,
  and three prospectively frozen replication instruments that stopped before
  payload acquisition
- two safety measurements the system does not pass, with the instruments' own
  power reported alongside. **These are negative closure evidence, not
  mechanism evidence, and they are development diagnostics rather than
  held-out** — see §5 and C-20
- four selective stale escapes confirmed on the production path alone, and a
  root cause for all four
- a prospective 223-pair, three-family migration-closure result in which all
  eight declared invariants were exercised and met with zero recorded
  violations (C-34)
- a methodological result about outcome-independent preflights

**Not available, and not claimed anywhere in this document:**

- any statement about model behaviour. No model was run. The model experiment's
  status is `NOT_RUN — PREDEFINED CPU PREFLIGHT INFEASIBLE`.
- correctness of the compiler over arbitrary sources.
- calibration of any threshold. `CalibrationTable.calibrated` is `False`
  throughout and refuses to be set true without naming a corpus.
- any comparison of answer-generation strategies. The arm that would have tested
  one exists as a design in a protocol that was never executed.
- any SFI3 endpoint result. The acquisition frame was exhausted, but one frozen
  family quota was not met, so the admitted cohort was not scored (C-33).
- any SFIR endpoint or GPU-successor result. SFIR1, SFIR2 and SFIR3 all
  terminated at their frozen metadata-only capacity instruments before payload,
  roster, acquisition or scoring. They establish instrument refusal only
  (C-35); they do not establish a model or compiler endpoint result.

---

## 2. Method: freezing, receipts and preflights

Three rules carry most of the weight.

**A protocol is frozen before its data exists.** Each protocol is a YAML
document sealed by content hash before acquisition begins. Gates, floors,
thresholds and exclusion codes are all in it. When a result later disappoints,
the protocol is what makes the difference between reporting a failure and
inventing a reason.

**A receipt is immutable and cannot be overwritten.** Receipts land on
run-specific paths, carry their own content hash and the digests of the tool and
protocol that produced them, and the writer raises rather than replacing an
existing path. `R1` exercised the refusal: a second run was refused the first
run's path, wrote its own, and left the first byte-identical (C-11).

**A preflight is outcome-independent.** Every study runs a CPU-only preflight
against its frozen gates before any expensive resource is touched. The preflight
cannot see a model output because no model has run when it executes. This
sounds like bookkeeping until it refuses something.

### 2.1 Incidents as first-class output

Incidents are recorded in an append-only ledger, several of which are the
reason a later result is trustworthy. Three are worth naming here:

- `INC-V2-006` — two revisions whose canonical units were byte-identical while
  the raw source had changed, one of them moving a link target. Every mechanism
  measured up to that point sat downstream of the canonicaliser and none could
  see it. This produced the entire source-coverage workstream.
- `INC-V2-010` — the markup policy classified fourteen attributes, including
  `colspan` and `rel`, as presentation. They change compiled interpretation.
  Reclassified forward, with the old results left standing under the grammar
  they declared.
- `INC-V2-021` — two acquisition processes ran concurrently against one output
  path because an empty log was read as death. Neither reached its write. The
  instructive part is that both walked the same frozen list under the same
  deterministic predicate, so they would have produced the *same* cohort and the
  second write would have looked like a normal success. A duplicate that agrees
  is harder to notice than one that disagrees.

---

## 3. Mechanism results (development split)

### 3.1 Selective recompilation agreed with full recomputation

On 34 revision pairs across two families, the selective path and a full rebuild
produced identical active state, with zero artifacts carried forward whose
full-rebuild value had moved (C-01).

**The limitation is structural and it is the reason section 5 exists.** Both
sides consumed the canonical document the engine had already produced. A defect
in canonicalisation is common-mode across them, so this comparison cannot see
one. The earlier 28-pair Wikipedia figure is the same shape and is described the
same way: same-implementation full-recomputation equivalence.

### 3.2 Coverage from canonical fact to artifact

On 43 pairs, every artifact whose canonical inputs changed was rebuilt, the
declared carry ban was never violated, and three positive controls fired while
three negative controls did not (C-02). The controls matter more than the
headline: a run in which nothing was wrong reads identically to a run in which
the probe does not work.

### 3.3 Refusal legibility

Nineteen declared refusal constructs executed as specified, every refusal
carried its evidence, and admission was invariant across 120 permutations for
each of 11 candidates (C-04). This is a harness result about a refusal
mechanism. It is not a statement about any deployed system.

### 3.4 Retrieval without reading the answer

Using only document title, identity, type and heading fields — never atom body
text — the retrieval envelope contained the target for 0.9903 of 720 questions,
and the target atom was recovered in every case where the envelope contained it
(C-05). Two leakage controls were rejected by construction: one that injected a
body token into the intent view, and one whose intent field differed across the
two revisions.

---

## 4. Negative findings

These are the part of the programme we would most want a reader to take.

### N-01. Full rebuild equivalence is not source faithfulness

Of the 43 pairs where full and selective rebuilds agreed exactly, **26 were
simultaneously source-coverage incomplete**: raw source changed in ways that
reached no canonical fact (C-03). Both build paths agreed perfectly about a
canonical state that had already dropped something.

The corollary is uncomfortable and worth stating plainly: an equivalence result
between two build paths is evidence about the paths, not about the source. A
system can be internally consistent and externally wrong, and the consistency
check will report success.

### N-02. Canonical atom granularity is not retrieval granularity

The unit that carries a fact and the unit a question can retrieve are different
sizes, and the gap is measurable (C-06). This is a finding about an assumption,
not a prescription: we do not claim the atom size is wrong.

### N-03. Surface lexical overlap is not information-provenance leakage

Questions built only from heading and identity fields still overlap the answer
text lexically. That overlap is not evidence that the construction leaked
(C-07). The separation is argued from the construction rule and the forbidden
source list and checked by controls; it is not a measurement of an information
channel, and we say so.

A related limit came out of the same protocol: on enumerated regulatory text,
80.7% of eCFR questions have a leaf heading that tokenises to the empty string,
so an answer-independent construction rule produces a query that cannot
distinguish sibling subsections (C-08). The fix — taking a distinguishing token
from the body — is exactly the leakage the protocol was frozen to exclude, so
the limit is published instead.

### N-04. Locally-complete semantic change is not exact-value endpoint eligibility

Of 296 locally-complete semantic-change candidates, 274 differed only in prose
and could not support an exact-value question. Ten survived a preflight whose
floor was 190 (C-12).

### N-05. Value-bearing structure is not a frequently observable value transition

Two held-out studies, in sequence, each removing the explanation the previous
one left open.

Forty-five fresh documents were selected for value-bearing structure — tables,
infoboxes, configuration keys, regulatory quantities. The extractor read and
paired 174 properties across spaced revision pairs. **None of their values had
moved** (C-13). The structure was there; the transitions were not.

That could have been bad pair sampling, so the successor searched revision
*history* directly. A complete walk of 2,271 fresh lineages, under a frozen
1,460-day horizon and a twelve-revision bound, found a qualifying stable-property
value transition in **3** (C-14). Of the rest, 1,107 carried too few revisions
inside the horizon and 1,144 carried no qualifying transition inside the window.

The two refusals are different failures and both were measured directly. Most
CFR sections carry a single dated version in the horizon. Twelve revisions of a
busy Wikipedia article span about four months, while the infobox quantities
update roughly annually — so the bound and the edit rate interact, and they
interact in opposite directions at the two ends: busy lineages give a window too
short in time, quiet ones give too few revisions at all.

**The bound was not moved.** It is frozen on API, compute and reproducibility
grounds with `explicitly_not_basis: observed value-fact yield`, and this
measurement is precisely that yield. Widening it would find more, and widening
it after seeing this number would make the bound a function of the thing it
measures.

### N-06. An outcome-independent preflight can correctly stop an expensive experiment

Three preflights, each frozen before its cohort existed, refused to start a GPU
study. Nine of eleven gates passed at the first refusal, so the failure was
localised rather than global: the machinery worked and the population did not
exist (C-15).

The stopping record is `STOP-V2-005 —
EXACT_VALUE_MODEL_ENDPOINT_NOT_FEASIBLE_UNDER_DECLARED_PUBLIC_SOURCE_FRAME`. The
model experiment status is `NOT_RUN — PREDEFINED CPU PREFLIGHT INFEASIBLE`. The
GPU authorisation for the cycle is terminated.

What this establishes is narrower than "the hypothesis is false" and we do not
say otherwise. It establishes that the cohort required to test it is not
reachable within the declared public source frame, and that the cost of learning
that was CPU time.

---

## 5. Two development diagnostics, and a forensic confirmation

Two protocols were written after the stopping record and run on disjoint slices
of the same frame. **Both FAIL, and the failures are the contribution.**

**Neither is held out.** Both were designed as held-out studies and both lost
that status to an evidence-hygiene pass: a smoke execution on real cohort
lineages produced and exposed outcome-derived metrics 35 and 28 minutes before
the respective protocol amendments, and both protocols were first frozen after
the runs they govern had already started. The demotion was derived mechanically
from immutable receipt timestamps and file modification times rather than
decided (C-20, INC-V2-027).

Nothing was repaired, re-scored or re-run. Not one number below moves. What
changed is the split each may be reported under, and that is the correct
outcome of a one-sided test: **the burden is on the study to demonstrate the
negative, and absence of proof of exposure is not proof of absence.**

### 5.1 Source front-end faithfulness (C-16, FAIL, development diagnostic)

`SOURCE_FAITHFULNESS_HELDOUT_V1` asks the narrower question a revision pair
makes possible: when a region of source changes, does the system say what became
of it? Every changed region must resolve to exactly one of `MODELED`,
`IGNORED_BY_PREDECLARED_POLICY` or `UNRESOLVED_SOURCE_FACT`. A changed byte that
no state covers is a hard failure.

    310 pairs · 4 families · 2,268 lineages walked · 0 GPU seconds
    split: development diagnostic (demoted; see C-20)

    changed regions                            373,006
      unclassified                                   0
      MODELED                                  121,682
        verified against the compiled state     58,486
        NOT carried by the compiled state       63,196
      IGNORED_BY_PREDECLARED_POLICY             97,560
      UNRESOLVED_SOURCE_FACT                   153,764

    scopes examined                              1,010
    scopes the run declared locally complete        601
    pairs where a loss sat inside a complete scope   30
    pairs where the compiled state did not move      60

**Nothing fell through.** Every one of 373,006 changed regions carried a state,
which is the half of the protocol that passed and the half that makes the rest
readable.

**More than half of the regions the grammar calls MODELED have nowhere to live.**
54,053 of the 63,196 unverified claims fail for one declared reason: the facet
they carry — reference locator, metadata, accessibility, temporal — has no place
in a compiled artifact, which holds unit text, headings, explicit paths and
document order and nothing else.

**In 30 of 310 pairs the loss was not declared.** The witness decides local
completeness from the grammar's four states alone and cannot see whether a
MODELED claim survived verification, so a construct the policy calls MODELED and
the compiler does not store passes it unnoticed. The gate had power: 601 scopes
were declared complete, so a passing result would have meant something.

The scope-level figure of 209 is an upper bound and we do not use it as a
headline; markdown scope regions are supersets (INC-V2-026). An
attribution-free criterion — the compiled state did not move at all while some
scope was declared complete — gives 34 pairs, larger than the gate's 30, so the
verdict is not an artefact of that coarseness.

### 5.2 Independent implementation differential study (C-17, FAIL, development diagnostic)

`ORACLE_INDEPENDENCE_V2` rebuilds the expected state from raw bytes in a
separate `python -I -S` process with an import guard armed inside it, and has a
third comparator — importing neither side, and the only process that hashes the
comparison — judge them.

**It is a differential study, not a verification.** The two implementations
share a specification, and that specification was written by reading the engine.
A defect living in the specification is common-mode and this design cannot see
it. The earlier working title claimed verification by an independent oracle; it
overstated the result and is retired. The permitted name is *independent
implementation differential study*. True independent verification would first require an
independently checkable reference semantics for the supported grammar, which
does not exist and is not produced by labelling a second implementation an
oracle.

    170 pairs attempted · 164 judged · 6 UNJUDGED · 0 GPU seconds

    exactly equivalent                             114
    divergent                                       50   (30.5%)
    oracle-relative divergences                      4   → see §5.3
    typed invalidation consistent                77 / 77
    reference-locator-only pairs                    12
      of which the engine reported no change        12

**Four oracle-relative divergences**, where the same-implementation comparison
found zero on 34 pairs. They are *oracle-relative* and stay that way: a
divergence between the production path and a second implementation is not, by
itself, evidence that the production path left something stale. Section 5.3 is
where that question is answered by the production path alone.

**Two implementations of the same written specification disagree on 30.5% of
pairs.** On Wikipedia the engine derives four units where the oracle derives
one. This is a finding about the specification, not a defect rate of the
selective path — and it is the reason the permitted wording is "independent
implementation" and never "independent verification".

**All twelve reference-locator-only pairs were reported clean.** An instrument
built for a different question, on a disjoint cohort, reproduced §5.1's
finding exactly.

The isolation held: both the oracle and the comparator were clean by import
graph and at runtime, in every judged pair, under `-I -S`. Six pairs the oracle
could not judge were reported `UNJUDGED` and none was counted as a pass.

### 5.3 Forensic confirmation on the production path alone (C-18, C-19)

A divergence against a second implementation says where to look. It does not say
the production path left anything behind. That question was asked directly, on
the terms the ruling set:

    production clean full rebuild(new raw)  vs  production selective result(new raw)

Freshly fetched bytes — never the cache, which is a copy and not evidence — the
production canonicaliser and the production compiler. The independent
implementation appears nowhere in the check.

**All four confirm.**

| case | clean rebuild moved | selective detected | carried though moved |
|---|---|---|---|
| `wikipedia:en:Three Villages` | 1 | *nothing* | `section:u:95960f72…` |
| `wikipedia:en:Monteceneri` | 1 | *nothing* | `section:u:0bf3fdf6…` |
| `wikipedia:en:Locarno` | 1 | *nothing* | `section:u:55f9943b…` |
| `git:pnpm/pnpm.io:docs/cli/change.md` | 6 | `evidence_moved`, `structure_changed` | `topic-bucket:…:0` |

In the three Wikipedia cases the selective path detected no change of any kind,
rebuilt nothing and carried all four artifacts forward, while a clean full
rebuild of the same bytes produces a different `section:` artifact.

**Four named cases are not a denominator.** This is post-result forensic
confirmation. It is not a rate, and it re-scores nothing: §5.2's receipt is
untouched and its counts stand exactly as executed.

**The root cause is not the one the table suggests.** Each stale artifact's
source difference was classified against a fixed, declared, cumulative
normalisation ladder — the first rung at which the two texts agree names the
difference:

    typographic_punctuation        1    curly quotes against ASCII quotes
    alphanumeric                   2    punctuation-only differences
    artifact_membership_or_order   1    a topic bucket whose membership moved

**Not one of the four is the compiler missing a substantive content change.**
Three are cases where the semantic diff correctly judged an edit non-semantic
and the artifact fingerprint moved anyway; the fourth is a plan-coverage gap on
a derived membership artifact. So the defect is an alignment failure with a
precise shape:

> the diff's notion of "changed" and the fingerprint's notion of "changed" are
> two different functions, and nothing requires them to agree.

The consequence is not that an edit is lost. It is that **the selective state is
not reproducible by a clean rebuild** — a quieter failure, and one which means
every equivalence result this programme has produced was measured on pairs where
the two notions happened to agree. §3.1 is bounded by that sentence.

---

## 6. Limitations

1. **Split.** The early mechanism results are on the development split. The
   preflight refusals, endpoint infeasibility, SFI3 frame stop and SFIR
   instrument refusals are held-out negative or methodological evidence. V2R4
   is the later positive held-out exception, scoped to its eight migration
   invariants on 223 pairs. The paper can present that bounded closure result;
   it cannot present confirmatory end-to-end source-faithfulness.
   **The two safety studies of §5 are neither.** They were designed as held-out,
   failed a one-sided evidence-hygiene test, and are development diagnostics
   (C-20). Their FAIL verdicts are still real failures observed on data the
   instruments had not been tuned against; what they cannot do is carry the
   evidential weight of a held-out result.
2. **No model was run**, so no claim about model behaviour of any kind is
   available from this programme.
3. **The second implementation shares its specification** with the system it
   compares against, and the two disagree on 30.5% of pairs, which bounds how
   sharply the remaining agreement can be read. It is a differential study; no
   independent verification was achieved, and achieving one would first require
   an independently checkable reference semantics for the supported grammar.
4. **The silent-drop localisation is coarse on markdown**, so the scope-level
   count is an upper bound and only the pair-level and attribution-free counts
   are used (INC-V2-026).
5. **No threshold is calibrated.** Every threshold is a declared parameter and
   is presented as one.
6. **Scale.** The corpora are hundreds to low thousands of documents from four
   public families. Nothing here speaks to private, multi-tenant or
   high-volume operation.
7. **Self-approval.** No external reviewer has read any of it.
8. **Selective state is not reproducible by a clean rebuild** in at least four
   confirmed cases (§5.3), so §3.1's equivalence result is bounded by the
   alignment failure that produced them.
9. **The independent replication sequence did not reach a corpus.** SFIR1,
   SFIR2 and SFIR3 each stopped at a different frozen Git metadata constraint
   before payload. The sequence supports a claim about instrument feasibility
   and adaptation discipline, not about source-fact endpoint behaviour.
10. **No SFIR corpus has been opened at all.** Across four
    independent-replication instruments no roster was frozen, no cohort was
    acquired and no payload was read. Every statement this paper makes about the
    SFIR sequence is a statement about instruments; none is a statement about the
    sources those instruments were built to read.
11. **Four instrument stops, four different causes, none of them combinable.**
    SFIR1 stopped on a Git-root HTTP 404, SFIR2 on a revision-chronology
    contract, SFIR3 on a recursive-tree `Content-Length` bound and SFIR4 on an
    exhausted rate-limit retry budget (§10.2). They are not four attempts at one
    measurement and cannot be pooled; each preserves only the particular
    constraint that stopped it.
12. **The capacity criterion has never been evaluated.** No SFIR instrument
    reached the point of applying its per-family threshold to a counted candidate
    set. Nothing here indicates that the declared frame is adequate, and nothing
    here indicates that it is short. SFIR4 needs particular care on this point
    because its stop is operational rather than evaluative: `capacity_measured`
    is `incomplete` and `scientific_threshold_evaluated` is `false` in its own
    terminal receipt.
13. **The binding constraint throughout has been this study's own instruments
    rather than the corpora.** Of the causes that ended the four censuses, a
    renamed metadata field, an adapter with no path for a legitimately empty
    root, an unhandled transport exception class and a retry budget set for a
    patience the endpoint does not permit are all defects or mis-specifications
    on this side of the boundary; in each of those cases the endpoint answered
    correctly (INC-V2-095, INC-V2-096, INC-V2-098, INC-V2-101). That is the
    honest summary of where the effort went, and it bounds any reading of the
    sequence as evidence about the difficulty of the sources themselves.

> **Correction, 2026-08-27 (P-04).** Limitation 9 above names "SFIR1, SFIR2 and
> SFIR3". A fourth instrument, SFIR4, has since been opened and sealed at a
> terminal operational stop (§10.2), so the sequence is four instruments and
> still no corpus. The original wording is left in place because its substantive
> claim — that the sequence supports a statement about instrument feasibility and
> adaptation discipline rather than about source-fact endpoint behaviour — is
> unchanged, and now rests on one more instrument than when it was written.

---

## 7. What the programme's discipline actually cost, and bought

It cost three failed cohorts and a headline experiment. It bought the ability to
say which of the three failures happened, in what order, and why the third one
narrowed the explanation rather than repeating it.

The alternative was available at every step and was cheap: widen the value
patterns, add a value kind, raise the context budget, lower the floor, reweight
the families, adopt a semantic judge. Each would have produced a runnable study
and a number. None would have produced a number that meant anything, and the
protocol that forbade each of them was frozen before anyone knew which one would
be tempting.

---

## Appendix A. Claim binding

Every claim above carries a `C-nn` identifier resolving to a row of
`paper/CLAIM_MATRIX.yaml`. Each row carries exact wording, the protocol, the
receipt and its digest, the split, the limitations, the wording that is
permitted and the wording that is not. `tools/build_claim_matrix.py` refuses a
row whose receipt is missing, whose bytes moved under it, or whose self-hash
does not recompute, and scans this document for every forbidden phrase.

## Appendix B. Status vocabulary

`NOT_STARTED` · `PARTIAL` · `IMPLEMENTED` · `TESTED` · `PROVEN` · `AUDITED` ·
`BLOCKED`. Programme status is **PARTIAL — MECHANISM EVIDENCED, ENDPOINT NOT
ESTABLISHED**. Code presence is not completion, and tests passing is not proof.

---

## 8. SOURCE_FACT_IR: the repair, and how it is being tested

**All positive source-faithfulness language in this section is PROVISIONAL until
the fresh held-out study returns.** Section 8.4 is where its verdict goes, and it
is written so that a FAIL requires no rewriting above it.

### 8.1 What SFH1 actually found

Not that the compiler loses source facts. That was known. It found that the
*instrument* could not tell the difference between a fact the compiled state
carried and a fact the grammar merely recognised: 121,682 regions were called
`MODELED`, and 63,196 of them could not be verified against the compiled state
at all. The old `MODELED` was a claim the grammar made from a table, and nothing
consulted the state it was a claim about.

So the repair is not a parser change. It is representation completeness.

### 8.2 Four states, and the one that is fail-open

    REPRESENTED_IN_COMPILED_STATE   the state carries it and the chain resolves
    RECOGNIZED_BUT_UNREPRESENTED    the parser saw it; nothing carries it
    IGNORED_BY_PREDECLARED_POLICY   declined in advance, by a named policy
    UNRESOLVED_SOURCE_FACT          seen, not decidable

Only `IGNORED` is fail-open, and only when it names a policy that existed before
the run. The IR refuses a policy reference on any other state, because a policy
citation on a fact that was not actually declined makes a defect read as a
limitation — the single most valuable confusion in this programme to prevent.

Two properties are enforced by construction rather than by convention. A
`REPRESENTED` fact without a representation cannot be built. A representation on
any other state cannot be built. The distinction the four states exist to draw
cannot be quietly dissolved by a caller.

### 8.3 The chain, and the kind that exists because of silence

Every represented fact must resolve four links:

    source witness -> canonical representation -> fingerprint -> dependency path

A missing link means the state is not source-faithful CURRENT, whatever its
state field says. This is the part SFH1 had no way to check: a state can carry no
losses and still be unfaithful, because a represented fact whose fingerprint or
dependency path is absent looks carried and behaves dropped.

Representations live in the IR and never in unit text. Text is where facets go to
become invisible: a reference whose target moved but whose anchor text did not
produces no textual difference at all, so a text-only state cannot represent the
change, cannot fingerprint it and cannot invalidate on it. That is INC-V2-006
and three of the four confirmed stale escapes, and it is why reference targets,
language, accessibility, applicability, effective time, authority, canonical
locator and provenance spans are each a first-class kind with its own
dependency channel.

One kind exists for a stranger reason. `UNSUPPORTED_CONSTRUCT` is a facet type
for constructs whose facet we cannot name, and it is always `UNRESOLVED` — it can
never be represented and can never be declined by policy, because a policy
declining "everything we do not support" would restore the silence with
paperwork attached. It exists because an adversarial fixture found that a section
containing MathML scored perfectly: no extractor claimed it, so no fact described
it, so nothing was wrong. Converting that absence into a fail-closed fact is what
makes the containing scope stop being complete, which is the true statement about
the world. It also makes the silent-loss endpoint measurable for the first time —
you cannot count a fact that produced nothing.

### 8.4 The fresh held-out study

`SOURCE_FACT_IR_HELDOUT_V1`, frozen at `0531dd0e...` **before one real lineage
was read**, against seven declared endpoints. The freeze discipline is a direct
consequence of INC-V2-027: a smoke run is an execution, so this study smoke-tests
on fixtures only.

The cohort is fresh by necessity, not by preference. SFH1 walked its entire frame
— 2,268 of 2,268 — so no unspent pool existed and the frame was expanded from
declared roots disjoint from every predecessor's: 1,997 candidate lineages, none
of which any earlier study touched. The four forensically confirmed stale escapes
are excluded by name, because a case used to diagnose a defect cannot certify its
repair.

Three families, not four. `sec_edgar` is absent: every predecessor issuer is
exhausted and fresh identifiers cannot be verified without acquisition. This is a
real narrowing of grammar breadth — SEC HTML was the only long-form filing
grammar in the predecessor frame — and quotas were **not** redistributed to the
remaining three to keep the target, because moving a quota to cover an absent
family is tuning against yield by a sympathetic route.

**Verdict: FAIL.** 260 pairs scored, 128,715 source facts, across three families.

    E1  no unclassified changed region        MET      0 violations   260 pairs exercising
    E2  no recognized-but-unrepresented       FAILED   1,284          260
    E3  no silent loss in a complete scope    MET      0               81
    E4  no reference/locator-only clean miss  MET      0               30
    E5  no confirmed selective stale escape   SKIPPED  never exercised  0
    E6  selective/clean-rebuild equivalence   SKIPPED  never exercised  0
    E7  unresolved fails closed               MET      0              121

    REPRESENTED_IN_COMPILED_STATE   121,065
    UNRESOLVED_SOURCE_FACT            4,826
    IGNORED_BY_PREDECLARED_POLICY     1,540
    RECOGNIZED_BUT_UNREPRESENTED      1,284

Two SKIPPED endpoints fail the study on their own, independently of E2. E5 and E6
require artifacts to be rebuilt from raw payloads, and nothing in this run did
that. They are reported SKIPPED rather than MET because **an endpoint nothing
could have violated has not been met — it has been avoided**, and a study whose
two hardest safety endpoints went untested does not get to pass on the strength
of the five that ran.

### 8.4.1 The failure is one kind, and it is link 1

Every one of the 1,284 unrepresented facts is a `PROVENANCE_SPAN`, and every one
carries the same reason: *the unit's text could not be located in the raw
source*. 1,048 are git markdown, 124 Wikipedia, 112 eCFR.

The canonicaliser strips markup, collapses whitespace and joins blocks, so a
unit's text is generally not a substring of the source it came from. Three
declared location strategies recover most of it — 121,065 facts resolve — and for
1,284 units none of them does. Those units have text in the compiled state that
**cannot be pointed back at any bytes**.

That is link 1 of the chain missing, and it is worth being exact about what it
does and does not mean:

- it does **not** mean the text is wrong, or that an edit was lost. The content
  is there and its digest matches.
- it **does** mean the state cannot say where that content came from. No witness,
  so no anchor; no anchor, so nothing downstream can attribute a source change to
  that unit; and the scope containing it cannot be called source-faithful CURRENT.

The old instrument could not have found this. It asked the grammar whether a
paragraph was modelled, the grammar said yes, and it was right — the text *is*
carried. The question of whether the carried text is traceable to its source was
not one the previous design could pose.

### 8.4.2 What was not done about it

`_locate` was not improved and the study was not re-run. Widening the location
strategies until 1,284 becomes zero, on the corpus that produced the 1,284, is
fitting an instrument to its own result. The corpus is spent; the repair, when it
is attempted, is demonstrated on a fresh disjoint one or not at all.

Nor were the two SKIPPED endpoints quietly dropped. They stay in the protocol,
they stay SKIPPED, and they stay counted against the verdict.

### 8.4.3 Cohort composition, as executed

    frame               1,997 fresh lineages, zero dropped as spent
    considered          1,997
    admitted              260   (floor 200, target 290)
    by family           git 120/120 · wikipedia 70/70 · eCFR 70/100
    rejected            TOO_FEW_REVISIONS 1,128 · BEYOND_FAMILY_QUOTA 601
                        CANONICALISATION_EMPTY 5 · PAYLOAD_UNAVAILABLE 3
    wall                3,448 s · GPU 0 s · $0

eCFR came in 30 under its quota. The floor and the three-family requirement are
met, and the quota was not lowered to make the shortfall disappear — a quota
moved after a count exists is not a quota.

### 8.5 What the four replayed cases do and do not show

Replayed through the typed representation, all four confirmed stale escapes have
their stale artifact named by the typed delta's invalidation set, where the
production path named nothing.

Stated at its true weight: this is a favourable diagnostic on the exact four
cases used to *design* the repair, which is the weakest evidential position
available. An earlier run of the same tool returned the opposite answer for all
four, because witness anchoring was wrong — the verdict is a property of the
implementation on the day it ran, not a settled fact. Four named cases are not a
denominator, and those four lineages are excluded from the held-out cohort
precisely so this result cannot be counted twice.

### 8.6 What building it in parallel actually cost

Eight lanes were implemented simultaneously against one written contract, then
integrated deterministically. Every lane's own suite passed throughout. The
integration found four defects that no lane could have found alone, and they
share one shape:

* the IR module was loaded twice under two names, producing two registries. An
  extractor was registered, tested, and produced nothing.
* witness `unit_path` was document-qualified on one side of the contract and
  bare on the other, so the resolver derived a document key of `040c3fd8...`
  where the real key was `e1f43638...`.
* an unsupported construct produced no fact at all.
* two lanes disagreed on percent-encoding equivalence, one reporting a false
  delta for a re-encoding of the same URI.

**None of them raised. Each one reported a clean result.** That is the same
failure this IR exists to prevent, arriving through the import system, through a
tuple convention, and through a normalisation rule instead of through a parser —
which is the strongest argument available that the failure class is real and not
an artefact of one component.

---

## 9. Native provenance: the second attempt, and what it is being asked

**The study described here was frozen before its corpus was read, scored once,
and returned FAIL. Its corpus is spent and is development material from here on.
It is not rescored, and the sections below were written before the result and
are left as written.**

### 9.1 Why the first attempt's defect was not a tuning problem

SFI1 failed on three grounds and the third was 1,284 `PROVENANCE_SPAN` facts in
`RECOGNIZED_BUT_UNREPRESENTED`, every one carrying the same reason: the unit's
text could not be located in the raw source.

The obvious response — widen the location strategies until the number reaches
zero — was refused, and not only because refitting an instrument on the corpus
that exposed it is fitting. It would not have worked, for a reason worth stating
precisely:

> The canonicaliser strips markup, collapses whitespace, decodes entities and
> joins blocks. By the time a unit's text exists, **there is nothing left to
> search for.** A tolerant matcher does not fail less often; it fails
> differently. It finds the *wrong* bytes.

And a provenance span that is wrong is worse than one that is absent, because
the absent one is visible. `_locate` answered 121,065 times and declined 1,284,
and the declines were the visible part of the problem — the 121,065 answers were
never checked against anything.

### 9.2 The replacement: witnesses by construction

The canonicaliser knows exactly which bytes it is reading at the moment it emits
each character, and the previous design threw that away and reconstructed it
afterwards. The replacement records it instead.

A span-map carries, per emitted run, the source byte range behind it, in one of
three relations: `copy` (verbatim from those bytes), `replace` (emitted *instead*
of those bytes — an entity decoded, a whitespace run collapsed) and `insert`
(emitted from nothing). Maps compose, so a staged pipeline still answers in raw
source bytes with no intermediate offset surviving into the answer.

Two design decisions carry most of the weight.

**`to_source` never guesses.** Output with no source returns nothing rather than
a neighbour's span. An honest absence is a fail-closed fact a study can count; a
confident wrong answer is a mis-attribution nothing downstream can detect.

**There is no way to emit text without naming its source.** The builder exposes
`copy`, `replace` and `insert` and no general `write`. A convenience method
would let a canonicaliser add an untraceable character by accident, which is the
entire class of defect being removed. `insert` is used in exactly one ordinary
place: the separator between two blocks joined under one heading.

The map is verified before it is published — a `copy` run whose bytes do not
decode to the text it claims is refused, and a unit whose map fails verification
reports no span at all rather than a span its own checker rejected. Publishing an
unverified span would be `_locate`'s mistake made one layer further in.

A consequence that is stated rather than smoothed over: **being fully sourced is
a different question from having a span.** A unit assembled from several blocks
carries an inserted separator, so its span is exact and its text is not entirely
accounted for. Both facts are recorded per unit.

### 9.3 What the study asks, and why two endpoints could not be dropped

`SOURCE_FACT_IR_HELDOUT_V2` requires all seven endpoints to be exercised and met,
over at least 200 pairs from at least three families, on a corpus disjoint from
SFI1's, SFH1's and the four forensic diagnostic cases.

E5 and E6 — confirmed selective stale escape, and exact selective-versus-clean
equivalence — may not report `SKIPPED`. They did in SFI1, and each failed that
study on its own. Retaining them was the decision that mattered most: five
endpoints were met with real gate power, and calling the other two *not
applicable to this instrument* would have produced a passing study that had
avoided its two hardest questions.

> An endpoint nothing could have violated has not been met. It has been avoided.

Answering them required rebuilding artifacts, which SFI1 never did. The rebuild
now happens where the raw payloads and both documents are already in hand, and
compares selective execution against a clean full rebuild over the *union* of
both artifact key sets — strictly stronger than the forensic tool's comparison,
which could not see a key the selective state never emitted. The forensic
subset is reported alongside so the two numbers can be checked against each
other.

### 9.4 A blind spot, declared before the corpus was read

E3 detects silent loss by way of `UNSUPPORTED_CONSTRUCT`, a short named list.
Loss occurring inside the reader, before any fact exists, is outside it. An
adversarial fixture found one such case and it was confirmed independently:

    The refund window is <b class="term"30 days</a> from delivery.

Both the markdown strip and the HTML parser absorb the malformed span whole.
`30 days` never reaches canonical text. The surviving unit reports
`fully_sourced: true`, zero verification failures, zero inserted runs, zero
parser anomalies — **silent loss with a clean bill of health.** It sits upstream
of the span map, so native provenance cannot see it: the map faithfully
describes text that is already missing content, which is correct behaviour for a
map and no comfort at all.

It was not repaired. A heuristic detector for malformed markup is exactly what
the unsupported-construct list avoids, because a general detector fires on
ordinary prose and buries the real cases; and an over-firing one would push pairs
into the fail-closed set, shrinking the judged cohort and potentially costing E5
and E6 the gate power this study exists to give them. So the limitation is
declared in the frozen protocol, and one sentence travels with any E3 number
this study produces:

> `MET` means no silent loss was found among the constructs this instrument can
> see. It does not mean none occurred.

What the successor is owed is not a detector but **byte accounting**: the span
map measures output coverage and nothing measures input coverage, so source
bytes consumed inside a unit's span and represented by nothing are currently
uncountable. Counting them makes this class visible with no heuristic at all.

### 9.5 Result

    pairs                    278  (floor 200, met)
    families                 3    encyclopedia_wikipedia · git_docs · regulation_ecfr
    facts                    92,957
    frame                    EXHAUSTED — 1,859 of 1,859 considered, 278 admitted,
                             1,581 rejected, 0 unaccounted

    E1  no unclassified changed regions        MET      0 / 278
    E2  no recognized-but-unrepresented        FAILED  14 / 278
    E3  no silent loss in a complete scope     MET      0 /  82
    E4  no reference-or-locator-only miss      MET      0 /  39
    E5  no confirmed selective stale escape    FAILED  14 / 158
    E6  exact selective vs clean equivalence   FAILED  14 / 190
    E7  unresolved fails closed                MET      0 / 121

    verdict                  FAIL
    receipt                  sfi2-native-provenance--20260823T085006Z-e53cc8aaeb7d
    result digest            sha256:a29b6520a868e985a5bfadc0953f0c99b5e812d085d667d6dcfb9bf4838ac58c
    correction               sfi2-score-correction--20260823T085421Z-be3e5836e575

**The E5 line above is a correction, and the correction is part of the result.**
As first scored, E5 read `SKIPPED_NEVER_EXERCISED` — "no judged supported pair
in this cohort could have exhibited it." That sentence was false: 158 pairs
could have and 14 did. The executor writes its escape block under the name of
what it *measured* (`E5_confirmed_selective_stale_escape`); the scorer looked
for the name of the property the protocol *asserts*
(`E5_no_confirmed_selective_stale_escape`). E6's two names coincide by accident,
so E6 scored correctly and the run looked coherent. The integration test written
to catch exactly this mismatch accepted `SKIPPED` as a valid outcome, so a
missing block satisfied the gate meant to detect it.

Nothing was re-acquired and nothing was re-measured; the rebuild had run once,
during acquisition, and its result was already inside the receipt being
corrected. The verdict did not move — `FAIL` on E2 and E6 before, `FAIL` on E2,
E5 and E6 after. The correction runs in the **unfavourable** direction, which is
the property that distinguishes it from fitting: a correction that makes a
result worse is not a result being arranged.

### 9.5.1 What the study established

**The defect SFI1 failed on is gone, completely.** SFI1 reported 1,284
`RECOGNIZED_BUT_UNREPRESENTED` facts, every one a `PROVENANCE_SPAN`. In SFI2
that count is **zero**. Not smaller — absent. Native provenance did what
retrospective location could not, and the endpoint SFI1 died on is no longer the
endpoint SFI2 died on.

**What replaced it was made visible by removing it.** The 14 remaining
unrepresented facts are all `INCLUDE_TARGET`, every one an include whose target
is a computed expression rather than a single string literal. This defect was
present in SFI1 and invisible underneath 1,284 louder ones.

**E5 and E6 failed on the same 14 pairs.** The intersection is 14 and the
difference is 0, across 14 distinct lineages, in both eCFR and git. Two
endpoints measuring different things agreed exactly, which is what a single
shared cause looks like.

**And the typed cross-check reported clean.** 191 of 191 pairs, zero
under-invalidated, zero silent facts.

That result is true and it does not mean what it appears to mean, which took a
forensic to establish and is worth stating carefully. The cross-check verifies
that every artifact the delta **named** as moved was invalidated. It never
verifies that the delta named everything that actually moved.

> A cross-check computed over a set the defect removes members from cannot see
> the defect. Its denominator is downstream of the thing being tested.

So the correct reading of the pair of results is narrower than the obvious one:
*given what the delta named, invalidation was complete.* Whether the delta named
enough was not measured by anything in SFI2, and it is where all fourteen
failures live. Section 9.7 gives the cause.

### 9.6 What a failure here would and would not mean

This study failed. The corpus is spent, the result is reported as a negative
held-out closure result, and that is where it stays. It is not a reason to widen
the grammar, lower a gate, drop a construct or re-score, and the repair is
measured on a corpus that had no hand in exposing the defect — which is why the
14 execution cases and the 14 include-target cases are development fixtures for
the successor and are excluded from its cohort. A case used to diagnose a defect
cannot certify its repair.

Five designs have now each declined to produce the positive result their authors
expected, each for a different and nameable reason. This one is the first whose
failure moved the question somewhere else: the four before it were failures of
the representation, and this is a failure of the executor, reached only because
the representation stopped failing first.

## 9.7 The cause, and why nothing was broken

All fourteen cases resolve to one gate, in a module neither the provenance work
nor the executor work had any reason to look at.

`diff_documents` decides whether to emit `MODIFIED_CLAIM` by comparing
`identity_text` on the two sides. `identity_text` is
`normalize_text_for_identity`: NFKC, casefold, then every non-word/non-space
character folded to a space. In all fourteen cases the raw text genuinely
differs and the normalization folds the difference away — a `®` appearing after
"Apache", `Github` becoming `GitHub`, `( e.g.` closing to `(e.g.`, a hyphen
becoming an em dash, `§§ 262.14,` splitting into `§ 262.14, §`, an ellipsis
removed. Six surface varieties, one gate, fourteen cases.

Everything after that is a correct consequence. No `MODIFIED_CLAIM` is emitted,
so the logical id never enters `changed_logical_ids`; the graph traversal is
never seeded, so it never reaches the node; `to_rebuild` correctly excludes an
artifact nothing reached — the planner's own explanation is the sentence *"no
change reached it"* — and the build correctly carries it forward because it is
not in the planned set.

**There is no defective component.** Every stage did exactly what it was built to
do, given its input, and fourteen stale artifacts reached ACTIVE state.

### 9.7.1 One function, two questions

`normalize_text_for_identity` exists to answer *"is this the same unit across two
revisions?"* For that question, folding a trademark symbol is **correct**: the
unit did not become a different unit. `diff_documents` reuses that answer for a
second question — *"is this unit unchanged?"* — for which the same fold is
**wrong**, because a trademark symbol appearing is exactly a change.

    identity  — did this unit survive?         insensitivity is the feature
    change    — did this unit's content move?  insensitivity is the defect

Nothing is mis-implemented and no threshold is mis-tuned. A function was asked a
question it was not built to answer, by a caller that had a different one, and
the two questions want opposite properties from the same normalization.

### 9.7.2 The wider form of the same shape

A second lane, building adversarial cases from the channel definitions rather
than from the spent corpus, found the same shape one level wider. Of five typed
dependency channels, only two — semantic and structural — have an edge in the
executor's graph, and the recompilation allow-list admits only two. Reference,
temporal and metadata changes are detected and correctly typed, then discarded
before seeding. All three return the planner's same sentence.

This explains an SFI2 line that looked clean and is: **E4 — no
reference-or-locator-only clean miss — MET, 0 over 39 pairs.** E4 asks whether
the system *reported* no change. It reported every one. Nothing asked whether the
report caused a rebuild.

> An endpoint can be genuinely met, with genuine gate power, and sit directly
> beside a defect it was never shaped to ask about.

That is not a scoring error and E4's result is not weakened. It is the limit of
the question, and the answer is a new endpoint rather than a re-reading of the
old one. The successor adds one: every detected typed change in a supported
channel must create a rebuild request. When this section was written, three of
five channels failed it, which was the point — an endpoint the system already
passes measures nothing.

> **Correction, 2026-08-27 (P-01).** Three of five channels no longer fail it.
> The gap was closed in `akc_cir.recompilation`: LOCATOR, TEMPORAL and METADATA
> each now seed their own traversal from the matching dependency channel. What
> did *not* change is that the endpoint is unmeasured — E9 has been scored on no
> cohort, and the corpus that exhibited the gap is spent, so the repair cannot
> be scored against the data that revealed it. The sentence a reader needs is
> not "all five channels propagate" but "all five are typed, and each propagates
> exactly where an edge declared it, recording UNRESOLVED where none did" —
> because propagating across edges that declared nothing is the blunt failure
> measured at 80.5% false invalidation. The endpoint therefore remains worth
> asking, for a different reason than when it was written: not because the
> system fails it, but because nothing has yet asked it of a cohort.

## 10. SFI3 stopped at the frozen acquisition frame (C-33)

`SOURCE_FACT_IR_HELDOUT_V3` was opened only after its protocol and lineage frame
were frozen. The acquisition then reached its declared exhaustive ending: all
1,698 candidates were considered, 245 were admitted and 1,453 were rejected.
The admitted family counts were 120 git documentation, 100 eCFR regulation and
25 Wikipedia encyclopedia pairs.

The first two families filled their frozen quotas. Wikipedia did not: 25 of 70
is a shortfall of 45. The frame receipt therefore records `scorable: false` even
though the overall floor was exceeded and all three families are represented.
Those other facts do not substitute for the predeclared family quota.

This is an acquisition-feasibility result, not an endpoint result. E1 through
E9 were not scored; the 245 admitted pairs establish no compiler rate and no
PASS or FAIL for the production repair. The shortfall is not redistributed, the
quota is not lowered, and the opened corpus remains spent. Consequently there
is no SFI3 acceptance, no successor cohort, no four-link acceptance and no GPU
execution. GPU use remains 0 seconds and spend remains $0.

### 10.1 Three independent-replication instruments stopped before payload (C-35)

SFI3's spent frame was not repaired or reweighted. Three new studies instead
used fresh protocol identifiers, fresh design charters and disjoint authority
chains. Each ran only a prospectively frozen, metadata-only capacity instrument:

| Instrument | Frozen refusal | Last scientifically permitted state |
|---|---|---|
| SFIR1 | Git-root metadata returned HTTP 404 | terminal before capacity metadata |
| SFIR2 | Git revision chronology could not satisfy the frozen chronology contract | terminal before capacity metadata |
| SFIR3 | recursive Git-tree `Content-Length` exceeded the frozen 16 MiB response bound | terminal before capacity metadata |

All three receipts record `capacity_metadata_written: false` and
`payload_opened: false`. No diff, SourceFact or endpoint outcome was computed;
no score was attempted; no roster or acquisition was authorised. These are not
three endpoint failures and cannot be combined into one. They are three
instrument-feasibility refusals, each preserving the exact constraint that
stopped it.

We stopped the redesign sequence after SFIR3. A fourth instrument could be
written, but after observing three successive failure surfaces its design would
be increasingly conditioned on the realised refusals. Calling that another
independent confirmation without a new, externally justified design basis
would risk result-following adaptation. The scientifically honest terminal
state is therefore `NO SFIR4 OPENED`, with no endpoint result, no model result,
0 GPU seconds and $0 spend.

> **Correction, 2026-08-27 (P-03).** SFIR4 was subsequently opened, so
> `NO SFIR4 OPENED` is no longer where this sequence ends. The paragraph above
> is left standing as the standard the fourth instrument was opened *against*
> rather than as a description of the current state: SFIR4's design charter and
> spent-identity authority were frozen before any of its own data existed, and
> its criterion — the per-family threshold, the root set, the per-root cap, the
> cohort, the selection salt and the scorer — has not moved since. The table in
> this section gains a fourth row in §10.2 rather than being rewritten, because
> the four stops are four separate instrument-feasibility refusals and merging
> them would destroy the only thing they individually establish. No SFIR4
> capacity, roster, endpoint or acceptance result is claimed anywhere in this
> draft; GPU use remains 0 seconds and spend $0.

### 10.2 SFIR4 stopped operationally, and that is not a capacity result

SFIR4 was opened under the objection §10.1 records, which is to say that the
objection was treated as a specification rather than as a veto. Four
metadata-only capacity censuses were then attempted against the live endpoints.
The first aborted after roughly fifty minutes on an eCFR metadata field that had
been renamed between SFIR3 and SFIR4 (INC-V2-095); the second on a reserved CFR
title that carries no edition date because it has no edition, which the adapter
had no path for and so refused the entire census over a root that had in fact
answered correctly (INC-V2-096); the third after twelve minutes on
`http.client.RemoteDisconnected`, which subclasses `ConnectionResetError` and
`BadStatusLine` rather than `urllib.error.URLError` and therefore matched none
of the handlers the instrument declared (INC-V2-098). The fourth ran twenty-nine
minutes, passed the point at which all three predecessors had died, and refused
with `encyclopedia_wikipedia rate-limit retry budget exhausted` (INC-V2-101).
SFIR4 is sealed there. Its terminal receipt records
`state: TERMINAL_OPERATIONAL_STOP`, `corpus_opened: false`,
`capacity_measured: incomplete` and `scientific_threshold_evaluated: false`.

The distinction that carries this section is between an instrument that asked
its question and received an unwelcome answer and an instrument that never
reached the point of asking. SFIR4 is the second. The capacity criterion was
never applied to anything: no candidate was counted, no threshold evaluated, no
roster frozen, no cohort read. A reader who files this under the same heading as
a failed capacity check will draw the inference that the declared frame is short
of capacity, and **nothing in this programme establishes that either way** —
neither that the frame is sufficient nor that it is not. The stop receipt is
explicit on the point in its own `what_this_receipt_does_not_say` field, and the
field exists because the confusion is the natural one to fall into: a run that
ends without a number and a run that ends with a number below a floor look alike
from the outside, and only the receipt distinguishes them.

Three of the four corrections were made and one deliberately was not, and the
line between them is the whole methodological content of the incident. A field
that has been renamed, a root that cannot carry an edition date, and an
exception class that no handler names are **unconditional defects**: each has
exactly one right answer, and it is the same answer whichever way the census
would have come out. Repairing them cannot bias a result, because the repair is
determined by the endpoint's behaviour and not by any property of the outcome.
A retry budget is not of that kind. `maximum_retries_per_request: 5`,
`max_rate_limit_wait_seconds: 60` and `max_total_rate_limit_wait_seconds: 180`
are tuning parameters, and a value chosen after watching a run fail is chosen
partly by the failure — there is no version of that edit that is not informed by
the run it responds to. So the budget was not touched and SFIR4 was not
re-frozen a fourth time. That the corrected value would probably have been
harmless is beside the point; what would not have survived is the property that
makes the first three corrections defensible, namely that a reader can check
that each of them was forced.

The alternative repair is worse, and is named here so that it is visibly refused
rather than merely unmentioned. Making the traversal fit the frozen budget
without touching the budget means reducing `max_category_pages_per_root`, which
changes the cohort — and changing a cohort after a failure is precisely the move
the standing instruction forbids outright. Between an edit that biases a
parameter and an edit that biases the sample, the study is not choosing the
lesser of the two; it is declining both.

§2 states the standard this has to meet: a protocol is frozen before its data
exists, and §10.1 extends that into the claim that redesigning again after
observing successive failure modes would make the next instrument increasingly a
function of prior outcomes. The SFIR4/SFIR5 split is an attempt to satisfy that
sentence rather than to route around it. Re-freezing SFIR4's budget and calling
the next census the same study would have been the evasion — one protocol
identity would then contain both the observation of a failure and the parameter
chosen in response to it, with nothing in the record able to separate them.
Sealing SFIR4 where it stopped and taking a **new prospective protocol
identifier** for the successor keeps the two on opposite sides of a freeze
boundary. The scientific question is carried across unchanged; what the successor
is permitted to alter is transport feasibility and nothing else. That is a weaker
guarantee than never having failed, and it is stated as the weaker thing it is:
SFIR5 is not independent of SFIR4 in the sense that SFIR1 was independent of
everything, because the fact that a pacing budget is needed at all was learned
from SFIR4. What the split does preserve is that the budget is chosen from a
direct measurement of the endpoint rather than from any capacity quantity, and
that the reasoning sits in a receipt where it can be checked rather than in an
assertion.

All four aborts were verified **result-blind before anything was touched**: in
each case the destination path held no capacity receipt, and the captured run
output was searched and holds a traceback and nothing else. No capacity quantity
was computed, printed or written at any of the four stops. One disclosure sits
against that record and is repeated here rather than left in the ledger:
diagnosing INC-V2-096 revealed that CFR title 35 contributes zero candidates,
which is outcome information about one of fifty roots learned before any census
completed. It cannot be unlearned. What protects the study is that it changed
nothing — the root set is charter-frozen, title 35 remains in it, and its
disposition is computed by the adapter rather than chosen.

The independent-replication sequence therefore now stands at **four instrument
stops and no opened corpus**:

| Instrument | Frozen refusal | Last scientifically permitted state |
|---|---|---|
| SFIR1 | Git-root metadata returned HTTP 404 | terminal before capacity metadata |
| SFIR2 | Git revision chronology could not satisfy the frozen chronology contract | terminal before capacity metadata |
| SFIR3 | recursive Git-tree `Content-Length` exceeded the frozen 16 MiB response bound | terminal before capacity metadata |
| SFIR4 | Wikipedia rate-limit retry budget exhausted; the frozen budget deliberately not edited | terminal operational stop; capacity incomplete |

These are four instrument-feasibility refusals, each preserving the exact
constraint that stopped it, and they do not add up to an endpoint outcome of any
kind. What they do add up to is a finding, and it is presented as one rather than
apologised for: **against live, third-party, unauthenticated endpoints, a
capacity instrument frozen in advance failed to survive contact with those
endpoints four times, and each failure was of a different kind** — an absent
root, a chronology contract, a response-size bound, a transport exception class,
and finally a request-pacing bound. None of the five is exotic, none was
anticipated by a design that had already been hostile-audited, and every one of
them is invisible to a study designed against a fixture. That is a result about
what prospective freezing costs on infrastructure one does not control, and it is
the kind of result that is normally absorbed into an appendix by studies that
quietly re-ran until something worked.

The successor's status is stated narrowly because nothing more is available. The
stop receipt names `succeeded_by: SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V5`. No
SFIR5 protocol document exists in the research tree as this section is written,
the choice between publishing the fourth stop as terminal, opening a paced
successor and pursuing authenticated access is recorded in INC-V2-101 as a
founder decision rather than an agent's, and consequently **no SFIR5 capacity,
roster, endpoint or acceptance result exists or is claimed**. GPU use across the
whole sequence remains 0 seconds and spend $0.

[CLAIM-PENDING: a CLAIM_MATRIX row binding this section to
`receipts/sfir4-terminal-operational-stop.json`, and an amendment to C-35, whose
wording describes a three-instrument sequence.]

> **Correction, 2026-08-27 (P-05).** The paragraph above states that no SFIR5
> protocol document exists in the research tree. That was true when it was
> written and is no longer true; it is left standing because the sequence in
> which these artifacts appeared is part of what the section is describing.
>
> SFIR5's design charter now exists and is frozen. Its distinguishing property
> is that it declares **none** of SFIR4's science: not the families, not the
> roots, not `C_f`, not `Q_f`, not the caps, not the salt, not the identity or
> payload rules. It names SFIR4's charter by digest and defers to it, and the
> freeze refuses any SFIR5 charter that restates one of those fields — including
> when the restated value is currently correct, since a copy is free to diverge
> later and nothing would notice. The census executes SFIR4's own probe against
> SFIR4's own charter, and that probe re-hashes itself against the charter
> before it runs. "The same question was asked" is therefore not a claim about
> intent; it is the same bytes, verified by the same code, refusing to start if
> either has moved.
>
> Two things changed and only two, both transport: a frozen per-host request
> interval, and routing every family through the response-evidence ledger.
> SFIR4's retry bounds (5 / 60 s / 180 s) are unmodified, and the freeze reads
> them from the live module rather than from a copy, so editing the frozen
> instrument is what turns the gate red. One consequence is disclosed rather
> than left to be found: pacing sleep is not charged to that retry budget,
> because it is not waiting on a 429, so a paced census can spend wall-clock the
> frozen fail-safe does not count. A separate finite wall-clock ceiling exists
> for exactly that reason.
>
> The second change repairs a defect found in SFIR4 while building the
> successor, and it is worth the paper's space. SFIR4's hash-chained response
> ledger covered **one family of three**: only one code path wrote to it, and
> the other two reached the network by a route that discarded the observation.
> The consistency check could not have caught it — a family that records nothing
> produces no aggregate, and an empty recomputation agrees with an empty
> declaration exactly. The census receipt would have contained no false field.
> It would have presented a response-evidence chain covering a third of the
> census and been silent about the silence. No sealed census exists anywhere in
> this programme, so nothing published is affected; the finding is about what
> the instrument would have certified, and it was caught by construction rather
> than by consequence.
>
> **What is still not claimed.** As this correction is written the SFIR5 census
> is executing and has produced no output. There is no SFIR5 capacity figure, no
> roster, no endpoint result and no acceptance result, and the sentence in bold
> above stands unchanged. GPU use across the whole sequence remains 0 seconds
> and spend $0.

### 10.3 Two occasions this analysis was confidently wrong before it was right

Both are recorded in INC-V2-101 and both are left standing in the ledger rather
than edited away, on the principle that a programme whose stated method is that
incidents are its output does not get to delete the incidents in which its own
reasoning was the defect.

The first was a diagnosis of *why* the Wikipedia census was being throttled. An
interleaved A/B against the live endpoint, seconds apart, produced six
alternating trials with perfect separation: the non-compliant User-Agent returned
HTTP 429 three times with `Retry-After` values of 17, 13 and 9, and the compliant
one returned HTTP 200 three times. The conclusion drawn was that Wikimedia
rate-limits by User-Agent. It was wrong. Minutes later the bare User-Agent
returned 200 as well, and the countdown in the retry-after values — 17, then 13,
then 9 — is the tell that was there all along: the bucket the census had already
exhausted was recovering while the trials ran. The A/B never isolated the variable
it named. It compared an exhausted rate bucket against a fresh one, and the clean
alternation was an artefact of the alternation itself.

The second was a volume estimate. The declared Wikipedia frame is 30 roots at up
to `max_category_pages_per_root: 100`, and that hundred was read as a request
count, yielding "up to 3,000 requests" and, at the observed throughput, "on the
order of 4.6 hours" — from which followed the much stronger conclusion that the
instrument could not reach a Wikipedia capacity measurement at this frame under
any sequence of events. The adapter batches, and had all along:
`category_page_size: 500` covers a hundred-page root in one request, and
`revision_batch_size: 50` fetches revisions for fifty titles at once. The real
figure is roughly three requests per root and **about ninety in total**, which at
the observed throughput is on the order of ten minutes rather than four and a
half hours. The estimate was wrong by more than an order of magnitude, and it was
wrong because a configuration value was never checked against the code that
issues the requests.

The methodological point is the same in both cases, and it is not the obvious one
about double-checking. It is that **a wrong answer that reproduces is more
dangerous than one that does not.** Six clean alternating trials is the kind of
evidence that ordinarily ends an investigation; reproducibility was doing no work
there, because the confound was itself time-dependent and the alternation sampled
it in phase. No number of additional repetitions would have found it. In both
cases the correction came from a control the first test did not contain —
re-testing the arm that had failed, after waiting long enough for the bucket to
refill, and reading the batching constants in the adapter rather than the page
counts in the protocol. The pacing measurement that a successor would be designed
against was taken only after both corrections, with a cool-down between arms so
that one trial's bucket could not bleed into the next, which is that same control
applied prospectively: 0 s spacing gave 10 successes and 2 refusals, 2 s gave 10
and 2, 5 s gave 11 and 1, and 7 s gave 20 successes and no refusals over 150
seconds. That spacing below about six seconds does not help is what says the limit
is a quota over a roughly-sixty-second window rather than a per-request rate — a
shape neither wrong answer would have predicted. It is admissible for designing a
successor because it measures the endpoint and not a capacity result: no candidate
was counted, no threshold evaluated and no cohort read.

Neither correction changes SFIR4's disposition. The corrected volume figure makes
a successor cheaper to run; it does not make a 180-second total wait retroactively
adequate for approximately ninety requests against an endpoint that admits about
ten per minute.

## 11. Identity/change migration closure

The migration campaign separated three questions that earlier instruments had
collapsed: what the resolver decided, whether an independent uncertainty signal
quarantined the neighbourhood, and what effective disposition downstream code
was permitted to publish. It also separated identity equivalence from
compiled-relevant change equivalence. A unit may retain its lineage while its
content, reference, temporal, metadata or structural facets change.

The sequence is evidence, not discarded scaffolding:

| Study | Cohort | Raw result | Scientific reading | Corpus state |
|---|---:|---|---|---|
| V1 | 514 pairs | FAIL, 7/8 | unresolved identity could still emit a definite removal | SPENT |
| V2R1 | 285 pairs | FAIL | invalid instrument: raw-id equality substituted for resolver correspondence | SPENT |
| V2R2 | 270 pairs | FAIL | invalid instrument: local resolver and quarantine obligations conflicted | SPENT |
| V2R3R1 | 300 pairs | I6 MET | non-vacuous I6 evidence, but only one of eight declared invariants was graded | SPENT |
| V2R4 | 223 pairs | PASS | all eight declared invariants exercised and met, zero violations | SPENT, CLOSED |

The V2R1 and V2R2 raw failures remain raw failures. Their adjudication prevents
them from being misreported as production-correctness failures, and it does not
turn them into passes. Likewise, V1's seven met invariants cannot be combined
with V2R3R1's I6 result to synthesize an eight-invariant pass. The positive
closure authority is V2R4 alone (C-34).

### 11.1 V2R4 result

V2R4 used a fresh, prospectively frozen cohort of 223 pairs: 123 git
documentation pairs, 52 eCFR regulation pairs and 48 SEC filing pairs. Every
declared invariant was present in the declared, graded and receipt domains;
each verdict was `MET`; and every violation list was empty.

| Invariant | Exercising observations | Verdict | Violations |
|---|---:|---|---:|
| I1 identity decisions unchanged | 223 | MET | 0 |
| I2 identity fold remains identity-only | 3,432 | MET | 0 |
| I3 expectation is independent | 223 | MET | 0 |
| I4 changed facet resolves typed or fail-closed | 298 | MET | 0 |
| I5 never silently unchanged | 15,912 | MET | 0 |
| I6 ambiguous identity stays unresolved | 4,765 | MET | 0 |
| I7 only predeclared ignores | 23,868 | MET | 0 |
| I8 SFI2 cases cannot certify | 223 | MET | 0 |

The cohort exercised both defect classes that had invalidated predecessor
instruments: six resolver-established matches had differing revision-local raw
identifiers, and six locally `NEW` resolver decisions were overridden by the
independent quarantine surface. All six overrides resolved to
`EFFECTIVE_UNRESOLVED`. This is non-vacuous evidence for the frozen closure
contract on this cohort. It does not prove global compiler correctness, source
faithfulness over arbitrary grammars or completeness of all future dependency
channels.

### 11.2 What closure did not unlock

Migration closure was a predecessor gate, not the paper's final endpoint.
SFI3 subsequently exhausted its own frozen acquisition frame without satisfying
one family quota (§10). Because SFI3 was non-scorable, there is no SFI3
acceptance and therefore no actual successor universe on which to run the
four-link gate. The GPU successor remains correctly unexecuted.

| Result slot | Required authority | Current status |
|---|---|---|
| SFIR independent replication | a frozen capacity instrument, roster, acquisition and exactly-once score | **TERMINAL PRE-PAYLOAD — SFIR1/2/3 instrument refusals; no SFIR4 opened** |
| Four-link successor acceptance | SFI acceptance plus actual frozen successor manifest; eligible floor at least 120 | **NOT REACHED** |
| GPU successor study | SFI acceptance and four-link acceptance; at most 6 GPU hours and $40 | **NOT RUN — 0 GPU seconds, $0** |

## 12. Related work and boundary of novelty

Self-adjusting computation studies how a computation can record dependencies
and update its output after input changes [R1–R3]. TAVONEL does not claim the
idea of incremental recomputation. Its narrower problem begins before ordinary
dependency propagation: source units have inferred cross-revision identities,
the same identity can carry a different compiled-relevant state, and unresolved
identity must not silently become a definite change.

Database provenance and traceable-data work make derivation histories available
for explanation and recomputation [R2, R4]. Recent work on incremental knowledge
graphs applies why-provenance to changing graph state [R4]. Our receipts and
dependency witnesses share that concern with derivational traceability, while
the evaluated contribution here is the composition of typed source-fact change,
uncertainty quarantine, selective rebuild and verification-gated activation.

Retrieval-augmented generation and citation-oriented long-context systems study
how evidence is selected or attributed at answer time [R5, R6]. This programme
does not compare answer quality against them. It asks an upstream question:
whether the compiled knowledge state offered to retrieval can still contain an
artifact whose source-relevant state moved. The absent GPU endpoint is therefore
not replaced with a literature number or an indirect benchmark.

## 13. Discussion and limitations

The strongest result is architectural rather than universal. Failures exposed
where one representation had been made to answer two incompatible questions.
SFI1 showed that a compiler cannot verify a source relationship its intermediate
representation cannot express. SFI2 showed that identity continuity cannot
stand in for change equivalence. V1 and V2R2 showed that local resolver state
cannot supersede an independent uncertainty surface. V2R3R1 showed that a pass
rule naming eight invariants is not evidence if the scorer grades one. V2R4
closed that specific chain with a fresh full-domain result.

Important limitations remain:

- Source coverage is bounded by the supported grammars and the three families
  in each named cohort. Malformed or unsupported structures can disappear
  before an instrument sees them.
- Thresholds and quotas are declared design parameters, not calibrated
  estimates. Their prospective immutability protects interpretation but does
  not make them optimal.
- V2R4 establishes the predeclared migration-closure contract on 223 pairs. It
  is not a proof over arbitrary documents, resolver distributions or future
  dependency channels.
- SFI3 is non-scorable. Its 245 admitted pairs produce no endpoint rate and must
  not be used as an informal estimate.
- SFIR1, SFIR2 and SFIR3 are terminal pre-payload instrument refusals. They
  produced neither capacity cohorts nor endpoint observations, and opening
  SFIR4 after three observed refusal modes was rejected as a result-following
  adaptation risk.
- Abstention and quarantine reduce false certainty at an operational cost that
  this paper has not estimated.
- No model experiment ran. Claims about generation quality, model accuracy or
  GPU efficiency are unavailable.
- All evidence and review reported here are internal. No independent external
  reviewer or replication has approved the manuscript.

## 14. Reproducibility and evidence lineage

The reproducible unit is an immutable lineage, not a command copied from a log:

```text
declare -> freeze -> acquire -> reduce -> score once -> seal -> spend
```

Each numbered empirical claim is mapped in `paper/CLAIM_MATRIX.yaml` to an exact
receipt. `paper/claim_receipt_pins.json` records file hashes, and
`tools/verify_claim_pins.py` refuses missing, mutated or forbidden evidence.
Historical failures and superseded instruments remain addressable; later
adjudication adds a record rather than rewriting the raw verdict.

For V2R4, the canonical measurement is
`identity-change-migration-closure-v2r4--20260826T064947Z-e6cab21d2c93.json`;
the downstream authority is
`migration-closure-acceptance--20260826T065127Z-0d8f9b2c3e28.json`. For SFI3,
the canonical stopping evidence is
`sfi3-frame-verification--20260826T120526Z-b4f647f6e883.json`. Reproduction must
verify these exact paths and hashes rather than selecting the newest matching
filename.

The independent-replication stopping chain is likewise exact and ordered:
`sfir1-capacity-failure-authority.json` (Git HTTP 404),
`sfir2-capacity-failure-authority.json` (Git revision chronology), then
`sfir3-capacity-failure-authority.json` (recursive-tree `Content-Length` above
16 MiB). C-35 binds directly to the SFIR3 receipt; that receipt's charter and
spent-identity chain bind the predecessor sequence. A reproduction must verify
that all three report no capacity metadata, no payload, no score and zero GPU
or paid spend. It must not manufacture the missing artifacts by retrying the
frozen instruments.

### 14.1 Figure specifications

**Figure 1 — Compiler lifecycle.** A left-to-right flow from versioned source to
source facts, semantic identity, typed change, dependency traversal, selective
recompilation, candidate state, verification conjunction and one visible
activation. Mark unresolved identity as a fail-closed branch before publication.

**Figure 2 — Identity is not change.** Two parallel comparators receive the same
before/after units. The identity comparator tolerates representational variation
to preserve lineage; the facet comparator preserves compiled-relevant
differences. Their outputs join only at effective disposition.

**Figure 3 — Failure-driven evolution.** A vertical sequence SFI1 -> SFI2 -> V1
-> V2R1 -> V2R2 -> V2R3R1 -> V2R4, with each observed failure on the left and
the resulting representation or instrument change on the right. Do not colour
invalid-instrument results as production failures.

**Figure 4 — Confirmatory route and stops.** V2R4 PASS -> SFI3 frame exhaustion
-> non-scorable STOP. From a separate branch, render SFIR1 Git 404 -> SFIR2
revision-chronology refusal -> SFIR3 recursive-tree response-bound refusal ->
`NO SFIR4 OPENED (adaptation risk)`. None of those nodes is an endpoint FAIL.
Render roster, acquisition, scoring, four-link and GPU as dashed grey `NOT
REACHED` nodes, with `0 GPU seconds / $0` attached to the terminal state.

## 15. Conclusion

This programme did not establish that the compiler is correct end to end, and
it produced no model result. It did establish why several tempting proxies are
insufficient: rebuild agreement does not imply source faithfulness; identity
equivalence does not imply change equivalence; detected change does not imply a
rebuild seed; and a named pass rule does not imply that its full domain was
graded.

The positive closure result is precise: on a fresh, prospectively frozen
223-pair, three-family cohort, all eight predeclared identity/change migration
invariants were exercised and met with zero recorded violations. The next
held-out study then stopped without scoring because its frozen Wikipedia quota
was infeasible within the exhausted frame. Preserving both outcomes is the
paper's central methodological claim: evidence infrastructure is useful when it
prevents an attractive conclusion as reliably as when it supports one.

The independent replication did not overturn that stopping result. Three fresh
capacity instruments terminated before payload on three different frozen Git
metadata constraints. Reporting that sequence as instrument infeasibility —
and declining to design SFIR4 after observing the sequence — preserves a clean
boundary between prospective testing and result-following adaptation. It yields
no compiler endpoint verdict and no model result.

The manuscript therefore remains an internal research draft. The migration
closure is complete; the end-to-end SFI endpoint, successor four-link study and
GPU result are not. SFIR1 through SFIR3 are terminal pre-payload records, not
pending result slots. No further replication protocol is claimed or authorised
here. Founder, human and counsel review remain external and pending; the IP gate
remains CLOSED and the manuscript remains `INTERNAL_ONLY`.

## References

[R1] *A theory of self-adjusting computation*. ACM Digital Library.
https://dl.acm.org/doi/10.1145/1596527.1596530

[R2] *Traceable data types for self-adjusting computation*. ACM Digital
Library. https://dl.acm.org/doi/10.1145/1806596.1806650

[R3] *Imperative self-adjusting computation*. ACM Digital Library.
https://dl.acm.org/doi/10.1145/1328438.1328476

[R4] *Incremental knowledge graph construction using provenance*. *Journal of
Web Semantics*, 2023. https://doi.org/10.1016/j.websem.2023.100796

[R5] P. Lewis et al. *Retrieval-augmented generation for knowledge-intensive
NLP tasks*. NeurIPS, 2020. https://arxiv.org/abs/2005.11401

[R6] *LongCite: Enabling LLMs to generate fine-grained citations in
long-context QA*. 2024. https://arxiv.org/abs/2409.02897
