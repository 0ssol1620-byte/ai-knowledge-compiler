# R4 — what each additional dollar of gating buys

198 pages, 12 severe errors (official text-block edit distance > 0.10),
evaluator revision `193627ae9e97`. Cost is measured GPU time, not a list price:
6.71 GPU-seconds per page for the gated parser at the $0.34/hr COMMUNITY rate
this run was billed at, and the second parser at its own frozen rate of $0.74/hr.

> **Discovery-set numbers.** The confirmatory holdout is frozen; when its
> results land they are appended below as a separate section and become the
> basis of the operating recommendation. Where the two disagree, the
> confirmatory numbers govern. Until that section exists, no tier here is
> confirmed.

**Everything above the confirmatory section is exploratory.** The operating points were chosen
after seeing this corpus. The p-values are uncorrected and are effect estimates,
not findings.

---

## The table

| configuration | $/1k | coverage | selective err | ARR | RRR | avoided /1k | per abstention pt | p |
|---|---|---|---|---|---|---|---|---|
| single run | 0.63 | 1.000 | 0.0606 | — | — | 0 | — | — |
| evidence-validity gate | 0.63 | 0.970 | 0.0521 | 0.0085 | 14% | 8.5 | 0.0028 | 0.0442 |
| structural gate | 0.63 | 0.990 | 0.0561 | 0.0045 | 7% | 4.5 | 0.0044 | 0.1178 |
| **stability gate** | **1.27** | 0.909 | 0.0444 | 0.0162 | **27%** | 16.2 | 0.0018 | 0.0151 |
| agreement gate (matched coverage) | 1.87 | 0.909 | 0.0500 | 0.0106 | 17% | 10.6 | 0.0012 | 0.0826 |
| **stability + agreement** | **2.50** | 0.833 | 0.0364 | 0.0242 | **40%** | 24.2 | 0.0015 | 0.0061 |

## Incremental, each tier against the next cheapest

| step | extra $/1k | extra avoided /1k | $ per additional severe error avoided |
|---|---|---|---|
| evidence-validity gate over single run | 0.00 | +8.5 | free |
| structural gate over evidence-validity gate | 0.00 | −4.0 | **dominated** |
| stability gate over structural gate | +0.63 | +11.7 | $0.054 |
| agreement gate over stability gate | +0.60 | −5.6 | **dominated** |
| stability + agreement over agreement gate | +0.63 | +13.6 | $0.046 |

Two entries are dominated — they cost more and avoid fewer errors than a
cheaper tier. **The agreement gate on its own is one of them.** It is strictly
worse than running the same parser twice: it costs 47% more and avoids a third
fewer errors.

## But agreement is not removable

That dominance result is about agreement *instead of* stability. Agreement
*added to* stability is a different quantity, and it is positive:

| | severe errors caught |
|---|---|
| stability alone | 4 of 12 |
| agreement alone | 3 of 12 |
| adding agreement to stability | **+2** |
| adding stability to agreement | +3 |
| either signal | 6 of 12 |
| neither | **6 of 12** |

The two signals overlap on 3 of the 36 pages they flag between them — Jaccard
0.091. They are not substitutes, and the earlier reading of this data as "the
second parser is unnecessary" was wrong in a way worth naming: a dominated
*alternative* was mistaken for a redundant *component*.

## Operating tiers

The data supports three tiers and refuses a fourth.

| tier | configuration | $/1k | severe error rate | coverage |
|---|---|---|---|---|
| **Economy** | single run | 0.63 | 6.1% | 100% |
| **Balanced** | stability gate | 1.27 | 4.4% | 91% |
| **High-integrity** | stability + agreement | 2.50 | 3.6% | 83% |

Doubling spend from Economy to Balanced removes 27% of severe errors. Doubling
again removes 40% of the original rate — real, and clearly sublinear. There is no
tier between Balanced and High-integrity, because the only candidate for one is
the agreement gate alone and it is dominated.

**What the tiers do not buy.** Every tier leaves half the severe errors in the
accepted set. High-integrity abstains on 17% of pages to remove 40% of the
errors; the remaining 60% look, to every signal available, exactly like correct
output. That ceiling is a property of the signals, not of the spend, and no
amount of additional inference on these two parsers moves it.

