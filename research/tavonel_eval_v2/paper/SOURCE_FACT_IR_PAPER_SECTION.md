# SOURCE_FACT_IR — representation completeness, and what a fresh held-out run would have to show

**INTERNAL DRAFT — NOT FOR RELEASE.** IP gate CLOSED. No arXiv, no public
repository, no dataset, no demo. This section is a draft for integration into
`paper/TAVONEL_PAPER_DRAFT_INTERNAL.md`, written to bind against
`paper/CLAIM_MATRIX.yaml` the same way every other section does. It does not
edit the draft or the matrix; the proposed rows are collected in §5 for the
programme owning those files to add.

**Every positive statement about SOURCE_FACT_IR's source-faithfulness in this
section is PROVISIONAL** and is marked so at first use with **[PROVISIONAL —
holds only if a fresh held-out run PASSES]**. None of it becomes an
unconditional claim by rereading it more confidently. `SFH1` — the study that
found the failure this repair addresses — was itself demoted from held-out to
`development_diagnostic` by the evidence-hygiene pass (C-16, C-20), and its
successor cannot lend SOURCE_FACT_IR a pass it did not earn on its own fresh
data. G-01b in the readiness gaps is explicit about this: *the two demoted
studies must be re-established on a fresh disjoint corpus before any positive
source-faithfulness language becomes non-provisional*, and *SOURCE_FACT_IR_V1
may not reuse SFH1 to claim its repair passed*.

---

## 1. The failure this repairs

`SFH1` walked 310 held-out revision pairs across four source families and
classified every one of 373,006 changed source regions against the grammar's
`MODELED` / `IGNORED` / `UNMODELED` vocabulary. Every region got a label; none
fell through (C-16). That completeness of *labeling* was real, and it was also
where the instrument's own failure was hiding: `MODELED` was a question put to
the grammar, answered from a table, and never checked against the compiled
state. Of 121,682 regions the grammar called `MODELED`, 63,196 — a majority —
had nowhere to live in the artifact the run actually produced. In 30 of 310
pairs, a region the compiled state could not carry sat inside a scope the run
had declared locally complete. In 60 pairs the compiled state did not move at
all while the raw source had.

The founder's ruling names the shape of the mistake precisely: *a source
construct must never be called MODELED merely because the parser recognizes
it.* Recognition is a fact about the front end. Representation is a fact about
the compiled state, and nothing about the front end's fact entails the compiled
state's. `SFH1` asked the front end and reported the answer as if it were about
the artifact.

A second, independent line of evidence points at the same gap by a different
route. `ORACLE_INDEPENDENCE_V2` built an expected state from raw bytes in an
isolated process and judged the production path against it through a third
comparator that imports neither side. 114 of 164 judged pairs were exactly
equivalent; 50 diverged; 4 carried an oracle-relative divergence in which the
production path had carried forward an artifact the independent implementation
said must change (C-17). All four were then forensically confirmed against the
production path alone, with no dependency on the oracle: a clean rebuild of
freshly fetched bytes moved an artifact that the selective path did not (C-18).
Classified against a fixed normalisation ladder, none of the four arose from a
substantive content change — one was typographic punctuation, two were
punctuation-only, one was a topic-bucket membership shift (C-19). The interesting
part is not the size of the edit. It is that in three of the four the selective
path reported no change of any kind, for a reason the ladder makes visible: a
semantic diff and an artifact fingerprint are two different functions of the
same input, and nothing forces them to agree. `SFH1`'s majority-unrepresented
finding and `ORACLE_INDEPENDENCE_V2`'s stale-escape finding are not the same
measurement, but they are the same shape of failure seen twice: something the
front end saw is not reliably present, or not reliably invalidated, in the
compiled state.

