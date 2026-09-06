# A9 confirmatory protocol — frozen 2026-08-18 (revision 2)

Everything A9 has produced so far is exploratory. Operating points were chosen
after seeing the data, roughly 120 comparisons were made, and the best of them
does not survive correction for that. This document exists so that the next
measurement is not exploratory: it fixes, before any new page is scored, exactly
one hypothesis, one signal, one operating point and one test.

**Frozen means frozen.** After this file is committed, changing any numbered item
below invalidates the confirmatory status of the result. A changed item is a new
exploratory round, not a revision.

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`. What a public
claim says remains the founder's decision.

> **Revision 2 replaces the primary signal.** Revision 1 named
> `evidence_validity` on the strength of p = 0.0014 and a zero marginal cost.
> Instrument validation then showed that number was an artefact: the rule fired
> on LaTeX math delimiters, which this corpus uses to typeset prices, so it was
> selecting formula-dense pages. Corrected, it reaches p = 0.0442, detects none
> of nine injected semantic corruptions, and fires on 8.5% of human-annotated
> ground-truth documents against 3.0% of model outputs. It is disqualified.
> Section 9 records the retraction in full.

---

## 1. The discovery set is sealed

198 pages, manifest `receipts/discovery-set-seal-2026-08-18.json`,
sha256 `21ddea8e2ebf73ca7bbebe370028463521974ca368269d65ada3c9ead8bc230f`.

These pages may be cited as an effect *estimate*. They may not contribute a page
to the confirmatory endpoint, and no threshold may be re-tuned on them and then
reported as confirmed. The manifest hashes each prediction so that a later run
overlapping the seal is detectable rather than a matter of recollection.

## 2. The primary signal — one, chosen and fixed

**The combined gate: abstain if the two runs of the gated parser differ, or if
cross-parser critical-token agreement falls below the frozen floor.**

Chosen over the cheaper stability-only gate for three reasons that are not its
p-value:

- **Its mechanism passed validation.** The reference-based comparison underneath
  both halves detects sign changes at 1.00, date changes at 1.00 and number
  changes at 0.66, with a false-positive rate of 0.000 against the
  human-annotated ground truth. No output-only instrument came close.
- **The two halves are complementary, not redundant.** They overlap on 3 of the
  36 pages they flag between them (Jaccard 0.091); adding agreement to stability
  catches 2 severe errors stability alone misses.
- **It needs the smallest holdout.** Its abstained arm is 17% of the corpus
  rather than 9%, and power is governed by the smaller arm, so it reaches 80%
  power at 800 pages where stability alone needs 1,200 (section 5).

**The operating point, fixed now:**

- stability: byte-identical output across two runs of the same immutable
  assembly, `temperature: 0.0`;
- agreement floor: the critical-token agreement value that reproduces the
  stability gate's coverage on the discovery set — **0.04545**, on the
  `1 / (1 + mismatches)` scale, i.e. **abstain above 21 critical-token
  mismatches** against the second parser.

  That floor is loose in absolute terms because the two parsers disagree on
  critical tokens almost everywhere: median 5 mismatches per page, upper quartile
  14, maximum 170, and only 12 of 198 pages agree completely. The gate is
  therefore not "the parsers agree" but "the parsers disagree less than usual",
  and the manuscript must say so — calling it agreement would imply a precision
  the measurement does not have.

The agreement floor is the one tuned quantity in this protocol and it is
frozen at its discovery-set value. It is not re-derived on the holdout.

**Naming, which is normative.** These are *observable output signals*. Multi-run
disagreement is **execution instability**, or a **reproducibility signal** —
never "confidence". The frozen runtime emits no confidence, and calling an
observable proxy by that name would misdescribe the mechanism in both a
manuscript and a claim.

## 3. The primary endpoint — one, stated as a direction

> On an untouched holdout, the severe-error rate among pages the gate accepts is
> lower than among pages it abstains on.

Severe error is official text-block edit distance > 0.10, under evaluator
revision `193627ae9e97`, one config, one ground-truth file — the same definition
the discovery set used. Ground truth supplies the outcome only; the gate never
sees it.

**Test:** Fisher's exact, two-sided, α = 0.05, on the 2×2 of
accepted/abstained × severe/not. One test. No subgroup, no second threshold, no
alternative signal reported as if it were also primary.

**A known limitation of this definition, recorded before the test rather than
after it.** Section 8 shows that a share of "severe errors" at this threshold are
annotation-convention mismatches rather than transcription failures. The
definition is kept anyway, because it is the official metric and because changing
it after seeing which pages it mislabels is exactly the contamination this
protocol exists to prevent. The limitation belongs in the manuscript, not in a
revised threshold.

## 3a. The denominator, and why 51 pages leave it

51 of the 800 pages carry no official text-block edit distance, so the primary
endpoint is undefined on them and they are excluded. That is a bias threat
before it is an administrative detail: if pages left the denominator for a
reason connected to output quality — an empty prediction, a matcher timeout,
a transcription so poor nothing aligned — the exclusion would remove precisely
the likeliest severe errors and depress the measured rate invisibly, with
nothing in the test statistic to show for it.

Measured, not assumed (`receipts/scored-page-criterion-2026-08-18.json`): the
evaluator scores a page **if and only if its ground truth contains at least one
`text_block`, `title`, `reference` or `code_txt` region**. That rule reproduces
the evaluator's decision on 800 of 800 pages, with no exception in either
direction. The 51 excluded pages are table-only and figure-only pages.

The criterion reads no prediction. The exclusion is therefore fixed by the
annotation before the model runs and cannot correlate with the gate.

What this does not claim: that the excluded pages are safe. A table-only page can
be transcribed catastrophically. It claims only that the official *text* metric
does not measure them, and that their removal is not selective.

## 4. Secondary, reported but not decisive

Coverage · abstention rate · selective risk at the fixed operating point ·
the full risk-coverage curve and its AURC · absolute and relative risk reduction
with a bootstrap CI over pages (10,000 resamples, seed 20260818) · the
per-signal marginal gains from section 2.

These are descriptive. If the primary test does not reject, no secondary number
converts the result into a positive one.

## 5. Sample size

Simulated, not approximated: the abstained arm holds 17% of the corpus, so at
n=200 it carries about 33 pages and 6 errors — cell counts where a normal
approximation is not trustworthy. The simulation runs the same Fisher exact test
the protocol will run. 20,000 trials per point, seed 20260818, α = 0.05, target
power 0.80. Receipt: `receipts/holdout-power-v2-2026-08-18.json`.

| signal | effect assumed | accept err | abstain err | risk ratio | n for 80% power | power at n=198 |
|---|---|---|---|---|---|---|
| **stability + agreement** | observed | 0.036 | 0.182 | 5.0× | 300 | 0.761 |
| **stability + agreement** | halved | 0.036 | 0.109 | 3.0× | **800** | 0.355 |
| stability alone | observed | 0.044 | 0.222 | 5.0× | 300 | 0.647 |
| stability alone | halved | 0.044 | 0.133 | 3.0× | 1200 | 0.284 |
| evidence-validity (disqualified) | observed | 0.052 | 0.333 | 6.4× | 600 | 0.488 |
| evidence-validity (disqualified) | halved | 0.052 | 0.193 | 3.7× | 1600 | 0.216 |

**The holdout is 800 pages.**

The 300 in the first row is what would be right if the effect estimate were
unbiased, and it is not: the operating point was selected on the same 198 pages
that produced it. Halving the *difference* between the arms is a deliberate
winner's-curse discount, and a study sized on the undiscounted estimate is the
standard route to an underpowered result that fails to replicate a real effect.

Two consequences worth stating plainly:

- **The discovery set could not have confirmed this even if it had been
  untouched.** At n=198 the discounted power is 0.36. This is a second,
  independent reason the current result is an estimate rather than a finding,
  separate from the multiple-comparisons argument.
- **The cheaper gate needs the more expensive study.** Stability alone costs half
  as much per page to run but needs 1,200 holdout pages instead of 800. Whichever
  is cheaper overall depends on the price of scored corpus, not of GPU time.

## 6. What is forbidden after unsealing the holdout

- Re-tuning the agreement floor, or any other threshold.
- Swapping the primary signal for one that performed better on the holdout.
- Adding pages until the test rejects, or stopping early because it did.
- Reporting a secondary endpoint as the headline when the primary did not reject.
- Changing the severe-error definition, the evaluator revision, or the config —
  including in response to section 8.

  **This rule was subsequently broken, deliberately and on the record.**
  Amendment 02 replaced the evaluator revision after the result was known. The
  rule exists to stop the instrument being reshaped until the answer improves,
  and the honest question is whether that is what happened. Three things are
  offered so a reader can decide rather than take it on trust: the change has
  **no free parameter** to tune (it deletes a wall-clock branch rather than
  retuning one), it changed **0 gate decisions** and no metric, threshold or
  normalisation, and it moved the result **against** the hypothesis — p from
  0.0025 to 0.032, with the interval now crossing zero. Both readings are
  published. An instrument change that only ever ran in the favourable direction
  would deserve the suspicion this rule encodes; this one is recorded so the
  suspicion can be tested.
- Pooling holdout pages with the sealed discovery set for any reported number.

## 6a. The holdout, constructed and frozen

Built after this protocol was frozen and before any holdout page was scored.

**Eligibility.** The full OmniDocBench annotation is 1,651 pages and all 1,651
are staged locally. Under the broadest reading of "observed" every one of them is
burned, because a completed public campaign produced second-parser predictions
and per-page scores for the whole corpus. That reading is recorded and then
narrowed to something checkable: **a page is burned if the gated parser has ever
produced output for it**, since both halves of the gate are functions of that
output. 216 pages meet that test. 1,435 do not.

**Leakage control.** Selection is at document level: whole documents are taken,
so no two pages of the same newspaper land on opposite sides of the split.
Excluding documents that contributed a discovery page leaves 1,411 eligible
pages across 1,273 documents.

**The freeze.** Documents sorted by identity, shuffled with seed 20260818, taken
in order until 800 pages. Result: **800 pages across 710 documents**, receipt
`receipts/confirmatory-holdout-800-2026-08-18.json`, manifest sha256
`cbba1bd37790839adccd5221fbac5280b935b1203d31020c1ae491d4f7034573`.

**Leakage checks, all zero:** page identity overlap 0, document identity overlap
0, exact content duplicates 0, near duplicates 0.

The near-duplicate instrument was itself corrected during this step and the
correction matters. A 64-bit difference hash refused the freeze on 19 pairs;
diagnosis showed the hash, not the corpus — across 1,770 pairs of unrelated
discovery pages the minimum distance was 3 bits, and one holdout page "matched"
six mutually unrelated discovery pages at once. At 256 bits the minimum distance
over all 19,900 discovery pairs is 25 while a rescaled copy of a page hashes to
0, so the threshold was set at 20, between the two, and fixed before the freeze
was re-run. A heavy crop is **not** detectable at any threshold — a 2% crop lands
at 31 — and that case is covered by the document-level exclusion instead.

**Residual contamination, stated rather than argued away.** Eligible pages carry
second-parser scores from the completed public campaign. Those scores were never
inspected per page during A9, and neither gate signal can be computed from them
alone. The risk is not zero.

## 7. What executing this requires

800 pages not in the seal, scored under evaluator revision `193627ae9e97`, and
**three inference passes** — two of the gated parser and one of the second
parser. At the measured rates that is 19.4 GPU-seconds and $2.50 per 1,000 pages,
so roughly $2 of GPU for the whole holdout. Corpus acquisition and official
scoring, not GPU time, are the entire real cost.

## 7a. The execution record, including the failures

`receipts/holdout-execution-log-2026-08-18.json` is the census of every
controller attempt, generated from the run directories rather than written by
hand. It exists because "we ran the frozen 800 once" and "we ran it until we
liked the answer" are indistinguishable without it.

Nine attempts were made. Seven failed at assembly qualification with the same
`TimeoutError` against the sealed v4 qualifier's 420-second vLLM health
deadline; COMMUNITY host cold-start speed varies and run 1 cleared the same
deadline on the same GPU type, so the deadline is achievable and the qualifier
bytes — frozen contract — were not edited to make an attempt pass.

**Why re-attempting is not a second draw.** Every failure stopped before a page
was read. A failed attempt produced no prediction, so it cannot have influenced
a threshold, an operating point or a statistic. This is the operational-versus-
semantic failure separation the repository constitution requires: a Pod that
died is not a model that was wrong.

That argument is made falsifiable rather than asserted: the log **refuses** if
more than the two pre-registered attempts ever reached inference. Two samples of
a nondeterministic process with a choice made between them would not be a
pre-registered execution, and the instrument stops rather than reports it.

## 8. A limitation this protocol carries rather than fixes

Six of the twelve severe errors on the discovery set are invisible to both
halves of the gate. A census of those six (`receipts/missed-case-forensics-2026-08-18.json`)
found: no tables on any of them, prediction-to-truth length ratio 0.99, a mean of
2.8 critical-token mismatches against 33.3 for the errors the gate does catch, and
edit distances clustered at 0.114–0.139, just over the threshold.

Reading two of the six source images directly showed the mechanism. On the
fuzzy-scanned page the model transcribed logo text and read a two-column name
list column-by-column where the annotation reads it row-by-row; several of its
"errors" are corrections of ground-truth typos. On the handwritten note it
transcribed the running header and page number that the annotation marks as
`abandon`. Across all six, the model emitted **12 of 12** ground-truth regions
that the annotation excludes — headers, page numbers, figure captions, abandoned
regions — against 63% on the rest of the corpus.

The hypothesis this supports is that a meaningful share of severe errors at this
threshold are annotation-convention mismatches, not transcription failures — and
that no acceptance signal can catch them, because there is nothing wrong with the
output. It is a census of six pages and twelve regions. It is not a finding, it
does not change the endpoint, and it is recorded here so that it is on the record
before the holdout rather than available as an excuse afterwards.

## 9. Retraction record

| retracted | why | replaced by |
|---|---|---|
| `evidence_validity` as primary signal, p = 0.0014, zero marginal cost | `orphan_currency` matched the opening `$` of LaTeX math spans; the gate selected formula-dense pages | the combined stability + agreement gate |
| "the second parser is unnecessary" | confused a dominated *alternative* with a redundant *component*; agreement adds 2 severe-error catches over stability | complementarity measured at Jaccard 0.091 |
| "88 detected tables indicates a nesting bug" | the extraction unit is byte-identical to the evaluator's and there is no nesting in this corpus | model over-segmentation, recorded |
| "the 200 source images are not available locally" | they are, under `stage1-hard-200-v1/inputs/`, named by case id | direct visual inspection performed, section 8 |
| "a share of severe errors are annotation-convention mismatches" (section 8) | held on all 6 discovery residuals; on 42 holdout residuals the excluded-region emission rate is 0.72 against a corpus rate of 0.74 | **withdrawn as an explanation of the residuals**, `receipts/holdout-forensics-2026-08-18.json` |
| the structural-validity gate as a weakly positive zero-cost signal | absolute risk reduction **−0.53pp** on 749 holdout pages; the pages it flags are cleaner than the ones it accepts | reported as a measured negative result; must not be shipped |
| "the evaluator's nondeterminism is independent of the gate and only attenuates the association" | measured, not assumed: the scoring fallback fired on 12.87% of abstained against 3.70% of accepted pages, Fisher exact p = 0.00050 | **retracted**; the instrument was corrected and the frozen evidence re-measured — amendment 02 |

## 10. Status

`EXECUTED`. The frozen 800-page holdout was run and scored, and the single
pre-registered test was performed once.

**First reading, frozen evaluator.** 648 accepted at 6.48% against 15.84% among
101 abstained, Fisher exact two-sided p = 0.0025.
Receipt: `receipts/confirmatory-result-2026-08-18.json` (kept; its hash is pinned
below and it has not been rewritten).

**The instrument was then found defective and the evidence re-measured** —
amendment 02, `A9_PROTOCOL_AMENDMENT_02_2026-08-18.md`. The evaluator selected
its matching algorithm by wall-clock timeout, and that fallback was measured to
be *dependent* on the gate (12.87% of abstained pages against 3.70% of accepted,
Fisher p = 0.00050), which makes it a confounder of the primary endpoint rather
than benign noise.

**Result under the corrected deterministic evaluator, which is the result that
stands: the null is rejected.** On the same 749 scored pages, with the same
648/101 partition — **0 gate decisions changed** — the gate accepts 648 at a
**5.86%** severe-error rate against **11.88%** among the 101 abstained (Fisher
exact, two-sided, **p = 0.032**, α = 0.05), in the direction observed on the
discovery set. Rate difference 6.02pp, bootstrap 95% CI **−0.21 to 12.79pp**.
Receipt: `receipts/confirmatory-result-deterministic-2026-08-18.json`.

**The magnitude claim does not survive, and is withdrawn.** The pre-registered
decision rule is the Fisher test and it rejects; the interval on the rate
difference includes zero. A9 claims the association and not its size.

Nothing in the protocol's operating point, endpoint, holdout or test was changed
at any point. The one post-unsealing change is the scoring instrument, recorded
as amendment 02 with both readings kept side by side in
`receipts/evaluator-correction-comparison-2026-08-18.json`.

### What this does and does not license

The correct description of the primary A9 result is no longer "promising, not
confirmed". It is **confirmed on one pre-registered test, scoped to this model
pair, this corpus and this operating point** — and that scope is part of the
statement, not a caveat appended to it.

Still *not* licensed by this result:

- **Any public claim.** Whether evidence supports a claim, and whether one is
  made, is the founder's decision. `PATENT_FILING = NOT FILED`,
  `PAPER_SUBMISSION = NOT SUBMITTED`.
- **Generalisation to another model pair or corpus.** One model, one second
  parser, one benchmark.
- **Any calibration claim.** No threshold here is calibrated;
  `CalibrationTable.calibrated` remains `False`.
- **The secondary results.** Tiers, complementarity and the residual census
  carry no p-values, were not pre-registered as endpoints, and are descriptive.
  They did not and could not have rescued a failed primary.
- **Any statement of effect size.** 6.02pp is a point estimate whose interval
  contains zero. "The gate roughly halves the severe-error rate" is not
  supported by this study.

### Result artifact hashes

Recorded so that a silent overwrite is detectable. This is not hypothetical:
earlier in this work two duplicate background jobs raced on the power-calculation
receipt and the second quietly replaced the first with third-decimal-different
Monte-Carlo values. Nothing failed, and the document and the receipt simply
stopped agreeing.

| artifact | sha256 |
|---|---|
| `confirmatory-result-2026-08-18.json` | `aca7a20f0c99d29c056e67df03bfce48ce9860ecff90811c0d728d3d5dbbf7e0` |
| `r4-confirmatory-2026-08-18.json` | `0fb53e5039e0e7dd16aca7302414546e2e37d14627e71f43de9328627c7dfc7b` |
| `holdout-forensics-2026-08-18.json` | `177e63bc70be7c7fde72e7b5bd3d598e5b590a5e84a6d655f45786761975f9d6` |
| `holdout-execution-log-2026-08-18.json` | `9bdd7193c37207349892509288b868536e843a2628aff56960c1b913a35111fa` |
| `scored-page-criterion-2026-08-18.json` | `86f3c3a24b1408b47985bfeed6a1df2dd9a42a59d67da09ef47b9b7eb001dd3a` |
| `confirmatory-holdout-800-2026-08-18.json` | `9e71f34114026797c308797530ef660f27b34ab6dee1638bb0e4c98ccfc02c01` |
| `discovery-set-seal-2026-08-18.json` | `460d1a272ee5061cc573cc3c95034f1db070ce6114974f4586427cc2d94da737` |
| `metric-reproducibility-2026-08-18.json` | `d5d1a73872c6b03878f0a7c50747d9fa3044da498a8d62e527759c3ae68b968f` |


The corrected instrument's receipts, pinned on the same terms. The rows above are **not** recomputed: those files were never rewritten, and their original hashes are what demonstrates it.

| artifact | sha256 |
|---|---|
| `confirmatory-result-deterministic-2026-08-18.json` | `ccb6965459bc0347cb133c18f292614d4e8010f8642a270e84c5b361e204a4f9` |
| `evaluator-correction-comparison-2026-08-18.json` | `c8b7c97d5443058f92c77f3f2c7beb5c0fea33dc96f1dca797b20bdf369a9be2` |
| `evaluator-determinism-2026-08-18.json` | `aefcaed291051ead28b439936dfd4da4e1c0319d27d93667a272051f65e129be` |
| `evaluator-version-deterministic-v1.json` | `265482c0d041d487269af1e27cb732bf48dbaf18f10c0fcfade3222a0e2a7df9` |
| `fallback-independence-2026-08-18.json` | `d63e377a2ed1d124dc740bea86cbcc49d0aabed4f6289672ce192a68737bff57` |
| `correction-locality-2026-08-18.json` | `40bf93fae2afe3ead4bf224c9e6c1786bedea76215ea165ecdb21ad215288b6f` |
| `r4-confirmatory-deterministic-2026-08-18.json` | `6e33b69eae53f063a1a93c30943b0af472a75b339e353f999e3d7da3a7b9ca5f` |
| `holdout-forensics-deterministic-2026-08-18.json` | `6f5c70dd1afbdab1213d202f1d2382165c479f5a73abcb628103e94b9c5b08b8` |
| `metric-reproducibility-deterministic-2026-08-18.json` | `c816e73ee1a3529b11128a1c92f0b620d52544427b1322b1bdec9e04c8bb4325` |
### One post-hoc change, disclosed

`r4_marginal_analysis.py` read the second parser's prediction unconditionally
and raised `FileNotFoundError` on the holdout, where 15 pages have none. It was
repaired **after** the primary test had already run and written its receipt, and
the repair aligns it with amendment 01 — a missing second-parser prediction
scores zero agreement and therefore abstains, exactly as the confirmatory test
already did. The primary test's code and result are untouched by this; the
change affects only the descriptive cost analysis. It is recorded here because a
repair made after unsealing is exactly the kind of thing that must be disclosed
rather than absorbed, even when it is mechanical.
