# A9 / R4 — limitations and threats to validity

Written to be usable as a manuscript section and as the honest answer to a
reviewer. Every entry names what could be wrong, what was done about it, and
what remains unfixed. Entries that were found by measurement rather than
anticipated are marked, because those are the ones that say something about how
much else might still be hiding.

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

---

## 1. Construct validity — is the outcome measuring what we mean by "error"?

**The severe-error label is partly an annotation-convention label.** *(found by
measurement)* A census of the six discovery-set severe errors that no gate
caught found that all six transcribe ground-truth-excluded regions — running
headers, page numbers, figure captions, logo text — at 12 of 12 against 63% for
the rest of the corpus, and that on one fuzzy scan several of the model's
"errors" correct ground-truth typos. Their prediction-to-truth length ratio is
0.99 and their edit distances cluster at 0.114–0.139, immediately above the
threshold.

What was done: nothing, deliberately. The definition is the official metric and
was frozen before the holdout; changing it after seeing which pages it mislabels
is the contamination the protocol exists to prevent. The limitation is carried,
not fixed, and the holdout re-checks the pattern as a secondary analysis.

**Ink is not text.** The scan-image verifier reads marks, so a photograph, a
logo and a dark scan margin all count as content. Measured: figure-bearing pages
sit at 0.264 ink-per-character against 0.198 without. This is one reason that
instrument failed, and it is reported rather than corrected.

## 2. Internal validity — could the effect be an artefact?

**Two instruments were confounded, and one of them nearly became the headline.**
*(found by measurement)* `evidence_validity` reached p = 0.0014 on the discovery
set and was named the confirmatory primary signal. Its `orphan_currency` rule was
matching the opening `$` of LaTeX math spans, which this corpus uses to typeset
prices, so the gate was selecting formula-dense pages. Corrected: p = 0.0442,
zero detection on nine injected semantic corruptions, and a false-positive rate
of 8.5% on human-annotated ground truth against a 3.0% firing rate on model
output — it fires more often on known-correct text than on the text under test.
Retracted and replaced.

The general lesson is in the mitigation: **every instrument now carries a
negative control.** The defect was invisible to sensitivity testing and appeared
immediately when the instrument was pointed at documents known to be correct.

**The structural signal is confounded with table count.** It flags 2 of 198
pages, and those pages average 14.7 tables against 0.22 elsewhere. Page-level
scoring uses defect *presence* so a table-heavy page contributes once, but the
residual confound is large enough that the signal is reported and not used as a
gate.

**The near-duplicate instrument was itself wrong at first.** *(found by
measurement)* A 64-bit difference hash refused the holdout freeze on 19 pairs;
across 1,770 pairs of unrelated discovery pages its minimum distance was 3 bits.
Replaced with a 256-bit hash whose measured minimum over 19,900 unrelated pairs
is 25, threshold set at 20, fixed before re-running.

**The denominator loses 51 of 800 pages, and that had to be checked rather than
noted.** *(found by measurement)* Those pages carry no official text-block edit
distance, so the primary endpoint is undefined on them. The danger is not the
count but the mechanism: an exclusion correlated with output quality — an empty
prediction, a matcher timeout, a transcription so poor that nothing aligned —
would strip out precisely the likeliest severe errors and depress the measured
rate with nothing in the test statistic to show for it.

Measured: the evaluator scores a page if and only if its *ground truth* contains
at least one `text_block`, `title`, `reference` or `code_txt` region, and that
rule reproduces its decision on 800 of 800 pages with no exception in either
direction. The rule reads no prediction, so the exclusion is fixed by the
annotation before the model runs and cannot interact with the gate. The excluded
pages are table-only and figure-only pages.

The residual limitation, stated rather than closed: this says the official *text*
metric does not measure those 51 pages. It does not say they are safe. A
table-only page can be transcribed catastrophically, and this design would not
see it.

Worth recording that the first rule proposed here was wrong. Using the
evaluator's own 16-category group of matched text elements — the obvious
candidate — misclassified 48 pages that carry only captions, footnotes or page
numbers. The correct set was found by testing candidates against the evaluator's
real output, not by reading its source.

**The outcome label is not perfectly reproducible, and the cause is our own
harness.** *(found by measurement, after the primary test)* Scoring both gated
runs revealed that **15 byte-identical pages received different scores across two
evaluation runs, and 5 of them flipped the severe label**. A byte-identical
prediction should not be able to change score.

The cause is not the upstream evaluator's matching. It is the stall-recovery
wrapper this repository puts around it: `quick_match` is abandoned after a
wall-clock timeout and a chunked Hungarian fallback with an order penalty runs
instead. Which pages exceed that timeout depends on machine load — 34 pages fell
back in one run and 28 in the other, with 12 falling back in exactly one — so
identical bytes can be scored by two different algorithms. 11 of the 15 moved
pages hit a fallback in at least one run.