Both studies were designed as held-out. Both were demoted to
`development_diagnostic` by the evidence-hygiene pass, because a smoke
execution on real cohort lineages produced and exposed outcome-derived metrics
before either protocol's amendment was frozen, and because both protocols were
first frozen after the runs they govern had already begun (C-20). Nothing about
either result was repaired, re-scored or re-run by that demotion. Only the
split each may be reported under changed, and the change is mechanical, derived
from receipt timestamps and file modification times, not decided. What that
means for this section is unforgiving and stated once, up front: **there is no
POSITIVE held-out result behind SOURCE_FACT_IR today.** What exists is a
held-out-designed *failure* — twice, by two different instruments — that names
the defect precisely enough to repair, and a repair that has not yet been run
against fresh data of its own.

---

## 2. Four states, not two

The repair is a vocabulary change before it is anything else, because the old
vocabulary was the failure. `MODELED` collapses two different claims into one
word — the front end saw it, and the compiled state carries it — and `SFH1`
shows what happens when 63,196 of 121,682 cases turn out to differ on exactly
that collapse. `SOURCE_FACT_IR_V1` (`source_fact_ir/ir.py`) splits it into four
states, and a fact is in exactly one:

- **`REPRESENTED_IN_COMPILED_STATE`** — the compiled state carries the fact,
  and the whole witness → representation → fingerprint → dependency chain
  resolves. This is the only state permitted inside a scope declared complete,
  and it is checkable against the artifact rather than merely asserted about
  it.
- **`RECOGNIZED_BUT_UNREPRESENTED`** — the parser saw the construct; the
  compiled state has no canonical representation for it. This is what the old
  `MODELED` actually meant in the majority of `SFH1`'s cases, and naming it is
  most of the repair. Fail-closed: a scope containing one cannot be declared
  complete.
- **`IGNORED_BY_PREDECLARED_POLICY`** — declined in advance, by a policy
  identifier that exists before the run. The only fail-*open* state, because a
  declared, named limitation is not the same failure as a silent one.
- **`UNRESOLVED_SOURCE_FACT`** — seen but not decidable: malformed source, an
  ambiguous locator, an unsupported construct. Fail-closed for the same reason
  `RECOGNIZED_BUT_UNREPRESENTED` is, and deliberately not allowed to stop the
  run outright — an unresolved fact that kills the run cannot be counted, and a
  fact that cannot be counted is indistinguishable from one nobody ever saw,
  which is the silent drop this whole programme exists to make impossible.

Fail-closed is enforced as a raised exception (`NotSourceFaithful`), not a
boolean returned into an `if` nobody wrote. A scope or a compiled state that
contains a fail-closed fact cannot be declared "complete" or "source-faithful
CURRENT" by any code path that goes through `assert_source_faithful` — it can
only be declared that by a caller that skips the check, which is a different
and visible failure.

The one architectural rule everything else follows from: **a representation
lives in the IR, not in unit text.** `INC-V2-006` is the concrete case that
makes the rule non-optional — two revisions whose canonical *units* were
byte-identical while the raw source had changed a link's target. Text-only
representation cannot see that kind of edit, cannot fingerprint it, and cannot
invalidate anything on it, because the text through which it would have to be
seen did not move. A reference target, a language tag, an effective date, an
applicability scope — none of these are safe to leave implicit in prose. They
have to be facts the IR carries explicitly, or the compiled state can lose them
the exact way `INC-V2-006` lost one and `ORACLE_INDEPENDENCE_V2`'s twelve
reference-only pairs (C-17) suggest it is not a rare shape of loss.

---

## 3. The chain, and why four links and not one

A `SourceFact` earns the label `REPRESENTED_IN_COMPILED_STATE` by construction
of the dataclass, but that label alone is not the property the founder's
ruling asks for. The chain is what carries that property, and it has four
links, each checkable independently:

1. **Witness** — where in the raw source bytes the fact was seen, as a byte
   span into the payload on disk, never into a decoded or re-normalised
   string. A witness that cannot be checked against the bytes on disk is a
   claim about the parser, not about the source; `Witness.verify` re-derives
   the excerpt from the raw bytes at read time rather than trusting a value
   recorded once.
