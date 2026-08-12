# Contract A v2 — `EXP-0101B` · Identity-Stable, Type-Aware Difference

*Written 2026-08-12 against `9e3a793`, superseding Contract A of
`ABSORPTION_EXPERIMENT_CONTRACTS_BATCH1.md` on the point of signal placement and
nothing else.*

**This is a contract, not code and not a performance claim.** No number below is
a measurement. Where a target appears it is a gate to be met, never a result.
**NOT CLEARED FOR EXTERNAL DISCLOSURE** — the EXP-0101 result this rests on is
internal and exploratory; see `EXP-0101/receipts/clean-room-provenance.json`.

Everything in batch 1 §0 still binds: the absorption path, the three arms, the
out-of-scope list, the two disciplines, the six gates, the ledger as the one IP
registry, the RED ordering, holdout hygiene and the §0.10 package structure. Only
Contract A's *Challenger* paragraph is replaced.

---

## 1. Why there is a v2

`EXP-0101` ran Contract A as written and it failed, decisively and with the
mechanism isolated. The rule of record, in the canonical three-question form:

> **Alignment asks which elements correspond.**
> **Identity asks whether this is still the same logical thing.**
> **Diff asks what changed about it.**
>
> **Content may be used at the alignment stage for candidate pairing. It must
> not enter the logical identity score.**

As first recorded, and preserved: *Content compatibility must not participate in
logical identity resolution.*

The three questions are the reason the rule is not arbitrary. They are different
questions, and content answers only the first and the third.

A logical claim's wording changing is *normal* — `identity.py:183` excludes
content from the identity seed for exactly that reason. So a content signal
inside the identity score pushes the changes that matter most below the merge
bar, where they become `IDENTITY_UNRESOLVED` and drop out of
`changed_logical_ids` (`semantic_diff.py:195`). The system does not say the
wrong thing; it says nothing about the thing it most needed to say.

Measured: critical numeric change recall **0/60**, against 1.0000 for CURRENT
and for the prior-art baseline. Removing that one signal and changing nothing
else restored it to 1.0000.

**Typed element reasoning is retained.** It is independent of the failed
integration, it is the source of every gain EXP-0101 measured, and CURRENT has
no equivalent: `critical_change_labelled_rate` is 0.0000 for CURRENT over 240
high-risk cases because `semantic_diff.py:422` has one label for every
modification.

### 1.1 The corollary that changes what "structural" may mean

`EXP-0101` also scored 0.0000 on figure replacement, and investigation found the
cause is not a second mechanism. `align_structural` resolved a caption's figure
binding and compared **the bound element's content hash**. It was named
structural and behaved as content.

| arm over 20 figure-replacement cases | recall |
|---|---|
| all alignment signals | 0/20 |
| minus `align_content` only | 0/20 |
| minus `align_structural` only | 0/20 |
| minus **both** | **20/20** |

Removing either alone recovers nothing. That is what rules out two independent
faults, and it generalises into the canonical corollary:

> **A signal named `structural` or `context` is treated as content-derived — and
> therefore banned from the identity stage — if its value is produced by reading
> text, a content hash, a token set, an embedding, or any content-derived
> digest. The name does not matter; what it reads does.**

**Consequence for this contract, and it is binding:** "structural compatibility
stays in the identity stage" is only safe under the corrected definition in §3.2.
Carrying EXP-0101's implementation forward would reproduce the failure while
appearing to comply with the restructure.

---

## 2. Question

Does moving content compatibility out of identity resolution and into a
type-aware difference stage hold critical semantic change recall at CURRENT's
level *while* reducing false invalidation from pure layout change — the two
things EXP-0101 could not achieve together?

---

## 3. The pipeline

```
Element Alignment  →  Stable Identity  →  Type-aware Difference Reasoning
                                       →  Semantic Change  →  Impact
```