**The first reading of this was wrong, and is retracted.** It said: the gate
never reads the evaluator, so the noise is independent of the accepted/abstained
split; independent misclassification of a binary outcome attenuates a measured
association toward the null rather than manufacturing one; therefore p = 0.0025
is conservative.

The premise does not follow. The gate not *reading* the evaluator makes the noise
independent of the evaluator's **output**, not of its **failure mode**. Both the
gate decision and the matcher's running time are functions of the same page, and
a page with many elements in disordered reading order is plausibly both slow to
match and likely to be abstained on.

Tested rather than argued (`receipts/fallback-independence-2026-08-18.json`): the
fallback fired on **12.87% of abstained pages against 3.70% of accepted pages,
Fisher exact two-sided p = 0.00050**, and it is also strongly associated with the
outcome itself. A measurement error correlated with both the exposure and the
outcome is a confounder, and the attenuation argument gives no protection at all.
This is a defect in the primary endpoint's measurement layer, not a limitation of
it.

**What it did to the result, measured rather than bounded.** The correction
removed 8 severe labels — every one of them in the direction severe → not
severe, because the approximation could only ever manufacture a dirty page, not
a clean one. Four fell in each arm, but the abstained arm is 101 pages against
648, so the same four corrections cost it 3.96pp against 0.62pp. **35.7% of the
originally measured effect was an artefact of the instrument**, and it pointed
the way that flattered the hypothesis: p moved from 0.0025 to 0.032 and the
95% interval on the rate difference now includes zero.

Under the corrected instrument this noise is gone rather than bounded, and that
is measured rather than argued. Re-scoring both frozen runs deterministically and
repeating the byte-identical-page check that found the defect: on 717
byte-identical pages **0 scores move and 0 severe labels flip**, against 15 and 5
before. The 6 remaining score movements are all on pages whose predictions
genuinely differ between the two runs, which is the behaviour a scorer should
have. Receipt: `receipts/metric-reproducibility-deterministic-2026-08-18.json`.

**Repaired and re-measured.** The original instinct — that changing the
apparatus after the confirmatory run is a post-hoc adjustment — is right about
changes that move an *operating point*, and wrong here. Nothing about the
experiment moved: the model outputs, the gate, the severe-error definition, the
holdout membership, the test and α are untouched. Only the device that turns a
prediction into a score was repaired, and the same frozen evidence was measured
again with it. The repair removes the wall-clock decision entirely rather than
retuning it, so it has no free parameter that could be adjusted toward a
preferred answer, and both readings stay on the record.

The full account is `EVALUATOR_CORRECTION_2026-08-18.md`; the corrected
instrument is `omnidocbench-deterministic-v1`.

## 3. External validity — does it generalise?

**One model, one second parser, one corpus.** The gated parser is OvisOCR2 at a
single pinned assembly; the second parser is one frozen MinerU 3.4.4 campaign.
Nothing here says the effect holds for another model pair, and the agreement
floor of 21 critical-token mismatches is a property of *this* pair's disagreement
distribution (median 5, upper quartile 14, maximum 170) rather than a general
constant.

**The discovery corpus is a hard subset.** 200 pages selected for visual
complexity. The holdout is drawn from the remainder of the same benchmark and is
therefore easier on average, which is a difference in the conservative
direction for the base rate but not necessarily for the effect.

**Never comparable to a leaderboard row.** These are subsets; leaderboards are
whole corpora. Quoted, never reproduced, never placed beside these numbers.

## 4. Statistical conclusion validity

**The discovery result cannot be significant, twice over.** Roughly 120 post-hoc
comparisons put the Bonferroni threshold near p ≈ 0.0004, which nothing on the
discovery set survives; and independently, the power calculation shows that at
n = 198 the discounted power is 0.36, so the discovery set could not have
confirmed the effect even if it had been untouched.

**Twelve severe errors is a small number, and six is smaller.** Every
per-signal marginal gain on the discovery set is a count out of twelve. They are
reported as counts, not as rates with implied precision.

**The holdout is sized on a halved effect.** The observed contrast would have
justified 300 pages; halving the arm difference as a winner's-curse discount
gives 800, which is what was frozen. If the true effect is smaller than half the
observed one, the study is underpowered and a null result is ambiguous — that
ambiguity is a property of the design and was stated before the result.

**The discount was the right call, and it was not conservative enough.**
*(resolved by measurement, then revised by the instrument correction)* The
holdout rejects at p = 0.032, but the effect is **smaller than half** the
discovery contrast: discovery measured 3.9% accepted against 25.0% abstained,
the holdout 5.86% against 11.88%. The design halved the arm difference; the
realised difference is closer to a third of it, which is why the 95% interval on
the rate difference includes zero at 800 pages.

Had the study been sized on the undiscounted effect at 300 pages it would have
been badly underpowered. Had it been sized on what actually turned up, 800 pages
would not have been enough either. The winner's-curse discount was load-bearing
and still insufficient — one instance, not a general result, but a concrete
argument for discounting a selected operating point harder than one thinks
necessary.