2. **Representation** — a JSON-serialisable canonical value that is not the
   unit's own text. `SourceFact.__post_init__` enforces the state/representation
   pairing at construction: a `REPRESENTED` fact must carry one, and no other
   state may.
3. **Fingerprint** — a function of the representation, injected rather than
   built into the module (`Fingerprinter`), so this contract does not have to
   depend on the compiler that satisfies it to state the requirement.
4. **Dependency path** — the invalidation edges the fact's channel travels on
   (`SEMANTIC`, `STRUCTURAL`, `REFERENTIAL`, `TEMPORAL`, `DESCRIPTIVE`),
   likewise injected. `INC-V2-028`'s alignment failure is the reason this link
   is separate from the fingerprint rather than folded into it: a fact whose
   channel is declared cannot move without something downstream being told,
   and a fingerprint alone does not guarantee that a resolver was ever wired to
   it.

`chain()` resolves and reports each link without deciding anything —
deliberately, because a gate that cannot show which link failed is a gate
nobody can act on. `chain_complete()` is the boolean a caller who wants a
verdict actually uses, and `assert_source_faithful` is the fail-closed
entry point that raises rather than returning it.

Kind ownership is likewise explicit rather than incidental: `KIND_OWNER` assigns
each of the twelve fact kinds to exactly one lane (`core`, `reference`,
`metadata`), and the extractor registry (`register`) refuses a second
extractor claiming a kind another already produces. An unclaimed kind
(`unclaimed_kinds()`) is not an error — it is the system's honest answer to
"what does this build not look for," read by a protocol's gates rather than
assumed to be zero.

---

## 4. What a fresh held-out run would have to show

**[PROVISIONAL — holds only if a fresh held-out run PASSES.]** Nothing above
this line is a result about SOURCE_FACT_IR's own correctness; it is an account
of the failure it targets and the contract it implements. A fresh, disjoint,
held-out study — never touched by the smoke executions that demoted `SFH1` and
`ORACLE_INDEPENDENCE_V2`, frozen before its cohort exists, and reported under
its own receipt — would have to show, at minimum:

- **the representation majority inverts.** `SFH1` found 63,196 of 121,682
  `MODELED`-labelled regions with no compiled-state representation. A
  successor study over the same construct population would need to show that
  regions the front end recognises are, in the overwhelming majority, actually
  `REPRESENTED_IN_COMPILED_STATE` rather than `RECOGNIZED_BUT_UNREPRESENTED` —
  not merely that some now are.
- **the chain resolves end to end, not just at the representation link.**
  Carrying a JSON value is necessary and not sufficient. The fingerprint and
  dependency-path links have to resolve for the same facts, or a scope can
  still be silently wrong in the way `SFH1`'s 30-of-310 finding showed: a
  region the compiled state could not carry, sitting inside a scope declared
  complete.
- **the stale-escape shape does not recur under the new representation.**
  `ORACLE_INDEPENDENCE_V2`'s four forensically confirmed cases were reference-
  and structure-adjacent, not content edits, and three produced no detected
  change at all. A successor study should specifically probe reference-target,
  language, effective-time and applicability facts — the kinds a text-only
  representation cannot see moving — and show the fingerprint moves when the
  representation does, on a corpus this design has not previously touched.
- **it is held out for real.** No smoke execution against the fresh corpus
  before the protocol amendment is frozen; no protocol frozen after its run has
  already started. `INC-V2-025` and `INC-V2-027` are the two ways the prior
  attempt lost that property, and `evidence-hygiene-pass` (C-20) is the
  mechanical, timestamp-derived test that would catch a repeat.
- **it reports honestly if it fails.** A study designed to prove
  SOURCE_FACT_IR's repair that instead reproduces `SFH1`'s finding is exactly
  as publishable as `SFH1` was, under the same discipline: a verdict of `FAIL`
  is a result, not an outcome to be re-run until it changes.