The ordering is the contract. Content informs **who pairs with whom** at the
alignment stage and **what changed inside a pair** at the difference stage. It
never scores **whether this is the same logical unit**.

### 3.1 Alignment stage — content is allowed here

Blueprint §9.4's tiered candidate generation, unchanged from EXP-0101: exact
content hash → same structural neighbourhood → type-compatible approximate →
constrained one-to-one assignment. Its output is a pairing and a tier, not an
identity.

**This is not a loophole in the canonical finding.** Alignment answers a
different question. Using content to decide which of twelve table rows is the
counterpart of this one is not the same act as using content to decide whether a
row whose value changed is still that row.

### 3.2 Identity stage — signals, and the two rules

Supplied to `akc_cir.identity` as additional signals, inheriting
availability-aware renormalisation and critical-signal abstention. Protected Core
stays unmodified; final stable-id assignment stays with it (§9.6).

| kept | source |
|---|---|
| source continuity | core, `identity.py:231` |
| structural path | core |
| explicit identifier | core |
| previous / next context | core anchors, plus alignment-derived context |
| geometry / style | core |
| **spatial compatibility** | alignment layer |
| **structural compatibility** | alignment layer, **redefined per §3.2.1** |

| removed | why |
|---|---|
| **content compatibility** | the canonical finding |

**Rule 1 — no core signal is suppressed.** The integration adds keys. Removing
one the core computed would be replacing the core's judgement rather than adding
to it.

**Rule 2 — every added signal passes the content-derivation test.** Before a
signal enters the identity stage, its implementation is checked for any read of
text, a content hash, a token set, an embedding, or any content-derived digest —
on either side of the pair, **or on anything either side points at**. A signal
that fails is a difference signal, whatever it is called.

**This test is part of the definition of done for `EXP-0101B`, per signal, not a
follow-up.** Concretely, done requires:

1. a named test per identity-stage signal asserting the property, which fails if
   the signal's implementation is later changed to read content;
2. the signal's own source reviewed against the list above, with the review
   recorded in the experiment's receipts; and
3. `align_structural`'s corrected form (§3.2.1) covered by a regression test
   built from the figure-replacement class, since that is the case that
   exposed the failure in the first place.

A signal without all three is not admitted to the identity stage.

#### 3.2.1 Structural compatibility, corrected

Structural compatibility answers: *does this element still occupy the same
structural slot, and does its binding still point at the element occupying the
counterpart slot?*

- A table row's header-derived key is compared as a **key**, not as row content.
- A caption's binding is satisfied when the figure it points at is the figure
  **aligned to** the old caption's figure — the alignment stage already decided
  that pairing. It must **not** consult that figure's text, caption, content
  hash or any digest thereof.
- Where no binding exists on either side the signal is **absent**, with a
  `MissingReason`. Never zero.

#### 3.2.2 Context, and why it is not smuggling content in

`align_context` reads the alignment produced in §3.1, which used content. The
identity stage therefore consumes something content influenced, one step
removed. That is the pipeline working as specified — alignment precedes identity
by design — and it is **not** exempt from §3.2's rule 2, which tests the
*signal's own* implementation. If a measurement later shows context behaving as
a content proxy, it is removed on the same grounds as `align_content`, and this
paragraph is where that possibility was written down in advance.

### 3.3 Difference stage — type-aware, and where content belongs

Judged per element type, over pairs identity has already settled:

- text semantic change
- numeric change
- `may` → `must` (modality)
- exception added / removed
- table-cell value change
- formula semantic change
- rendering-only change
- row / column movement

Two of these — **rendering-only** and **row/column movement** — are the only
verdicts that assert *no meaning changed*. They keep EXP-0101's guard: a
demotion is unreachable unless the two sides' numbers are already identical.

---

## 4. Arms

Three, on one manifest, per §0.2.

