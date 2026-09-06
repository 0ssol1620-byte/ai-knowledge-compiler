# Protocol amendment 02 — deterministic evaluator, and re-measurement of the frozen evidence

**Recorded after the primary test had run and its result was known.** That is the
opposite of amendment 01's standing, and the difference is stated up front rather
than buried: this is not a pre-specification. It is a repair to a measuring
instrument that was found to be defective, and it has to be judged on whether the
repair could have been steered toward a preferred answer.

## What went wrong

The evaluator selected **which matching algorithm scored a page** using a
wall-clock timeout. Identical prediction bytes could therefore be scored by the
exact matcher on one run and by a chunked approximation on another, depending on
how loaded the machine was.

Measured on the frozen holdout: 15 byte-identical pages scored differently across
the two evaluation runs, and 5 of them flipped the severe label.

## Why that could not be recorded as a limitation and left there

The original write-up argued the noise was harmless — the gate never reads the
evaluator, so the misclassification is independent of the accepted/abstained
split, and independent outcome misclassification attenuates an association toward
the null.

**That argument was wrong.** Independence from the evaluator's *output* is not
independence from its *failure mode*. The gate's decision and the matcher's
running time are both functions of the same page.

Tested rather than argued:

| | fallback | no fallback | rate |
|---|---|---|---|
| accepted | 24 | 624 | 3.70% |
| abstained | 13 | 88 | 12.87% |

Fisher exact, two-sided, **p = 0.00050**. The fallback also tracks the outcome
itself. Measurement error correlated with both the exposure and the outcome is a
confounder of the primary endpoint; it can bias in either direction, and the
attenuation argument offers no protection. `receipts/fallback-independence-2026-08-18.json`.

## The amendment

1. A corrected evaluator, `omnidocbench-deterministic-v1`, in which no wall-clock
   value influences which algorithm scores a page: the exact matcher runs to
   completion on every page. The outer `func_timeout` wrapper is bypassed rather
   than enlarged, because running the matcher on a timer thread is itself a
   scheduling-dependent path.
2. The frozen 800-page Run #1 and Run #2 are re-scored with it.
3. The primary confirmatory Fisher test is recomputed under the **identical**
   protocol — same holdout, same gate, same operating point, same severe-error
   definition, same test, same α.
4. Both readings are reported side by side. The pre-correction result is not
   replaced.

## What did not change, and can be checked rather than trusted

| | |
|---|---|
| model outputs | the same two frozen runs, byte for byte |
| gate and operating point | unchanged; `gate_decisions_that_changed` must be 0 |
| severe-error definition | text-block edit distance > 0.10 |
| holdout membership | unchanged; no page added, dropped or re-selected |
| statistical test and α | Fisher exact two-sided, α = 0.05, one test |
| evaluator metrics, thresholds, cost functions, normalisation | unchanged; the diff is 1 file, 18 lines, and is published in full |

## Why this is not holdout reuse, and why that is a real distinction

Holdout reuse means letting the outcome influence the gate, the operating point,
the endpoint or the corpus. None of those moved. The gate's decision for each
page is a function of prediction bytes alone, and those bytes are unchanged, so
the accepted/abstained partition is bit-identical.

Post-hoc tuning means adjusting something until the answer improves. **The repair
has no free parameter to adjust.** It removes an approximation rather than
retuning one — there is no timeout budget, no tolerance, no threshold that could
have been set to flatter the result. That property was chosen deliberately over
the alternative repair (a deterministic page-count budget instead of a
wall-clock one), which would have worked but would have introduced exactly such
a knob.

The correction was specified, implemented and verified deterministic **before**
the corrected confirmatory number was computed.

## The falsifiable half

The claim "only the wall-clock decision was removed" implies a testable
consequence: a page that never hit a fallback ran the exact matcher under both
evaluators, so its score cannot move. `correction_locality.py` checks exactly
that and refuses if any page moved without a recorded fallback. If it refuses,
this amendment's justification is void and the re-measurement must not be used.

## The commitment, made before the corrected number was known

If the primary result does not survive the corrected instrument, **that is the
finding.** The evaluator is not adjusted a second time to recover a p-value, and
the pre-correction result is not preferred because it was first.

## Scope

This amendment governs the instrument only. Everything else in
`A9_CONFIRMATORY_PROTOCOL_2026-08-18.md` revision 2 and amendment 01 stands
unchanged.

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.
