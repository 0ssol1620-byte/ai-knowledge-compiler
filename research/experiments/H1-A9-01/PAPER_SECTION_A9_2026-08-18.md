# Selective acceptance for document parsing — manuscript section (draft)

Draft of the experiment and results section for the *Beyond the Parser*
follow-on. Written to be lifted into the manuscript, so it is in manuscript
voice and carries its own limitations rather than deferring them.

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`. Nothing here is
authorized for publication, and what a public claim says is not a decision made
in this document.

**Status:** Methods and results complete.

---

## 1. Motivation

A document parser that is wrong on 6% of pages and silent about which 6% is not
usable as a source of trusted context: every downstream consumer must treat all
of its output as suspect. A parser that is wrong on 6% and can *say* which pages
it is unsure of is a different tool, because the uncertain pages can be escalated
to a more expensive path and the rest can be trusted.

This is selective prediction applied to document parsing. The question is not
whether a parser can be made more accurate, but whether a per-page **acceptance
gate** can separate the pages it gets right from the pages it gets wrong, using
only signals available without ground truth — and at what cost.

## 2. Signals

Two signals are evaluated, both computed from parser output alone, and both
deliberately of a kind that a deployed system can compute at inference time.

**Execution stability.** The same immutable model assembly is run twice over the
same page at temperature 0, and the two outputs are compared byte for byte. Any
difference abstains. Nominally deterministic decoding is not bit-reproducible in
practice — batching, kernel selection and reduction order vary — and the
hypothesis is that the pages where that nondeterminism becomes visible are pages
where the model's distribution is flat, which is to say pages it is unsure of.

**Cross-parser critical-token agreement.** An independent parser of a different
family transcribes the same page, and the two transcriptions are compared on
*critical tokens* — numbers, dates, currency amounts, units, identifiers —
rather than on text similarity. Text similarity is dominated by layout and
reading-order convention, which are exactly the differences between parsers that
do not matter. A page abstains when critical-token mismatches exceed a fixed
floor.

The two are expected to be complementary rather than redundant: stability is
blind to an error the model makes confidently and repeatably, and agreement is
blind to an error both parsers make.

A third family of signals — output-only internal consistency, structural
validity of emitted tables, and OCR-independent ink coverage against the source
image — was implemented and is reported in §7 as negative results.

## 3. Corpus and split

Pages are drawn from OmniDocBench. A 200-page discovery set, selected for visual
complexity, was used for all exploratory work: signal design, threshold search,
instrument development and failure analysis. It was then **sealed by content
hash**; anything downstream that touches a page in it is contaminated by
construction and the seal makes that checkable.

An 800-page confirmatory holdout was drawn from the remainder. It was
constructed under four leakage controls that **refuse rather than report**:
page identity, exact content hash, 256-bit perceptual near-duplicate distance,
and a document-level split so that no source document contributes pages to both
sets. Document-level splitting was preferred to page-level random splitting
because pages of one document share layout, typography and scan conditions, and
a page-level split leaks all three.

One leakage control is knowingly incomplete and is reported as such: a heavily
cropped derivative is undetectable by perceptual hashing at any threshold — a 2%
crop already exceeds the measured unrelated-pair minimum — and is covered only
indirectly by excluding whole documents.

## 4. Outcome

Severe error is **official text-block edit distance > 0.10** under a single
frozen evaluator revision, one configuration, one ground-truth file. Ground
truth supplies the outcome only. The gate never reads it, and correctness is
computed by a separately frozen component, so the acceptance decision cannot be
circular with the correctness label.

**51 of the 800 pages carry no official text score and are excluded.** This is a
bias threat rather than an administrative detail: if pages left the denominator
for a reason connected to output quality, the exclusion would remove precisely
the likeliest severe errors. The exclusion rule was therefore derived and
checked rather than assumed — the evaluator scores a page if and only if its
*ground truth* contains at least one body-text region, a rule that reproduces
the evaluator's decision on 800 of 800 pages with no exception in either
direction. The rule reads no prediction, so the exclusion is fixed by the
annotation before the model runs. The excluded pages are table-only and
figure-only pages, and the claim is not that they are safe — a table-only page
can be transcribed catastrophically — only that the official *text* metric does
not measure them and their removal is not selective.

## 5. Preregistration

The operating point, the endpoint, the test and the sample size were fixed in a
written protocol before the holdout was constructed, and the protocol's hash is
recorded. Specifically fixed in advance: the gate (abstain if the two runs
differ, or if critical-token mismatches exceed the floor, or if the second
parser has no prediction for the page — a missing signal abstains, never
accepts), the severe-error definition, and a **single** two-sided Fisher exact
test at α = 0.05 on accepted-versus-abstained. One test. No subgroup analysis
promoted to primary, no second threshold, no alternative signal reported as
though it were also primary.

The sample size was computed on a **halved** effect. The contrast observed on
the discovery set would have justified 300 pages; halving the arm difference as
a winner's-curse discount gives 800. The consequence is stated before the
result: if the true effect is smaller than half the observed one, the study is
underpowered and a null is ambiguous.

## 6. Instrument validation

Every instrument in this work is validated before any number derived from it is
believed, in both directions:

- **Sensitivity** against nine injected *semantic* corruptions — number change,
  sign change, date change, unit change, entity/token loss, row swap, column
  swap, cell omission, duplicated cell. Syntactic corruption is not used,
  because detecting a broken tag says nothing about detecting a changed digit.
- **False-positive rate** against human-annotated ground-truth text as a
  negative control. Any flag raised on ground truth is by construction a false
  positive.

This is not methodological decoration. The negative control is what exposed the
single largest error in this work, described in §7, and the defect was invisible
to sensitivity testing alone.

Instrument measurement units are additionally checked for identity with the
official evaluator's, by executing the evaluator's own extraction function and
diffing it against the instrument's, rather than by reading its source and
reimplementing it. An earlier instrument counted 88 tables where the evaluator
counted 60; the divergence was model over-segmentation surfacing through a
measurement unit that had never been checked against the reference.

## 7. Negative and retracted results

Reported because a failed hypothesis is evidence, and because the corrections
are more informative than the successes.

**An internal-consistency signal was retracted after being named primary.** It
reached p = 0.0014 on the discovery set. Its orphaned-currency rule was matching
the opening `$` of LaTeX math spans, which this corpus uses to typeset prices,
so the gate was silently selecting formula-dense pages. Corrected, it detects
none of the nine semantic corruptions and has an 8.5% false-positive rate on
ground truth against a 3.0% firing rate on the text under test — it fires more
often on known-correct text than on model output. Retracted and replaced.

**Structural validity of emitted tables is not supported on this corpus.** It
flags 2 of 198 pages, and those pages average 14.7 tables against 0.22
elsewhere; the signal is confounded with table count and is reported, not used.

**Ink coverage against the source image is not supported.** The highest
ink-per-character decile contains no severe errors at all (p = 0.62). Ink is not
text: a photograph, a logo and a dark scan margin all read as marks, and
figure-bearing pages measure 0.264 ink-per-character against 0.198 without.

**A near-duplicate instrument was itself defective.** A 64-bit difference hash
refused the holdout freeze on 19 pairs; across 1,770 unrelated discovery pairs
its minimum distance was 3 bits, so it could not distinguish dense scanned text
at all. Replaced with a 256-bit hash whose measured unrelated-pair minimum over
19,900 pairs is 25, with the threshold set at 20 and fixed before re-running.

## 8. Execution record

The confirmatory holdout required nine controller attempts. Seven failed at
runtime assembly qualification against a frozen health-check deadline, on
community-cloud hosts whose cold-start time varies; the successful runs cleared
the same deadline on the same GPU type, so the deadline was achievable and no
frozen component was modified to make an attempt pass.

Every failure stopped before a page was read and therefore produced no
prediction, so no failed attempt can have influenced a threshold, an operating
point or a statistic. Reporting this is not incidental: "we ran the holdout
once" and "we ran it until we liked the answer" are indistinguishable without
the execution record, and the record is generated from the controller's own run
directories rather than written by hand. The instrument that produces it refuses
if more than the pre-registered number of attempts ever reached inference.

## 9. Results

### 9.1 The confirmatory test

All figures in this section come from the **deterministic evaluator**
(`omnidocbench-deterministic-v1`). The originally reported figures came from an
instrument that selected its matching algorithm by wall-clock timeout; §9.5 and
§9.6 give the defect, the repair and both readings side by side. The frozen model
outputs, the gate, the operating point and the holdout are identical in both.

The gated parser was run twice over the frozen 800 pages, and 749 carry an
official text score. The baseline severe-error rate is **6.68%** (50 of 749).

At the pre-registered operating point the gate accepts 648 pages and abstains on
101. The severe-error rate is **5.86% among accepted pages and 11.88% among
abstained pages** (Fisher exact, two-sided, **p = 0.032**), rejecting the null
at α = 0.05 in the direction observed on the discovery set.

| quantity | value | 95% interval |
|---|---|---|
| accepted severe-error rate | 5.86% (38/648) | 4.30–7.95% (Wilson) |
| abstained severe-error rate | 11.88% (12/101) | 6.93–19.63% (Wilson) |
| rate difference | 6.02pp | **−0.21 to 12.79pp** (bootstrap, 10,000) |
| risk ratio, abstained/accepted | 2.03 | — |
| absolute risk reduction vs baseline | 0.81pp | — |
| relative risk reduction | 12.2% | — |
| coverage | 86.5% | — |
| severe errors avoided per 1,000 pages | 8.1 | — |
| GPU cost | $2.50/1,000 pages | — |
| cost per severe error avoided | $0.308 | — |

**The decision rule and the interval disagree, and both are reported.** The
pre-registered primary endpoint is the Fisher exact test, which rejects. The
bootstrap interval on the risk difference is a different and more conservative
procedure over a 101-page arm, and it includes zero. We therefore claim the
*association* and not its *magnitude*: this study establishes that abstained
pages carry a higher severe-error rate, and does not establish how much higher.

The effect is **smaller than on the discovery set**, which is what a
selected-operating-point result should do when it is honest. Discovery measured
3.9% accepted against 25.0% abstained; the holdout measures 5.9% against 11.9%.
The direction and the significance replicate and the magnitude shrinks by
substantially more than half — more, in fact, than the sample size was budgeted
for, which is why the interval no longer clears zero. Reporting the discovery
contrast as the expected effect would have overstated it roughly threefold.

15 of the abstentions are pages with no second-parser prediction, abstained
under the fail-closed rule rather than on a measured disagreement.

### 9.2 The two signals are complementary, and the holdout says so more strongly

Of the 50 severe errors, stability catches 5 and cross-parser agreement catches
6. Their marginal gains over each other are **+6 and +5 respectively** — that is,
each signal's entire yield is additional to the other's. Of the **11** severe
errors the two catch between them — 50 total minus the 39 both miss — **all 11
are caught by exactly one**, so on corrected labels the intersection is empty.
The Jaccard overlap of the sets of pages they *flag* is **0.067**, lower than
the 0.091 measured on the discovery set: the two signals rarely fire on the same
page at all.

This is the result the cost analysis depends on. If agreement re-detected what
stability detects, running both would be paying twice for one signal; it does
not, so the two-signal configuration buys genuinely additional error reduction.

### 9.3 Cost-quality tiers

| tier | GPU s/page | coverage | severe rate | RRR | $/1,000 | $/error avoided |
|---|---|---|---|---|---|---|
| single run | 10.17 | 1.000 | 6.68% | — | $0.96 | — |
| stability gate | 20.34 | 0.957 | 6.28% | 6.0% | $1.92 | $0.103 |
| stability + agreement | 26.34 | 0.920 | 5.66% | 15.2% | $3.15 | $0.202 |

Each step buys non-overlapping error reduction at a monotonically rising price
per error removed, which is the shape a cost-quality frontier should have. The
stability gate alone is the cheapest error removal available here at $0.103 per
severe error avoided; adding the second parser costs roughly twice that per
additional error, which is what an independent signal costs.

Two changes from the pre-correction reading are worth naming, because they run
in opposite directions. The stability gate on its own is **no longer significant**
(Fisher p = 0.055 against 0.002); it survives here as the cheapest tier, not as an
established effect. And the coverage-matched agreement-only gate, which was
*dominated* under the defective instrument, is no longer dominated — it now buys
1.4 additional avoided errors per 1,000 pages at $0.195 each.

The structural-validity gate remains dominated and remains **negative**: a risk
reduction of −0.53pp — the pages it flags are cleaner than the pages it accepts —
having been merely weak and confounded on the discovery set.

### 9.4 The ceiling

**36 of the 50 severe errors are invisible to every signal measured**, and 39
survive the two-signal gate. The discovery set put that fraction near one half;
the larger sample puts it at 72%. Spending does not move it: the most expensive
configuration uses 2.6x the GPU of a single run and still accepts the large
majority of severe errors.

A secondary, exploratory census of the residuals re-checked four hypotheses
formed on the discovery set. Two reproduced: the pages that defeat every signal
have a prediction-to-truth length ratio near one (0.87 against 5.18 for caught
pages) and lose far fewer critical tokens (6.2 mismatches against 297.9). Both
say the same thing — these outputs *look* like correct transcriptions of about
the right length containing about the right numbers, and no ground-truth-free
signal here separates them.

Two hypotheses did **not** reproduce: missed cases do not carry fewer tables, and
they do not transcribe ground-truth-excluded regions at an elevated rate (0.70
against a corpus rate of 0.74). Both were formed on six cases and did not survive
thirty-eight. They are reported because they were stated in advance of this check,
and because a hypothesis that dies on a larger sample is the ordinary outcome of
generating hypotheses from small residual sets. No p-value is attached to any of
this; it was not pre-registered as an endpoint.

### 9.5 The scoring harness was not deterministic, and we found out afterwards

Both gated runs were scored, which allowed a check that had not been planned:
the same page, transcribed identically by two runs, should receive the same
score. On 717 byte-identical pages, **15 did not, and 5 of those flipped the
severe label**.

The cause is a stall-recovery wrapper around the official matcher rather than
the matcher itself. A wall-clock timeout abandons the primary matching and
substitutes a chunked approximation; which pages exceed the timeout depends on
machine load, and the two runs fell back on 34 and 28 pages respectively with 12
asymmetric. 11 of the 15 moved pages hit a fallback in at least one run.

The aggregate is far more robust than the per-page labels: mean edit distance
0.02853 against 0.02807, and **58 severe pages in both runs** — the same total,
differently distributed.

An earlier draft of this section argued that the noise was harmless: the gate
never reads the evaluator, so the misclassification is independent of the
accepted/abstained split, and independent outcome misclassification attenuates an
association toward the null. **That argument is withdrawn.** Independence from
the evaluator's *output* does not imply independence from its *failure mode*, and
both the gate decision and the matcher's running time are functions of the same
page.

Measured directly, the fallback is not independent of the gate: it fired on
**12.87% of abstained pages against 3.70% of accepted pages, Fisher exact
two-sided p = 0.00050**, and it is also strongly associated with the outcome.
Measurement error correlated with both the exposure and the outcome can bias in
either direction, so §9.1 could not be left resting on it.

The instrument was therefore repaired and the frozen evidence re-measured. §9.6
reports both readings.

### 9.6 The corrected instrument, and what it did to the result

The repair removes the wall-clock decision rather than retuning it: the exact
matcher runs to completion on every page. The change is one file and eighteen
lines, alters no metric, threshold, cost function or normalisation, and has **no
free parameter** — there is no budget or tolerance that could have been set to
favour an outcome. It was specified, implemented and demonstrated deterministic
before the corrected result was computed.

*Determinism, measured rather than asserted.* The same 800 predictions were
scored three times under the conditions that used to change the answer —
repetition, four workers against two, forward against reversed page order — and
the per-page scores and severe labels are **bit-identical every time**, compared
by hash rather than tolerance, with **zero fallbacks** in both the captured logs
and the evaluator's own execution record.

*Only what could change, changed.* The claim "we removed only the wall-clock
decision" implies that a page which never fell back cannot move. Of 790
comparable pages, 30 moved score — **all 30 among the 34 that had fallen back,
none outside**. Four pages fell back and did not move, because the approximation
happened to agree there.

*The result.*

| quantity | frozen instrument | deterministic instrument |
|---|---|---|
| accepted / severe | 648 / 42 (6.48%) | 648 / 38 (**5.86%**) |
| abstained / severe | 101 / 16 (15.84%) | 101 / 12 (**11.88%**) |
| rate difference | 9.36pp | **6.02pp** |
| 95% CI (bootstrap) | 2.39 to 16.75pp | **−0.21 to 12.79pp** |
| Fisher exact, two-sided | p = 0.0025 | **p = 0.032** |
| gate decisions changed | — | **0** |

The null is still rejected, so §9.1's claim stands — on weaker evidence than the
first reading showed, and with the magnitude claim withdrawn.

*Why the correction moved the arms unequally, which is the point.* All eight
label changes went **severe → not severe**: the approximation never invented a
clean page, only a dirty one. Four fell in each arm, but the arms are not the
same size, and the fallback was not equally likely in them — 11.88% of abstained
pages against 3.40% of accepted. Four corrections cost the accepted arm 0.62pp
and the abstained arm 3.96pp. **35.7% of the originally measured effect was an
artefact of the measuring instrument, pointing in the direction that flattered
the hypothesis.**

That is the concrete form of the error in the withdrawn attenuation argument. A
misclassification correlated with the exposure does not shrink an effect toward
the null; here it inflated one.

*What the repair restores.* Repeating §9.5's check under the corrected
instrument — the same byte-identical pages, scored from both frozen runs —
**0 of 717 move score and 0 flip the severe label**, against 15 and 5 before.
The 6 score movements that remain are all on pages whose predictions genuinely
differ between runs. §9.5's finding was a property of the measuring apparatus,
and it does not survive the apparatus being fixed.

## 10. Limitations

**One model, one second parser, one corpus.** The gated parser is a single
pinned assembly; the second parser is one frozen campaign of a single system.
Nothing here says the effect holds for another model pair, and the agreement
floor is a property of *this* pair's disagreement distribution rather than a
general constant.

**The severe-error label may be partly an annotation-convention label — and the
evidence for that weakened on the larger sample.** A census of the six
discovery-set severe errors that no signal caught found that all six transcribe
ground-truth-excluded regions (running headers, page numbers, figure captions,
logo text), that their prediction-to-truth length ratio is 0.99, and that on one
fuzzy scan several of the model's "errors" correct typographical errors in the
ground truth. That suggested a share of the "severe" label was convention
mismatch rather than transcription failure.

On the holdout's 42 residuals the excluded-region emission rate is 0.72 against
a corpus rate of 0.74 — indistinguishable. **The excluded-region explanation
does not survive and is withdrawn.** It was built on six pages. What does
survive from that census is the length-ratio and critical-token pattern
(§9.4), which points the other way: the residuals look like ordinary correct
transcriptions and are wrong anyway.

The definition was kept throughout regardless of either finding, because it is
the official metric and because changing it after seeing which pages it
mislabels is exactly the contamination the protocol exists to prevent. The
residual limitation is honest uncertainty: some fraction of the severe label may
still be convention, and this work has not identified which fraction.

**No threshold here is calibrated.** No claim is made that any threshold is
optimal for any population.

**Never comparable to a leaderboard row.** These are subsets; leaderboards are
whole corpora. Published leaderboard figures are quoted where relevant and never
reproduced, and never placed beside these numbers.

**Cost figures are raw GPU cost** at the rate specific runs were billed, on
community capacity, and are not retail prices.

**A ceiling that spending does not move.** On the holdout, 71% of severe errors
are invisible to every signal measured — worse than the discovery set's half,
and measured on a sample large enough that it is unlikely to be a small-sample
artefact. The most expensive configuration spends 2.6x the GPU of a single run
and still accepts the large majority of severe errors. The explanation that part
of that remainder is not error at all did not survive the larger sample, so the
ceiling cannot be discounted that way. It is a property of the signals, not of
the budget.