**Reading the shrinkage correctly.** The accepted-set rate *rose* between the
two sets (3.9% → 5.9%) and the abstained-set rate *fell* (25.0% → 11.9%). Both
move toward the base rate, which is what regression from a selected operating
point looks like. The holdout's own base rate is also higher (6.68% vs 6.1%),
so part of the accepted-rate rise is corpus difficulty rather than shrinkage.
The two cannot be separated with one holdout, and no attempt is made to.

**One test was run, and the secondary analyses are not tests.** The primary
executed once, before any secondary analysis touched the holdout outcomes, and
the run order is enforced by the driver script rather than by intention. The
tier comparisons, the complementarity numbers and the residual census carry no
p-values and are not corrected for multiplicity, because they are descriptive.
Nothing among them converts the primary result or would have rescued it had it
failed.

**A dominated configuration turned actively harmful, which is worth stating as a
statistical caution rather than only as a finding.** The structural gate scored a
weak positive on 198 discovery pages and a **negative** 0.64pp risk reduction on
749 holdout pages. It was never a candidate primary signal, but it was in the
cost table with a positive number beside it. A weak positive on a small
exploratory set is not evidence of a small real effect; it is compatible with no
effect and with an effect of the opposite sign.

## 5. Contamination and leakage

**The holdout's second-parser predictions predate this experiment.** Under the
broadest definition of "observed" every page in the benchmark is burned, because
a completed public campaign scored all 1,651 with the second parser. The
narrower, checkable definition used is "the gated parser has produced output for
this page", which excludes 216. The residual risk is that those campaign scores
influenced A9 design in some way not traceable in the receipts. It is not zero,
and it is recorded in the audit rather than argued away.

**Leakage controls that are in place:** document-level split (no document
straddles the boundary), page identity, exact content hash, and 256-bit
perceptual near-duplicate. **A control that is not in place:** heavy cropping is
undetectable by the perceptual hash at any threshold — a 2% crop already exceeds
the unrelated-pair minimum — and is covered only indirectly, by excluding whole
documents.

## 6. Operational validity

**Cost figures are raw GPU cost at the rate a specific run was billed.** The two
parsers ran on different clouds at different hourly rates ($0.34 COMMUNITY and
$0.74), so GPU-seconds is the comparable quantity and dollars are reported with
each rate named. These are not retail prices and must never sit beside one.

**The COMMUNITY-cloud caveat carries.** The holdout runs on COMMUNITY capacity
because SECURE had no CUDA ≥ 12.9 stock, so its output is not SECURE-cloud
evidence and must not be labelled as such.

## 6a. Execution integrity

**The holdout took nine controller attempts, and reporting only the successful
one would have been misleading.** Seven failed at runtime assembly qualification
against a frozen health-check deadline, on community-cloud hosts with variable
cold-start time; the successful runs cleared the same deadline on the same GPU
type, so the deadline was achievable and no frozen component was edited to make
an attempt pass.

The argument that this does not contaminate the result is that every failure
stopped before a page was read, so no failed attempt produced a prediction and
none could influence a threshold, an operating point or a statistic. That is the
operational-versus-semantic failure distinction the system is built around, and
it is the right argument — but it is an argument, and arguments about one's own
experiment are worth little unless something can falsify them.

What makes it checkable: the execution log is generated from the controller's
own run directories rather than written afterwards, and it **refuses** if more
than the pre-registered number of attempts ever reached inference. Two samples
of a nondeterministic process with a choice made between them is the failure
mode that matters, and the instrument stops rather than reports it.

The residual risk that remains: an attempt that reached inference and was
deleted from disk before the log ran would be invisible to it. The log audits
what the controller wrote; it cannot audit what was removed.

## 7. What no amount of additional spend fixes

On the discovery set, every gate leaves half the severe errors in the accepted
set. The three-signal combination catches 8 of 12; stability and agreement
together catch 6. The remainder look, to every signal available, exactly like
correct output.

**The holdout makes this worse, and removes one of the consolations.** On 749
pages, 36 of 50 severe errors are invisible to every signal — 72%, against the
discovery set's half — and the two-signal gate leaves 39. The most expensive
configuration spends 2.6x the GPU of a single run and still accepts the large
majority of severe errors.

The consolation that was removed: §1 recorded a census suggesting part of the
residual might be annotation-convention mismatch rather than error, on the
strength of all six discovery residuals transcribing ground-truth-excluded
regions. On 38 holdout residuals the excluded-region emission rate is 0.70
against a corpus rate of 0.74 — indistinguishable. **That explanation does not
survive the larger sample and is withdrawn.** What does survive is less
comforting: the residuals have a prediction-to-truth length ratio near one and
lose few critical tokens, meaning they look like correct transcriptions of the
right length with the right numbers, and are wrong anyway.

The ceiling is a property of the signals, not of the budget, and it is now
measured on a sample large enough that it is unlikely to be a small-sample
artefact.