| arm | what |
|---|---|
| `CURRENT` | `akc_cir` untouched. Also serves as batch 1's "identity without alignment" ablation. |
| `PRIOR-ART BASELINE` | `tech_xversion_diff`, clean room, **YELLOW / `CLEAN_ROOM_ONLY`** |
| `REVISED HYBRID` | §3 |

**The baseline is re-run, not copied forward.** §7 says why.

`EXP-0101`'s six arms are **not** re-reported as if they were this experiment's.
They are a prior internal result and are cited as one.

---

## 5. Dataset

The Knowledge Evolution Suite, **same generator, same seed, same manifest
digest** — `packages/absorption/src/akc_absorption/evolution_suite.py`,
`SUITE_VERSION = "kes-1"`. Comparability with EXP-0101 depends on it not moving.
If it must change, `SUITE_VERSION` is bumped and EXP-0101's numbers stop being
comparable; say so rather than quietly regenerating.

**Its limits carry forward unchanged and must be restated wherever the numbers
are:** the seed corpus is generated, not a subset of the production corpus; no
DART/SEC amendment pair and no Office→PDF export pair is included; no embedding
provider is called, so the content ceiling is lexical; the optical-degradation
class is half inside the fold table by construction; `TYPO_ONLY` defeats every
arm for want of a lexicon.

Adding the two missing dataset arms is **in scope for a later contract and out
of scope here**, because changing the corpus and the pipeline in one step makes
the result unattributable.

---

## 6. Metrics, ablations, statistics

Contract A's metric list, unchanged, plus the one EXP-0101 had to add:

**`layout_only_false_invalidation_rate`** — a layout-only case that is reported
as a semantic change **or** left unresolved. Both end in a rebuild. Reading the
false-positive rate alone lets an arm look better by abstaining more, which is
exactly what EXP-0101's challenger did: false positives 0.0708 → 0.0000, but
false invalidation 0.7500 → 0.7292, Holm-adjusted p = 0.4375. **This is the
primary cost metric, and the false-positive rate is never reported without it.**

**Ablations.** −spatial · −structural · −type-specific reasoning · per-mutation
class. Plus, mandatory: **an arm that re-adds content compatibility to the
identity stage.** EXP-0101 is the evidence for the canonical finding on the
current fixture; an experiment that restructures on the strength of it should
carry the falsifier that would overturn it.

**Statistics.** Paired at document-pair level. Exact McNemar for the binary
judgements. 10,000-resample bootstrap CI for rates, fixed seed. Holm–Bonferroni
across every arm × slice. Every rate carries its denominator.

---

## 7. Clean room — the baseline is re-implemented, not reused

`EXP-0101`'s baseline was written with summariser and implementer held by **one
agent**, a departure from §15.3 recorded in
`EXP-0101/receipts/clean-room-provenance.json`.

For `EXP-0101B` the chain is required:

```
paper → requirements-only summary → separate implementer → independent implementation
```

**The new implementer must not be shown `baseline_xversion.py`, any other file
from the EXP-0101 implementation, or that session's transcript.** Contamination
cannot be undone; only the contaminated role can be replaced.

If the two implementations disagree, **both are kept and the disagreement is
analysed.** It is evidence about how underdetermined the published requirements
are, and deleting the first would destroy it. `EXP-0101B`'s baseline becomes the
externally usable canonical one; `EXP-0101`'s remains exploratory and internal.

---

## 8. Gates

The six of §0.5, plus Contract A's three, plus one this result forces:

| gate | rule |
|---|---|
| 1 quality non-regression | semantic-change recall ≥ CURRENT |
| 2 catastrophic failure non-regression | zero critical false merges; CURRENT's fail-closed paths preserved |
| 3 latency/cost budget | **primary: `layout_only_false_invalidation_rate` ≤ CURRENT.** See §8.1 |
| 4 reproducibility | frozen manifest reproduces every metric; deterministic components bit-exact |
| 5 permission/security invariants | not engaged; state it rather than claiming a pass |
| 6 license/FTO | clean-room evidence per §7; **design-around review for external language is owed and BLOCKS external use** |
| A-i | critical semantic mutation recall ≥ CURRENT on the high-risk set, target 1.0 |
| A-ii | zero critical false merges |
| A-iii | ambiguous stays reviewable, never silently merged |
| **A-iv** | **figure replacement recall ≥ CURRENT.** EXP-0101 scored 0.0000 here; a restructure that does not fix it has not addressed the corollary |