Until that run exists and passes, the correct summary of SOURCE_FACT_IR's
status is: a repaired vocabulary and a checkable four-link contract, built in
direct response to two independently-shaped confirmed failures, not yet
measured against fresh data of its own.

---

## 5. Proposed claim-matrix rows

The following rows are proposed for `paper/CLAIM_MATRIX.yaml` §3. They are not
applied here — that file is owned by the orchestrator's integration pass. Both
rows use `status: NOT_YET_ESTABLISHED` and `receipt: PENDING`, the pairing
`tools/build_claim_matrix.py` requires for anything unproven, and both cite
`split: held_out` because that is what each is designed as, not what either has
achieved yet.

```yaml
claims:
  - id: C-21
    wording: >-
      SOURCE_FACT_IR_V1 defines a four-state vocabulary
      (REPRESENTED_IN_COMPILED_STATE, RECOGNIZED_BUT_UNREPRESENTED,
      IGNORED_BY_PREDECLARED_POLICY, UNRESOLVED_SOURCE_FACT) and a four-link
      chain (witness, representation, fingerprint, dependency path) intended to
      repair the representation-completeness failure SFH1 and
      ORACLE_INDEPENDENCE_V2 independently confirmed.
    protocol: SOURCE_FACT_IR_V1
    receipt: PENDING
    split: held_out
    status: NOT_YET_ESTABLISHED
    allowed:
      - the vocabulary and chain are implemented and unit-tested against the
        contract in source_fact_ir/ir.py
      - the design responds directly to SFH1's finding and to the four
        forensically confirmed stale escapes
    forbidden:
      - the repair passed
      - source-faithful end-to-end
      - SFH1 was repeated and passed
      - any claim that reuses SFH1's or ORACLE_INDEPENDENCE_V2's receipts as
        evidence of this claim
    limitations:
      - no fresh held-out corpus has been run against this implementation
      - this is a claim about what was built, not about what it achieves on
        held-out data

  - id: C-22
    wording: >-
      A fresh, disjoint, held-out study of SOURCE_FACT_IR_V1, frozen before its
      cohort exists and never exposed to a pre-freeze smoke execution, shows
      the majority of recognized source constructs are
      REPRESENTED_IN_COMPILED_STATE with all four chain links resolved, on a
      corpus SFH1 and ORACLE_INDEPENDENCE_V2 did not touch.
    protocol: SOURCE_FACT_IR_HELDOUT_V1
    receipt: PENDING
    split: held_out
    status: NOT_YET_ESTABLISHED
    allowed: []
    forbidden:
      - source-faithful end-to-end
      - no source fact is lost
      - the compiler is correct
      - any wording pending a receipt that does not yet exist
    limitations:
      - this row exists to be filled in by an actual run, or to be reported
        FAIL and left standing if the run does not support it
      - a PASS here authorises the GPU successor preflight's held-out gate
        (tools/gpu_successor_preflight.py, G_GSP_HELD_OUT_PASS_PRESENT); it
        does not by itself authorise any model claim
```

---

## 6. Relationship to the GPU successor preflight

`tools/gpu_successor_preflight.py` is the CPU-only readiness check for a model
study built on top of SOURCE_FACT_IR's repair — a study that asks whether a
model answering from the compiled representation gets a typed source fact
right where a model answering from unit text alone cannot, because the fact
(a reference target, a language tag, an effective date, an applicability
scope) never appears in the text. That endpoint is deliberately not the
exact-value endpoint `STOP-V2-005` closed: the closed endpoint needed a value
that *moved* between two revisions of one lineage, a transition scarce enough
that a complete walk of 2,271 lineages found it three times against a floor of
190 (C-14, C-15). The successor needs no transition — eligibility is a
property of a single revision's typed representation, not of a pair — so the
scarcity that closed the exact-value endpoint does not apply to it by
construction. The preflight's own central gate refuses to report the successor
ready until a receipt matching C-22 exists and PASSES; run today, with no such
receipt on disk, it reports `BLOCKED`.
