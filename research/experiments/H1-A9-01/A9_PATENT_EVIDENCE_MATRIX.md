# A9 patent evidence matrix

Maps each A9 claim element to the artifact that supports it and the strength of
that support. This is an internal evidence ledger, **not** a claim chart and not
a filing recommendation.

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`. What a public
claim says, and whether evidence supports it, is the founder's decision.

## Support levels

| level | meaning |
|---|---|
| `WORKED_EMBODIMENT` | code exists, runs, and its behaviour is pinned by tests |
| `MEASURED_EXPLORATORY` | measured on the discovery set; operating point chosen after seeing it |
| `MEASURED_CONFIRMATORY` | measured once on an untouched holdout under a pre-registered protocol |
| `NOT_SUPPORTED` | tested and failed; retained because a failed hypothesis is evidence |
| `WITHDRAWN` | previously claimed, since retracted, with the reason recorded |

---

## Elements

| # | claim element | support | artifact |
|---|---|---|---|
| A9-E1 | An acceptance gate that abstains on a per-page basis rather than accepting all output | `WORKED_EMBODIMENT` | `confirmatory_test.py`, `r4_marginal_analysis.py` |
| A9-E2 | Abstention driven by **execution instability** — byte-level disagreement between two runs of the same immutable assembly at temperature 0 | `MEASURED_CONFIRMATORY` as part of the combined gate; `MEASURED_EXPLORATORY` standalone | discovery `confidence-proxy-arm-2026-08-18.json` (18/198 unstable, p = 0.0151); confirmatory `r4-confirmatory-deterministic-2026-08-18.json` (32/749 unstable, ARR 0.40pp, 5 severe caught, standalone Fisher p = 0.055 — **not significant alone**) |
| A9-E3 | Abstention driven by cross-parser **critical-token disagreement**, not text similarity | `MEASURED_EXPLORATORY` | `selective-acceptance-two-parser-2026-08-18.json` |
| A9-E4 | The two signals are complementary rather than redundant | **`MEASURED_CONFIRMATORY`** | `r4-confirmatory-deterministic-2026-08-18.json`; flagged-page Jaccard 0.067 on 749 holdout pages, +6 severe errors from adding agreement to stability and +5 the other way; **all 11 jointly caught are caught by exactly one — the intersection is empty** |
| A9-E5 | The acceptance decision never reads the correctness outcome | `WORKED_EMBODIMENT` | anti-circularity is structural: gates read predictions only; the evaluator is a separately frozen revision `193627ae9e97`, re-measured by its deterministic correction `omnidocbench-deterministic-v1` with **0 gate decisions changed** |
| A9-E6 | Fail-closed on an unavailable signal — a page the gate cannot evaluate is abstained, never accepted | `WORKED_EMBODIMENT` | `A9_PROTOCOL_AMENDMENT_01_2026-08-18.md`, implemented in `confirmatory_test.py` |
| A9-E7 | Cost-tiered operation: distinct gates at distinct GPU cost with measured marginal utility | **`MEASURED_CONFIRMATORY`** | `R4_OPERATING_TIERS_2026-08-18.md` confirmatory section; three tiers at $0.96 / $1.92 / $3.15 per 1,000 pages with monotonically rising cost per error avoided ($0.103 then $0.202) |
| A9-E8 | Selective acceptance reduces severe-error rate on unseen data | **`MEASURED_CONFIRMATORY` for the association; `NOT_SUPPORTED` for any effect size** | `confirmatory-result-deterministic-2026-08-18.json`; 749 pages, 5.86% accepted vs 11.88% abstained, Fisher exact p = 0.032, one pre-registered test. The bootstrap 95% CI on the rate difference is −0.21 to 12.79pp and **includes zero**, so no magnitude may be claimed |
| A9-E9 | Output-only internal-consistency checking as an acceptance signal | `WITHDRAWN` | fired on LaTeX math delimiters; corrected instrument detects none of nine semantic corruptions and has an 8.5% false-positive rate on ground truth |
| A9-E10 | Structural validity of emitted tables as an acceptance signal | `NOT_SUPPORTED`, and **harmful on the holdout** | discovery: flags 2/198, confounded with table count (14.7 vs 0.22 mean tables). Confirmatory: absolute risk reduction **−0.53pp** — the pages it flags are cleaner than the ones it accepts. Must not be shipped |
| A9-E11 | Source-grounded acceptance on scans via OCR-independent ink coverage | `NOT_SUPPORTED` | `ink-coverage-verifier-2026-08-18.json`; top decile contains zero severe errors, p = 0.62 |
| A9-E12 | Model self-confidence as an acceptance signal | `WITHDRAWN` — abandoned | the frozen runtime emits none and the preregistration forbids reconstructing one |

## Instrument-validation elements

These support the *method*, not the gate, and are what distinguishes a measured
claim from an asserted one.

| # | element | support | artifact |
|---|---|---|---|
| A9-V1 | Instrument measurement unit provably identical to the official evaluator's | `WORKED_EMBODIMENT` | `test_evaluator_alignment_contract.py` executes the evaluator's own extractor and diffs it |
| A9-V2 | Sensitivity validated against injected **semantic** corruption — number, sign, date, unit, entity loss, row/column swap, cell omission, duplicated cell | `WORKED_EMBODIMENT` | `evaluator-aligned-instruments-2026-08-18.json` |
| A9-V3 | False-positive rate measured against human-annotated ground truth as a negative control | `WORKED_EMBODIMENT` | same; reference-based instrument FPR 0.000 |
| A9-V4 | Holdout provenance auditable at page and document level, with leakage instruments themselves validated | `WORKED_EMBODIMENT` | `holdout-provenance-audit-*.json`, `confirmatory-holdout-800-*.json`, `test_holdout_provenance_contract.py` |
| A9-V5 | Discovery/confirmatory separation enforced by a hash-sealed manifest | `WORKED_EMBODIMENT` | `discovery-set-seal-2026-08-18.json` |
| A9-V6 | The confirmatory denominator's exclusions are decided by ground truth alone, verified rather than asserted | `WORKED_EMBODIMENT` | `scored-page-criterion-2026-08-18.json`; reproduces the evaluator on 800/800 pages, reads no prediction |
| A9-V7 | Execution integrity is auditable: every controller attempt is recorded, and the instrument refuses if more than the pre-registered number reached inference | `WORKED_EMBODIMENT` | `holdout-execution-log-2026-08-18.json` |
| A9-V8 | The single-use confirmatory test is verified on synthetic fixtures before its one execution | `WORKED_EMBODIMENT` | `test_confirmatory_test_arithmetic.py`; partition, severe attribution, fail-closed branch and rates checked against hand-computed values |
| A9-V9 | **Outcome scoring is a deterministic function of its input** — no wall-clock value may select the scoring algorithm | `WORKED_EMBODIMENT` | `omnidocbench-deterministic-v1`; `evaluator-determinism-2026-08-18.json`: identical per-page score and label hashes across repeated evaluation, 4 versus 2 workers and forward versus reversed page order, zero fallbacks in both the logs and the evaluator's own execution record |
| A9-V10 | Measurement error is tested for **dependence on the exposure** rather than assumed independent | `WORKED_EMBODIMENT` | `fallback-independence-2026-08-18.json`; the scoring fallback fired on 12.87% of abstained against 3.70% of accepted pages, Fisher exact p = 0.00050 — the finding that required the instrument to be corrected and the evidence re-measured |
| A9-V11 | An instrument correction is bounded and falsifiable: only pages the defect could have touched may change | `WORKED_EMBODIMENT` | `correction-locality-2026-08-18.json`; of 790 pages, 30 moved score and **all 30** had fallen back, none outside; `evaluator-version-deterministic-v1.json` publishes the full 1-file, 18-line diff |

## Why the validation elements carry weight here

A9-V1 through A9-V8 are not supporting material for the gate; on this record they
are the more defensible half. Two instruments in this work were wrong in ways
that changed a conclusion — an evidence rule matching LaTeX math delimiters, so
that a "signal" was selecting formula-dense pages and reached p = 0.0014 on the
way to being named primary; and a 64-bit perceptual hash that could not
distinguish unrelated scanned pages and refused a corpus freeze on 19 spurious
pairs. Neither was caught by review or by sensitivity testing. Both were caught
by negative controls and by measuring the instrument against a reference.

That is the element worth claiming: not that these particular signals work, but
that an acceptance-gate pipeline can be built so its own measurement apparatus
is falsified before its outputs are believed.

## What is deliberately absent

- No claim that any threshold here is calibrated. `CalibrationTable.calibrated`
  remains `False`.
- No comparison against a public leaderboard row.
- No retail price beside a GPU cost.
- No claim that the gate detects semantic corruption from output alone. It does
  not: number, sign, date and unit changes are detectable only by comparison
  against a second transcription, which is exactly why the second parser cannot
  be removed.