### 8.1 Two gates EXP-0101 passed for the wrong reason

Do not read a pass on these without checking the mechanism.

`mean_rebuild_fraction` was **1.0000 for every arm** that goes through
`akc_cir.semantic_diff`, so gate 3 was a tie at the worst possible value and
gate 2's equivalence held only because nothing was ever carried over. The cause
is registered as a separate engineering gap —
`DIAGNOSTIC_CONTRACT_DIAG_B_01.md` — and **is not fixed by this contract.**

Until that diagnostic completes, three claim states are permitted for selective
recompilation and no others, and every artifact touching it uses one:

| state | asserts | current |
|---|---|---|
| `IMPLEMENTED` | the mechanism exists in code | **yes** |
| `DEMONSTRATED` | a narrow recompilation benefit is proven | no |
| `NOT YET DEMONSTRATED` | neither shown end to end | **this is the state** |

**The cause of the 1.0 rebuild fraction is not settled and is not written down
as settled** until `DIAG-B-01` decomposes its four candidates by read-only
counterfactual. Family B §5 is finalised after that, not before.

---

## 9. Reproducibility package

`research/experiments/EXP-0101B/`, §0.10 structure exactly. Raw evidence follows
the discipline EXP-0101 established:

```
raw evidence → deterministic compression → sha256 manifest → receipt
```

Both digests recorded — the raw one defines the evidence, the compressed one
detects a swapped artifact — with byte count, record count, schema version and
experiment id, so the manifest is unchanged if the artifacts later move to object
storage. **Raw evidence is never discarded, and least of all because a result is
unfavourable.**

---

## 10. FTO

Unchanged from Contract A. The *diff → dependency → impact → rebuild* narrative
approaches the generic expression of `tech_palantir_propagated_deletion` and
`tech_palantir_universal_data_pipeline` (RED). This experiment changes neither
module. Documentation and any external language pass design-around review;
`tech_xversion_diff` clean-room evidence per §7.

The ledger entry is **`ABS-B-01`**, extended rather than reopened: `why_changed`
is immutable and stands, and this contract is an **amendment appended** to it,
never an overwrite. `gate_status` stays `CLAIM_CHART_DONE`.

**Filing and publication timing is the founder's alone.**

---

## Acceptance — how this file is graded

1. Zero code, migration or schema change; zero YELLOW source snippets.
2. The canonical finding appears in the words of record.
3. The corollary is present, with the 0/20 · 0/20 · 0/20 · 20/20 evidence, and
   binds the redefinition of structural compatibility.
4. The content-derivation test is a stated requirement with a test obligation.
5. Every CURRENT claim carries a `file:line` citation matching HEAD.
6. `layout_only_false_invalidation_rate` is named the primary cost metric and
   the false-positive rate is never reported alone.
7. The falsifier ablation — content re-added to identity — is mandatory.
8. §7's clean-room chain is binding and names what the new implementer may not
   see; disagreement keeps both results.
9. Gate 8.1 states the three permitted claim states — `IMPLEMENTED`,
   `DEMONSTRATED`, `NOT YET DEMONSTRATED` — and which one currently applies.
10. Every metric carries its denominator; statistics state the paired design,
    the test, and multiple-comparison handling.
11. No sentence anywhere concedes that this work falls inside a third party's
    patent scope, and none characterises the scope of any particular patent
    claim. That analysis happens outside the repository under counsel privilege.
