# Ledger entry `ABS-B-01` — fields frozen before the measurement run

> **NOT CLEARED FOR EXTERNAL DISCLOSURE.** Gate 6 BLOCKED. Internal and
> exploratory use only until the role-separated reimplementation recorded in
> `clean-room-provenance.json` is complete.


*Deliverable for the IP track. **This file is not the ledger.** The canonical
entry is §7.2 of `docs/ip/INVENTION_DISCLOSURE_B.md` in the IP worktree
(`D:\CodexProjects\ai-knowledge-compiler-ip-research`), and this repository does
not write there — two worktrees editing one file collide. What follows is the
content that fills that entry's `PLANNED` fields, in its format, for the IP
track to carry across.*

**`why_changed` is not restated as new text.** It already exists in the ledger,
written before any result, and §0.6 makes it immutable. It is quoted below
verbatim so the paste is a fill rather than a rewrite.

---

## Authoring provenance — read this before trusting the tense

The five fields below describe a design that was fixed before any measurement.
They were **written to this file after** the harness had been exercised on 1-
and 4-document smoke runs, which is why this section exists rather than a bare
`why_written_before_result: true`.

What that means precisely:

- The design, the signal set, the weight share, and the predicted effect —
  including the predicted failure mode in `expected_technical_effect` — were
  settled from blueprint §9.2–§9.5 before any arm was executed.
- The predicted failure mode was reached by arithmetic on the published weights
  (`identity.py:231`) and the 0.92 bar (`identity.py:253`), not by observing an
  output.
- The smoke runs that preceded this file were on 4 of the 60 seed documents and
  were run to check that the harness executed, not to choose a design.
- No threshold, weight or rule was changed after any arm was scored. The one
  addition made after the smoke run was a **diagnostic ablation**
  (`challenger_no_content`), which adds a measurement and changes no arm.

An examiner should read `why_written_before_result` as **true for the design and
the prediction, with the writing-down lagging the design by the smoke runs
described here.** That is a weaker claim than the ledger's flag alone implies,
and it is the accurate one.

---

## `intake_id` · `classification` · `gate_status`

| field | value |
|---|---|
| `intake_id` | `tech_xversion_diff` (Heterogeneous Cross-Version Differencing impl) |
| `classification` | **YELLOW** — `CLEAN_ROOM_ONLY` (unchanged) |
| `gate_status` | `CLAIM_CHART_DONE` (unchanged — this experiment does not advance it) |
| `experiment` | Contract **A**. Path **`research/experiments/EXP-0101/`** — no longer `PLANNED` |
| `claim_elements_touched` | **B1**, **B2**, **B3/B4** (the abstention chain) — unchanged, and B3/B4 is where the result landed |

`gate_status` deliberately does not move. Contract A's FTO note requires
design-around review for **documentation and external language**, not for this
code, and no such review has been recorded. Nothing here is cleared for external
description.

## `prior_art_used` *(frozen)*

Requirement-level description of cross-version element alignment as published —
typed elements, spatial/structural/content compatibility, constrained one-to-one
assignment, per-type difference reasoning. Sources actually read, and the sources
deliberately not read, are itemised in
`research/experiments/EXP-0101/receipts/clean-room-provenance.json`.

**No implementation was consulted, copied, translated, ported or vendored.**
That receipt also records a real departure from §15.3: summariser and implementer
were one agent. It is written down rather than glossed, and it carries a founder
question.

## `what_changed` *(frozen — fills the ledger's `PLANNED`)*

An alignment layer supplies five additional signals — `align_type`,
`align_spatial`, `align_structural`, `align_content`, `align_context` — to the
existing seven-signal identity scorer, which keeps ownership of the final stable
id. The five carry 30% of total weight; the seven are scaled by 0.70 and keep
their ratios, so a pair with no alignment evidence scores exactly what CURRENT
scores. A separate type-specific reasoning pass classifies each `MODIFIED_CLAIM`
into modality / exception-scope / date / numeric / value-order / rendering-only /
text-edit, and only the last two are treated as not-a-meaning-change.

`akc_cir.identity` and `akc_cir.semantic_diff` are **unmodified**. The
challenger is a subclass in a package that is not in the wheel, behind
`ABSORB_ALIGNMENT_DIFF`, default false.

## `why_changed` *(immutable — quoted from the existing ledger, not rewritten)*

> Published alignment methods, including the strongest, **force an assignment**.
> A forced assignment asserts continuity that was not established, and the
> downstream cost is asymmetric: a wrongly-merged claim corrupts a history that
> may be real, while a wrongly-rebuilt artifact only costs compute. The change
> exists to make that asymmetry explicit rather than to improve alignment
> accuracy.

## `expected_technical_effect` *(frozen)*

Predicted before running, on the fixture's eleven mutation classes:

1. **Layout-only false semantic invalidation falls.** The exact-content
   candidate tier withholds the positional signals from a pair whose content is
   identical, so a re-render cannot vote against identity; and rendering-only
   demotion removes the `MODIFIED_CLAIM` that optical degradation currently
   produces.
2. **Critical semantic recall holds at CURRENT's level.** This was the
   prediction and it carried a named risk, below.
3. **Alignment F1 is not expected to move much**, because CURRENT's structural
   and neighbour signals already align most pairs; the alignment layer's value
   was expected to be in the *bands*, not the matching.

**Predicted failure mode, named in advance.** `align_content` is content-derived
and enters an identity score. `identity.py:186` states that content is
deliberately excluded from the identity seed *"so that a clause keeps its
identity when its wording changes -- which is the entire point."* Adding a
content signal to the scorer risks pushing genuine content edits below the 0.92
bar and converting a detected change into an abstention. Arithmetic on the
published weights put a pair at roughly 0.90 for a single numeric edit, which is
under the bar. This was accepted as the thing the experiment would measure, not
designed around.

## `design_rationale` *(frozen)*

Why this and not the alternatives:

- **Why signals into the existing scorer, rather than a parallel aligner whose
  output overrides identity.** Contract A and blueprint §9.6 both put the final
  stable-id assignment with `akc_cir.identity`, and Protected Core rules forbid
  replacing it. Feeding signals in also inherits availability-aware
  renormalisation and critical-signal abstention for free, which a parallel
  aligner would have had to reimplement and could have got wrong quietly.
- **Why a subclass in a package outside the wheel, rather than a flag inside
  `akc_cir`.** A flag inside the core package makes the core's behaviour depend
  on an experiment's state. Not shipping the code at all is a stronger statement
  than a default-false flag, and both are used.
- **Why no core signal is suppressed.** Suppressing one would be replacing the
  core's judgement rather than adding to it, and the contract says *additional*
  signals.
- **Why the alignment share is 0.30 and stays there.** Blueprint §9.4 says this
  layer's thresholds are uncalibrated and that this suite is what decides them.
  Sweeping the share against the same fixture the arms are scored on is what
  §0.9 forbids; a number tuned that way could not be reported afterwards.
- **Why the type reasoning demotes only two refinements.** `RENDERING_ONLY` and
  `VALUE_ORDER_CHANGE` are the only two where the evidence is that nothing was
  said differently. Everything else, including a suspected typo, is reported as
  a change, because nothing available here can prove a wording change is
  meaningless.

## `sources_read`

`research/experiments/EXP-0101/receipts/clean-room-provenance.json`, bound by
sha256 in `research/experiments/EXP-0101/receipts/receipts.json`.

## `why_written_before_result`

`true` **for the design and the prediction**, with the qualification in
*Authoring provenance* above. Do not paste the flag without that section.
