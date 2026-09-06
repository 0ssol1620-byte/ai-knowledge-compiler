# Protocol amendment 01 — missing second-parser predictions

**Recorded before any holdout inference completed and before any holdout outcome
was computed.** That ordering is the whole point of the document: this is a
pre-specification, not an adjustment.

## The gap

The frozen gate has two halves. The stability half needs two runs of the gated
parser, which the holdout will produce. The agreement half needs a second-parser
prediction for the same page, and those come from the frozen public campaign
`folynta-mineru344-quality-candidate-merged-2026-08-09` — verified as the
discovery arm's source by hashing all 200 discovery predictions against every
candidate campaign directory (200/200 byte-identical; every other candidate
matched only 199).

That campaign covers **784 of the 800** frozen holdout pages. Sixteen have no
second-parser prediction.

## The rule, fixed now

**A page with no second-parser prediction is abstained.**

Fail closed, per the repository's own constitution: *"No silent fallback. A
component that cannot do its job says so."* The agreement half cannot evaluate
those pages, so the gate refuses them rather than accepting them by default.

## Why this is conservative, stated so it can be checked

Abstention moves those 16 pages into the abstained arm. Their expected severe-
error rate is the corpus base rate — roughly 6% on the discovery set — which is
well below the abstained arm's expected rate of about 18%. Adding them therefore
**dilutes** the abstained arm and shrinks the measured contrast.

The amendment can only make the primary test harder to pass. If it rejects
anyway, the amendment did not manufacture the result.

## Alternatives considered and rejected

- **Run MinerU on the 16.** Would need a second parser runtime stood up for
  sixteen pages, and any new MinerU build is a different second parser from the
  frozen one the discovery arm used — changing the gate mid-experiment.
- **Drop the 16 from the holdout.** Selecting the analysis set on data
  availability after the freeze. Availability is plausibly independent of the
  outcome, but "plausibly independent" is exactly the argument a post-hoc
  exclusion always makes, and the freeze exists so that argument never has to be
  trusted.
- **Accept them ungated.** Puts pages the gate cannot evaluate into the accepted
  arm, which is the direction that would flatter the result.

## Scope

This amendment governs the primary endpoint only. Secondary analyses report the
16 pages separately so their contribution is visible rather than folded in.

Nothing else in `A9_CONFIRMATORY_PROTOCOL_2026-08-18.md` revision 2 changes.