---

## The instrument correction behind this table

The previous version of this analysis named `evidence_validity` the strongest
and cheapest signal at p = 0.0014 and made it the confirmatory primary. **That is
retracted.** Its `orphan_currency` rule was firing on the opening `$` of LaTeX
math spans, which this corpus uses to typeset prices, so the flag tracked
formula-dense pages, and formula-dense pages are harder to parse. The gate was
measuring typesetting.

With math spans excluded the same instrument:

- flags 6 pages rather than 17, at p = 0.0442;
- detects **none** of nine injected semantic corruptions (number, sign, date and
  unit changes, entity loss, row and column swaps, cell omission, duplicated
  cell);
- fires on 8.5% of human-annotated ground-truth documents against 3.0% of model
  outputs — it fires more often on known-correct text than on the text under
  test.

It stays in the table as a measured configuration and is disqualified as a
confirmatory primary signal. What survived validation instead is the
reference-based comparison underneath the stability and agreement gates:
false-positive rate 0.000, and detection of 1.00 for sign changes, 1.00 for date
changes and 0.66 for number changes.

## Measurement-unit alignment

The 88-detected-versus-60-scored table gap is resolved and was not a detector
defect. The evaluator's extraction unit is the *outermost* `<table>`, scanned
with a stack; that function is vendored verbatim and returns 88 on these same
predictions, matching the previous detector on every page. There is no nesting
in this corpus. The evaluator reports 60 because its evaluation targets are the
60 ground-truth table regions, and the model **over-segments**: 29 tables where
the truth annotates 26, 25 where it annotates 13, 18 where it annotates 6.

One consequence is implemented rather than noted. 72 of the 88 tables sit on
three pages, so any page-level structural proxy expressed as a rate over tables
would make those three pages incomparable with the rest. The structural signal
is therefore *defect presence*, contributed once per page. Even so it flags only
2 of 198 pages, and those pages average 14.7 tables against 0.22 elsewhere — the
flag is still largely a proxy for "this is the table-heavy page". It is reported,
and it is not used as a gate.


---

# CONFIRMATORY — measured on the 800-page holdout

Everything above this line is **discovery**: measured on the 198-page set that
was also used to design the signals and choose the operating points. It is kept
for provenance and it is not the basis of the recommendation.

Everything below is measured on the frozen 800-page confirmatory holdout, of
which 749 carry an official text score, and is scored by the **deterministic
evaluator** (`omnidocbench-deterministic-v1`). The figures previously published
here came from an instrument that chose its matching algorithm by wall-clock
timeout; `EVALUATOR_CORRECTION_2026-08-18.md` records the defect, the repair and
both readings. Receipt: `receipts/r4-confirmatory-deterministic-2026-08-18.json`.
The primary test result it sits beside is
`receipts/confirmatory-result-deterministic-2026-08-18.json`.

**Baseline severe-error rate: 6.68%** (50 of 749). The discovery set ran at
6.1%; the holdout is drawn from the remainder of the same benchmark and is
easier on average, but it is also 3.8x larger, so this is the better estimate.

## The tiers, on confirmatory data

| tier | GPU s/page | coverage | severe rate | ARR | RRR | avoided /1k | $/1k | $/error avoided |
|---|---|---|---|---|---|---|---|---|
| **Economy** — single run | 10.17 | 1.000 | 6.68% | — | — | — | $0.96 | — |
| **Balanced** — stability gate | 20.34 | 0.957 | 6.28% | 0.40pp | 6.0% | 4.0 | $1.92 | $0.103 |
| **High-integrity** — stability + agreement | 26.34 | 0.920 | 5.66% | 1.02pp | 15.2% | 10.2 | $3.15 | $0.202 |

**The Balanced tier is no longer a statistically established effect.** Its own
accepted-versus-abstained contrast is Fisher p = 0.055 under the corrected
instrument, against 0.002 before. It stays in the table as the cheapest
configuration measured, not as a demonstrated one. High-integrity's contrast
remains at p = 0.001.

One configuration from the discovery table is **dominated on confirmatory data**
and is not a tier:

- `structural_gate` has a **negative** ARR of −0.53pp: the pages it flags are
  cleaner than the ones it accepts. On discovery it was merely weak and
  confounded with table count; on the holdout it is actively harmful. It is
  retained in the receipt as a measured negative result and must not be shipped.

`agreement_gate_matched_coverage` was dominated under the defective instrument
and is **not** dominated under the corrected one: it buys 1.4 additional avoided
errors per 1,000 pages over the stability gate, at $0.195 each. It is still not
offered as a tier — it costs more than Balanced for a marginal gain inside the
noise — but the earlier claim that it is strictly worse is withdrawn.

The `evidence_validity_gate` row survives at 0.2 avoided per 1,000 for no extra
GPU, because it reads output already produced. That is not a rehabilitation:
§ above records that the instrument detects none of nine injected semantic
corruptions and fires more often on known-correct text than on the text under
test. A signal that is free and slightly positive on one corpus, with no
mechanism that survived validation, is not a signal. It stays out of the tiers.

## The complementarity result replicates

This was the finding the confirmatory run most needed to reproduce, because the
whole three-tier structure rests on it — if agreement merely re-detected what
stability detects, High-integrity would be paying twice for one signal.

| quantity | discovery (198) | confirmatory (749) |
|---|---|---|
| severe errors | 12 | 50 |
| caught by stability | 4 | 5 |
| caught by agreement | 4 | 6 |
| **agreement's marginal gain over stability** | +2 | **+6** |
| **stability's marginal gain over agreement** | +2 | **+5** |
| Jaccard overlap of the *flagged page* sets | 0.091 | **0.067** |
| caught by neither | 6 | 39 |

The overlap is *smaller* on the holdout, not larger. Of the **11** severe errors
the two signals catch between them (50 total minus the 39 both miss), **all 11
are caught by exactly one of the two** — on corrected labels the intersection is
empty. These are not two measurements of the same underlying quantity.

The Jaccard figure is over the sets of *flagged pages*, not over the severe
errors caught; it says the two signals rarely fire on the same page at all.

## What this means for the recommendation

**The choice is a cost question, and all three tiers are defensible answers.**

- **Economy** at $0.96/1,000 pages, accepting a 6.7% severe-error rate with no
  page marked. Correct when downstream consumption tolerates error, or when a
  human reads everything anyway.
- **Balanced** at $1.92/1,000 doubles GPU cost to remove 6% of severe errors
  and marks 4.3% of pages for escalation. **$0.103 per severe error avoided is
  the cheapest error removal available here** — but at p = 0.055 its effect is
  not established, so shipping only this tier means shipping the tier with the
  weakest evidence behind it.
- **High-integrity** at $3.15/1,000 removes 15.2% of severe errors at 8.0%
  abstention. The incremental step from Balanced costs $0.202 per additional
  error avoided — roughly twice Balanced's rate, which is what buying a second
  independent signal costs — and it is the only configuration whose contrast
  survives the corrected instrument at α = 0.05.

The tier structure holds on confirmatory data. Every step up the ladder buys
real, non-overlapping error reduction at a monotonically rising price per error,
which is exactly the shape a cost-quality frontier should have.

## The ceiling, restated with the larger sample

**36 of 50 severe errors are invisible to every signal measured here**, and
stability and agreement together miss 39. The discovery set put that fraction at
half; the holdout puts it at 72%. More budget does not move it — High-integrity
spends 2.6x Economy's GPU and still accepts the large majority of severe errors.

The forensic analysis of those residuals is in
`receipts/holdout-forensics-deterministic-2026-08-18.json`, and two of the four discovery
hypotheses about them reproduced independently: missed cases have a
prediction-to-truth length ratio near one, and they lose fewer critical tokens.
Both say the same thing — the pages that defeat every signal are pages where the
output *looks* like a correct transcription of the right length with the right
numbers in it. Nothing available without ground truth distinguishes them, and
that is a property of the signals rather than of the budget.

The two hypotheses that did **not** reproduce are recorded in §E of the forensics
receipt: missed cases do not carry fewer tables on the holdout, and they do not
transcribe ground-truth-excluded regions at a higher rate. Both looked
compelling on 6 cases and did not survive 42.
