# The measurement layer was defective, and the evidence was re-measured

A confirmatory result is a claim about the world made through an instrument. This
records a defect found in that instrument *after* the confirmatory test had run,
what was done about it, and what the same frozen evidence says once the
instrument is repaired.

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

**Nothing about the experiment changed.** The model outputs are the same two
frozen 800-page runs, byte for byte. The gate, its operating point, the
severe-error definition, the holdout membership, the statistical test and α are
all exactly as pre-registered. The only thing replaced is the device that turns
a prediction into a score.

---

## 1. The defect

The evaluator chose **which matching algorithm to run** from a wall-clock
timeout. `func_timeout(match_timeout_sec, match_gt2pred, …)` abandoned the exact
matcher after 90 seconds and substituted a chunked Hungarian approximation with
an order penalty; `deal_with_truncated` had its own deadline underneath.

Whether a page exceeded either depends on how busy the machine was. So the same
prediction bytes could be scored by two different algorithms on two runs.

Measured, by scoring both frozen runs and comparing pages whose predictions were
byte-identical:

| quantity | value |
|---|---|
| byte-identical pages whose score moved | **15** |
| of those, hit a timeout fallback in ≥1 run | 11 |
| byte-identical pages whose **severe label flipped** | **5** |
| pages that fell back in run 1 / run 2 | 34 / 28 |
| pages that fell back in exactly one run | 12 |

## 2. Why this was not merely a limitation

The first write-up of the confirmatory result argued:

> the gate never reads the evaluator, so the noise is independent of the
> accepted/abstained split; independent misclassification attenuates an
> association toward the null rather than manufacturing one; therefore the
> p-value is conservative.

**The premise does not follow.** The gate not *reading* the evaluator makes it
independent of the evaluator's output, not of the evaluator's **failure mode**.
Both the gate's decision and the matcher's running time are functions of the same
page, and pages with many elements in disordered reading order are plausibly both
slow to match and likely to be abstained on.

So it was tested rather than argued (`receipts/fallback-independence-2026-08-18.json`):

| | fallback | no fallback | rate |
|---|---|---|---|
| accepted | 24 | 624 | **3.70%** |
| abstained | 13 | 88 | **12.87%** |

**Fisher exact, two-sided, p = 0.00050.** The fallback is *not* independent of the
gate — abstained pages hit it 3.5× as often. It is also strongly associated with
the outcome itself (p < 10⁻⁶): pages that fell back are far more likely to be
labelled severe.

A measurement error that tracks **both** the exposure and the outcome is a
confounder, not benign noise. It can bias in either direction, and the
attenuation argument gives no protection at all. That is what made this a defect
in the primary endpoint rather than a footnote, and why the evidence had to be
re-measured.

The original claim was wrong, and it was wrong in the direction of
self-reassurance. It is left in the record with this correction attached.

## 3. The repair

`benchmark/datasets/private/evaluator-checkouts/omnidocbench-deterministic-v1`,
derived from the frozen checkout at `193627ae9e97`.

The fix removes wall-clock from the decision **entirely** rather than making the
approximation deterministic. Under an opt-in `deterministic_matching: true`, the
exact matcher runs to completion on every page: the outer `func_timeout` wrapper
is bypassed and the inner truncation deadline is disabled.

Bypassing rather than enlarging the wrapper matters — `func_timeout` runs the
callable on a timer thread, which is itself a scheduling-dependent path even
with a generous limit.

This choice has a property a deterministic *budget* would not: there is **no
threshold to pick**, so there is no opportunity to pick one that flatters the
result. Every page is scored by the same exact algorithm.

| | |
|---|---|
| version | `omnidocbench-deterministic-v1` |
| derived from | `193627ae9e97d89188468ed1ee3b7a856ff76044` |
| files changed | **1** (`src/dataset/end2end_dataset.py`) |
| lines added / removed | 18 / 1 |
| metrics, thresholds, cost functions, normalisation changed | **none** |
| default path | unchanged, so pre-correction artifacts stay reproducible |

Full unified diff and per-file hashes:
`receipts/evaluator-version-deterministic-v1.json`.

**How to reconstruct it.** Both checkouts are git-ignored, as third-party code
under `benchmark/datasets/private/` is throughout this repository, so the
corrected evaluator is not carried in the tree. Rebuild it by copying the frozen
checkout at `193627ae9e97` and applying the unified diff in the receipt; the
receipt's `python_source_sha256` over every `.py` file, in sorted path order,
verifies the result. That hash is what binds a number to the instrument that
produced it — not the presence of a directory on one machine.

The cost of exactness is time, not correctness: pages that used to be cut off at
90 seconds take 120–210 seconds to finish properly.

## 4. What was verified before the corrected instrument was used

`receipts/evaluator-determinism-2026-08-18.json`. The same 800 predictions are
scored repeatedly under the conditions that used to change the answer — repeated
evaluation, different worker counts, and reversed page order — and the per-page
scores and derived severe labels must be **bit-identical**, compared by hash
rather than by tolerance. A tolerance would defeat the purpose: the claim is not
that the answers are close, it is that scoring is a function of its input.

Zero timeout-fallback lines is part of the contract. Hashes agreeing while a
fallback fired would be luck, not determinism.

Measured over three full evaluations of all 800 pages:

| evaluation | workers | page order | pages scored | severe | fallbacks |
|---|---|---|---|---|---|
| 0 | 4 | forward | 790 | 50 | 0 |
| 1 | 2 | reversed | 790 | 50 | 0 |
| 2 | 4 | forward (repeat) | 790 | 50 | 0 |

**Distinct per-page score hashes: 1. Distinct severe-label hashes: 1.**

The count of fallbacks is taken from two independent places — the captured log
and the evaluator's own `stage_execution.json`, which also records that both
timeout fields were `null`. The log alone was not enough: a capture thread died
during one of these runs (an unrelated locale defect in the environment probe),
and a log-only check reads zero just as happily when the log is missing as when
nothing fired. A run that cannot produce its own record is now treated as
unverified rather than as clean.

## 4a. The claim that could have been false, and was not

"Only the wall-clock decision was removed" has a testable consequence: a page
that never hit a fallback ran the exact matcher under both evaluators, so its
score cannot move. If one did, the correction touched something else and the
case for re-measuring collapses. `correction_locality.py` checks it and refuses
rather than reports.

Measured on Run #1 (`receipts/correction-locality-2026-08-18.json`):

| quantity | value |
|---|---|
| pages compared | 790 |
| fell back under the frozen evaluator | 34 |
| fell back under the corrected evaluator | **0** |
| scores that moved | 30 |
| of those, had fallen back | **30** |
| **moved with no recorded fallback** | **0** |
| fell back but score unchanged | 4 |
| severe labels | **58 → 50** |

The correction changed exactly the pages it was capable of changing, and nothing
else. The four pages that fell back without moving are the honest reason the
aggregate barely shifts: on those, the approximation happened to agree with the
exact matcher.

The direction is worth stating plainly before the endpoint is recomputed. The
approximation was **inflating** severe counts — 8 pages labelled severe under it
are not severe under exact matching — and the fallback was already measured to
concentrate in the abstained arm. Those two facts together mean the
pre-correction reading may have been biased *toward* the hypothesis, which is
precisely the possibility that made this a defect rather than a footnote.

## 5. Results

The same frozen evidence, measured before and after the repair.
`receipts/evaluator-correction-comparison-2026-08-18.json`.

| quantity | frozen evaluator | deterministic evaluator |
|---|---|---|
| pages tested | 749 | 749 |
| accepted / severe | 648 / 42 | 648 / **38** |
| abstained / severe | 101 / 16 | 101 / **12** |
| accepted severe rate | 6.48% | **5.86%** (Wilson 4.30–7.95) |
| abstained severe rate | 15.84% | **11.88%** (Wilson 6.93–19.63) |
| risk difference | 9.36pp | **6.02pp** |
| 95% CI on the difference (bootstrap) | 2.39 to 16.75pp | **−0.21 to 12.79pp** |
| Fisher exact, two-sided | p = 0.0025 | **p = 0.0317** |
| total severe | 58 | **50** |
| coverage | 86.52% | 86.52% |
| **gate decisions that changed** | — | **0** |
| fallback rate, accepted | 3.40% | **0** |
| fallback rate, abstained | 11.88% | **0** |

**The pre-registered null is still rejected.** Fisher exact two-sided
p = 0.0317 against α = 0.05, in the direction observed on the discovery set, one
test at the frozen operating point. The confirmatory claim stands on the
corrected instrument.

**It stands on materially weaker evidence than the first reading suggested, and
that has to be said in the same breath.** The p-value moved by an order of
magnitude, the effect fell by about a third, and the 95% interval on the risk
difference now **includes zero**. The decision rule and the interval disagree
because they are different procedures — Fisher conditions on the margins, the
percentile bootstrap resamples a 101-page arm — and the pre-registered primary
endpoint is the Fisher test. So the *association* survives; a claim about its
*magnitude* does not.

### The mechanism, quantified

Every one of the 8 label changes ran the same way: **severe → not severe**. The
approximation never invented a clean page, it only ever manufactured a dirty
one. Four landed in each arm — and that is the whole story, because the arms are
not the same size:

| | flips | arm size | rate change |
|---|---|---|---|
| accepted | 4 | 648 | −0.62pp |
| abstained | 4 | 101 | **−3.96pp** |

The abstained arm absorbed six times the rate change from the same number of
corrections, because the fallback fired there 3.5× as often. **35.7% of the
originally measured effect was an artefact of the measurement defect**, and it
was an artefact pointing in the direction that flattered the hypothesis.

This is exactly the failure mode the retracted attenuation argument said could
not happen.

### What this changes downstream

- The confirmatory claim is **sealed on the corrected column**, at p = 0.0317.
- Any statement of effect *size* — "roughly 9pp", "the effect is about half the
  discovery contrast" — is withdrawn. The corrected interval is compatible with
  a very small effect.
- The pre-correction numbers are not deleted. They are the first reading of a
  defective instrument, and they stay next to the second so the difference
  between the two is auditable rather than invisible.

## 6. Why this is not holdout reuse or post-hoc tuning

The distinction that matters:

- **Holdout reuse** would mean looking at the outcome and then changing the
  gate, the operating point, the endpoint or the corpus. None of those moved.
  The gate's accept/abstain decision for every page is a function of prediction
  bytes only, and those bytes are unchanged, so the partition is identical.
- **Post-hoc tuning** would mean adjusting something until the answer improved.
  The repair has no free parameter to adjust — it removes an approximation
  rather than retuning one — and it was specified, implemented and verified
  before the corrected numbers were computed.

What did happen: a defect was found in the measuring device, demonstrated to be
correlated with the comparison being measured, and the same frozen evidence was
measured again with the device repaired. Both readings stay on the record.

The commitment made before running it, and kept: **if the result had not
survived the correction, that would have been the finding.** The instrument does
not get adjusted a second time to recover a p-value.
