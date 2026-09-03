# A9 claim triage — 2026-08-18

Phase 0 returned NO-GO on the registered comparison. This document is what that
NO-GO bought: a partition of A9's claims into what is provable now, what becomes
provable with named additional evidence, and what should be abandoned rather than
kept alive.

Nothing here is approved for publication. `PATENT_FILING = NOT FILED`,
`PAPER_SUBMISSION = NOT SUBMITTED`, and what a public claim says is the founder's
call, not this document's.

**Everything in sections ① to ③ is exploratory** and was measured on the
discovery set. It is not merged with the confirmatory numbers; where the two
disagree, the confirmatory one governs and this document is annotated rather
than rewritten.

**The confirmatory holdout has since run, and was then re-scored with a
corrected evaluator.** All confirmatory figures in this document are the
corrected ones. On 749 scored pages of the frozen 800, the pre-registered gate
accepts 648 pages at a **5.86%** severe-error rate against **11.88%** among the
101 abstained (Fisher exact, two-sided, **p = 0.032**, one test). The effect
replicates in direction and significance and is **roughly a third of the
discovery magnitude** — discovery measured 3.9% against 25.0% — a larger shrink
than the winner's-curse discount anticipated, and the bootstrap interval on the
rate difference now includes zero. Full result:
`receipts/confirmatory-result-deterministic-2026-08-18.json`; the defect that
made re-scoring necessary and both readings: `EVALUATOR_CORRECTION_2026-08-18.md`;
tiers and complementarity: `R4_OPERATING_TIERS_2026-08-18.md`.

Two exploratory claims below are **overturned** by that run and are marked in
place: the structural signal (§③) is not merely weak but has a negative risk
reduction on the holdout, and the four residual-case hypotheses in §② split two
reproduced / two not.

**Corpus for every number below**: 198 of 200 OmniDocBench hard-subset pages
(2 pages carry no official per-page text score for either parser and are excluded
by name in the receipt). Sources are page images. Evaluator revision
`193627ae9e97`, one config, one ground-truth file, both parsers scored under it.
Ground truth is used only as the correctness outcome; no gate signal sees it.

---

## ① Provable now

**A9-1. Two-parser agreement concentrates error rather than merely correlating with it.**
Splitting the corpus at the median agreement, the official severe-error rate
(text edit distance > 0.10) is 1.0% among agreeing pages and 11.1% among
disagreeing pages. Abstaining on the 10% of pages where the parsers disagree
most leaves an accepted-set error of 3.9% against an abstained-set error of
25.0% (Fisher exact, two-sided, p = 0.0032).

*The caveat is part of the claim.* That operating point was selected after
looking at 4 error thresholds x 3 agreement signals x 10 coverage points. Under
Bonferroni correction for those ~120 comparisons the threshold is p ≈ 0.0004 and
p = 0.0032 does not survive it. What is defensible is the **effect estimate and
its direction**, which is monotone in coverage and consistent across all four
error thresholds — not a confirmatory significance claim. The preregistration's
own rule ("do not tune the registered endpoint after observing holdout outcomes")
is what forces this reading.

**Confirmatory update.** The agreement half was carried into the frozen combined
gate and its contribution replicated: on the holdout it catches 6 of 50 severe
errors, all 6 of which stability does not catch. As a *standalone*
coverage-matched gate it costs $0.27/1,000 more than the stability gate for 1.4
additional avoided errors per 1,000 pages, so its value is as the second signal,
not as the cheap one. The exploratory 3.9%-versus-25.0% contrast above is not
the holdout's magnitude; the holdout measures 6.5% against 15.8%.

Receipt: `receipts/selective-acceptance-two-parser-2026-08-18.json`.

**A9-2. Run-to-run output instability is an error signal, and needs no second parser.**
Two independent runs of the same immutable assembly, on different hosts, at
`temperature: 0.0`, produced byte-identical output on 180 of 198 pages. The 18
unstable pages carry a severe-error rate of 22.2% against 4.4% for the stable
ones (5.0x, Fisher p = 0.0151); at the looser threshold, 27.8% against 9.4%
(p = 0.0343).

This matters more than A9-1 for deployment: it requires only running the same
input twice, so it gates a single-model system. It is **not** a model
self-confidence and must never be named as one.

**Confirmatory update — replicated as the cheapest tier, but no longer
significant on its own.** On the holdout 32 of 749 pages are unstable; the
stability gate alone reaches 95.7% coverage, 6.28% selective error, absolute risk
reduction 0.40pp, at **$0.103 per severe error avoided — the cheapest error
removal measured anywhere in A9**. It catches 5 of 50 severe errors, all 5 of
which cross-parser agreement does not catch. Its own accepted-versus-abstained
contrast is **Fisher p = 0.055** under the corrected evaluator, so it is the
cheapest configuration measured rather than an established effect.

Receipt: `receipts/confidence-proxy-arm-2026-08-18.json`.

**A9-12. RETRACTED — `evidence_validity` is not a usable signal.**
This entry previously claimed the strongest and cheapest separation in A9
(p = 0.0014, zero marginal GPU cost) and was the confirmatory primary signal.
Instrument validation destroyed it. The `orphan_currency` rule matched the
opening `$` of LaTeX math spans, and this corpus typesets prices that way
(`$\$$6-$\$$18`), so the gate was selecting formula-dense pages — which are
harder — rather than malformed ones.

Corrected to exclude math spans, the same instrument flags 6 pages rather than
17 and reaches p = 0.0442. Two further validation results disqualify it
independently of the p-value:

- it detects **none** of nine injected semantic corruptions (number, sign, date
  and unit changes, entity loss, row and column swap, cell omission, duplicated
  cell);
- it fires on 8.5% of human-annotated ground-truth documents against 3.0% of
  model outputs — more often on known-correct text than on the text under test.

What replaced it as the confirmatory primary is the combined stability +
agreement gate, whose underlying instrument did pass: false-positive rate 0.000,
detection 1.00 for sign changes, 1.00 for date changes, 0.66 for number changes.

Receipts: `receipts/evaluator-aligned-instruments-2026-08-18.json`,
`receipts/r4-marginal-2026-08-18.json`.

**A9-13. The signals are largely complementary, so the second parser is not redundant.**
**CONFIRMED on the holdout, more strongly than on discovery.** Jaccard overlap
between the two signals' *flagged page* sets is 0.067 on 749 pages against 0.091
on 198; of the 11 severe errors the two catch between them, **all 11 are caught
by exactly one** — on corrected labels the intersection is empty.
Adding agreement to stability gains 6 severe errors; adding stability to
agreement gains 5. Receipt:
`receipts/r4-confirmatory-deterministic-2026-08-18.json`.

The original discovery text follows.

Execution instability flags 18 pages, low agreement flags 18, and only 3 pages
are flagged by both — Jaccard 0.091. Of the 12 severe errors, stability alone
catches 3, agreement alone 2, both 1, `evidence_validity` alone 2, and 4 are
caught by none of the three. Two signals that overlap this little are not
substitutes, and an earlier reading of this data as "a second parser is
unnecessary" was wrong: the parsers catch different errors, and combining all
three raises the caught share from 6/12 to 8/12.

**A9-3. The runtime is reproducible at the metric level — RESCOPED on the holdout, then RESTORED by the instrument correction.**

**Resolution.** The per-page half failed because of the evaluator, not the
runtime, and the corrected evaluator settles it: re-scoring both frozen runs
deterministically, **0 of 717 byte-identical pages move score and 0 flip the
severe label** (against 15 and 5 under the defective instrument). The aggregate
also tightens — mean text edit distance 0.023542 against 0.023574, and 50 severe
pages in both runs. The claim holds at both levels.
Receipt: `receipts/metric-reproducibility-deterministic-2026-08-18.json`.

The original rescoping, and the evidence that produced it, follow.
**The aggregate claim holds and strengthens; the per-page claim does not, and the
reason is our harness rather than the runtime.** On 749 holdout pages scored
twice under the frozen evaluator: mean text edit distance 0.02853 versus
0.02807, and **58 severe pages in both runs** — the same count, from two
independent inference runs. (Under the corrected evaluator the count is 50; the
figures in this paragraph describe the defective instrument, which is the point
of the paragraph.)

But 15 **byte-identical** pages received different scores, and 5 flipped the
severe label. A byte-identical prediction cannot change score under a
deterministic scorer, and the cause is the repository's own stall-recovery
wrapper: a wall-clock timeout abandons `quick_match` for a chunked Hungarian
fallback, and which pages exceed it depends on machine load (34 fallbacks in one
run, 28 in the other, 12 asymmetric). 11 of the 15 hit a fallback in at least
one run.

So the correct statement is: **the runtime reproduces at the aggregate metric
level, and the scoring harness does not reproduce at the per-page level.** The
discovery-set version of this claim below reported "191 of 198 per-page text
scores identical" as a property of the runtime; part of that 7-page difference
was probably the harness, and could not have been distinguished at the time
because only the model was varied. Receipt:
`receipts/metric-reproducibility-2026-08-18.json`.

The original discovery text follows.

Two independent runs: text edit distance 0.0197 and 0.0197, formula 0.2517 and
0.2517, reading order 0.0666 and 0.0667, table TEDS 0.7903 and 0.7974. 191 of
198 per-page text scores identical, median absolute difference 0.00000, maximum
0.0033. This is the R5 weakness, closed for this assembly on this corpus.

**A9-4. A corpus can look nearly perfect and still lose the tokens that matter.**
Of the 116 pages whose official text edit distance is ≤ 0.01, 61 lose at least
one ground-truth critical token (a number, currency amount, unit or sign) that
formatting differences do not explain. This is the direct argument for why an
edit-distance gate is insufficient and a critical-token gate is not redundant.

Receipt: `.chatgpt2codex/.../critical-token-measurement.json`.

---

## ② Provable with named additional evidence

**A9-5. Selective acceptance beats unconditional processing (confirmatory).**
**DISCHARGED — the evidence it named now exists.** The requirement was one
operating point and one signal fixed before looking, on a corpus not used to
choose them, sized by a power calculation. All three were met: protocol
revision 2 plus amendment 01 fixed the gate, the endpoint and a single Fisher
exact test; the 800-page holdout was frozen under four leakage checks with zero
overlap against the sealed discovery set; the sample size came from a
winner's-curse-discounted power calculation.

Result on 749 scored pages: **5.86% severe among 648 accepted against 11.88%
among 101 abstained, Fisher exact two-sided p = 0.032**, rejecting at α = 0.05
in the discovery direction. Rate difference 6.02pp, bootstrap 95% CI
**−0.21 to 12.79pp**. This is the one confirmatory statement A9 is entitled to
make, and it is scoped to this model pair, this corpus and this operating point.

**The claim is the association, not its size.** The pre-registered decision rule
rejects; the interval on the rate difference includes zero. Any statement of how
*much* the gate reduces severe errors is unsupported.

Receipt: `receipts/confirmatory-result-deterministic-2026-08-18.json`.

**A9-6. Source-grounded acceptance on scans.**
Phase 0 called this arm unavailable because the sources have no native text.
That was a statement about `native_text_source_check`, not about the arm. The
material for a scan-native version exists and is local: all 10,205 ground-truth
regions carry a `poly`, the 200 source images are present, and the second parser
emits per-block `bbox` and `type` at inference time. Two designs follow, both
CPU-only and both using ground truth solely as the correctness outcome:

- *region evidence alignment* — reconcile the parser's own block geometry with
  the ink actually present on the page, so a column read as blank while carrying
  text is caught without OCR and without ground truth;
- *OCR-independent visual verification* — per-region ink density against emitted
  character count, which catches gross omission and gross hallucination in both
  directions.

A third, a small human-verified gold subset, needs a person; blind judgement is
not an agent's to make.

**A9-14. The measurement unit was already the evaluator's; the 88-vs-60 gap is the model.**
The instrument counted 88 tables where the official evaluator scored 60, and the
suspected cause was nested `<table>` double counting. It was not. The evaluator
extracts outermost tables with a stack scanner; that function is vendored
verbatim and returns 88 on the same predictions, matching on every page, and the
corpus contains no nesting at all. The evaluator reports 60 because its targets
are the 60 ground-truth regions, and the model **over-segments** — 29 tables
where the truth annotates 26, 25 where it annotates 13, 18 where it annotates 6.
The equivalence is now pinned by a test that executes the evaluator's own
function and diffs it.

**A9-15. Half the severe errors are invisible to every signal, and some may not be errors.**
Six of twelve severe errors evade both gate halves. The census: no tables on any
of the six, prediction-to-truth length ratio 0.99, 2.8 mean critical-token
mismatches against 33.3 for the errors that are caught, edit distances clustered
at 0.114–0.139 just over the threshold. Reading two of the six source images
showed the mechanism — the model transcribes running headers, page numbers and
logo text that the annotation marks `abandon`, and reads a two-column list
column-by-column where the annotation reads it row-by-row. Across the six it
emitted 12 of 12 annotation-excluded regions, against 63% on the rest of the
corpus. On the fuzzy-scanned page several of its "errors" correct ground-truth
typos.

This is a census of six pages, not a finding. If it holds up, part of what the
0.10 edit-distance threshold labels severe is annotation-convention mismatch,
and no acceptance signal can catch those because nothing is wrong with the
output.

**Confirmatory update — it half held up, and the half that failed is the
interesting one.** Re-checked on the holdout's 42 residual severe errors as a
secondary exploratory analysis:

| discovery hypothesis | holdout verdict |
|---|---|
| missed cases have a length ratio near one | **REPRODUCED** (0.87 missed vs 4.13 caught) |
| missed cases lose fewer critical tokens | **REPRODUCED** (6.5 vs 239.1 mismatches) |
| missed cases carry fewer tables | NOT_REPRODUCED (0.14 vs 0.13) |
| missed cases transcribe excluded regions more | **NOT_REPRODUCED** (0.72 vs corpus 0.74) |

The two that reproduced say one thing: the residuals *look* like correct
transcriptions of about the right length containing about the right numbers, and
no ground-truth-free signal separates them. The two that failed include the
annotation-convention hypothesis, which was the most consequential — it argued
that part of the severe label is not error at all. On 42 cases the excluded-region
emission rate is indistinguishable from the corpus rate. **That argument is
withdrawn as an explanation of the residuals**; it was built on six pages and did
not survive forty-two.

The fraction is also worse at scale: 36 of 50 severe errors are invisible to
every signal, 72% rather than the discovery set's half.

Receipt: `receipts/holdout-forensics-deterministic-2026-08-18.json`. No p-value is attached;
these were not pre-registered endpoints.

**A9-7. Structural validity as a proxy — OVERTURNED on the holdout, and harmful.**
**The holdout answered the question this claim said needed a better corpus, and
the answer is worse than "uninformative".** On 749 pages the structural gate's
absolute risk reduction is **−0.53pp**: the pages it flags are *cleaner* than the
pages it accepts, and abstaining on its signal makes the accepted set worse than
doing nothing. It costs no extra GPU, which is the only reason it was still in
the table. It must not be shipped, and the "needs a corpus with table defects"
framing below is superseded — a corpus with 3.8x more pages was found and the
signal went the wrong way on it.

The original discovery text follows.

The original pair of instruments were both broken and their null results carried
no information; both have been rebuilt against HTML and validated by injection.
The evidence half became A9-12. The structural half did not: 196 of 198 pages
score identically, so a median split leaves 2 pages on one side and the test is
uninformative (1/2 versus 21/196, p = 0.21). That is a property of this corpus,
not of the instrument — the model rarely emits a malformed table here. It needs a
corpus with table defects in it before anything can be said either way.

**A9-16. The scan-image source-grounded verifier is built, and does not work.**
Both designs from `SCAN_SOURCE_GROUNDED_DESIGN_2026-08-18.md` are implemented in
`scripts/ink_coverage_verifier.py`: Otsu ink density on the source image, and
ink per emitted character. CPU only, no OCR, no ground truth, no licence
question. On the 198-page discovery corpus it **does not separate severe error**
at any cut — top decile 0.000 vs 0.068 (p = 0.62), top quartile 0.098 vs 0.048
(p = 0.19), median split 0.060 vs 0.061 (p = 1.00). The highest-ink-per-character
decile contains no severe errors at all.

Two honest notes rather than one. First, the deletion-injection validation
returns 1.00 at every fraction and that number is close to a tautology: removing
characters raises ink-per-character by construction, so it shows the arithmetic
points the right way and nothing more. Second, the predicted confound is real and
measured — figure-bearing pages sit at 0.264 against 0.198 without, because ink
from a photograph has no characters to divide by.

Published as **not supported**, in the same way the campaign published blind
quality detection as not supported. A9-6 moves from ② to ③ for this design; a
region-aligned version that uses the second parser's own block geometry rather
than whole-page ink remains untested and stays in ②.

Receipt: `receipts/ink-coverage-verifier-2026-08-18.json`.

**A9-8. Head-to-head source-grounded versus agreement.**
Needs one corpus where both arms run: documents with a native text layer *and*
two independent parsers. Neither condition holds today — the PDF suites have one
parser and no staged sources, the two-parser suite is scans.

---

## ③ Abandon

**A9-9. The model self-confidence arm, on this runtime.**
The frozen runtime emits no per-case confidence, and the preregistration forbids
reconstructing one. This is not "later": it is abandoned unless a runtime that
genuinely emits confidence enters the comparison, and the observable proxies in
A9-2 must never be renamed into it.

**A9-10. The original primary endpoint as registered.**
"Does a source-grounded gate identify a higher-precision accepted subset than
agreement or self-confidence" cannot be answered on frozen data, because the arms
do not coexist on any frozen case set. Keeping it as the headline would mean
either imputing features the preregistration forbids or quietly changing which
cases the comparison runs on.

The replacement is narrower and stronger: **acceptance gating beats unconditional
processing, and the signal that drives it is available without a second model.**
That claim survives the objection the original invites — "you chose a weak
comparator" — because its comparator is the system's own current behaviour.

**A9-11. Any comparison against a public leaderboard row.**
This is a 200-page hard subset; leaderboards are whole corpora. Quoted, never
reproduced, never placed beside these numbers as if same-condition.

---

## What broke while measuring this

Recorded because the same failures will recur:

| Defect | Effect if unnoticed |
|---|---|
| predictions named by `case_id`, evaluator matches page names | 184 of 200 pages scored as empty; every metric understated |
| official TEDS below 0 on one table | harness refused the whole run; clamping would have improved a published number |
| ground truth assembled from 2 of 14 content categories | 178 of 200 pages reported "mutated"; the surplus was real page content |
| number formatting counted as loss *and* surplus | 39% of apparent losses were `1,000` versus `1000` |
| structural detector aimed at the wrong table format | a null result that meant nothing |
| consistency check compared the output with a whitespace-normalised copy of itself | the strongest signal in A9 was reported as absent |
| `orphan_currency` matched LaTeX math delimiters | a typesetting proxy was promoted to confirmatory primary signal at p = 0.0014 |
| no negative control on any instrument | a detector firing on 24% of known-good text read as a defect detector |
| 64-bit perceptual hash on dense scanned text | a corpus freeze refused on 19 pairs that were not duplicates; minimum distance between unrelated pages was 3 bits |
| contract test computing its repository root one directory too high | the evaluator-alignment suite skipped silently and stayed green while the 88-versus-60 defect it exists to catch was live |
| the evaluator's 16-category text group read as the scored-page rule | 48 caption-only and page-number-only pages misclassified as carrying a text score |

Most of these made the system look worse than it is, one hid a real signal, and
one made it look **better** — the LaTeX-delimiter defect manufactured the
strongest result in A9 out of nothing. That last direction is the dangerous one,
and it was caught only because the instrument was run against known-good text.
Every instrument here now carries a negative control for that reason.

The distribution is not reassuring. It means the instruments were not calibrated
against the artifact they measure, and an error in the flattering direction
would have been just as invisible as the others. Two entries deserve separate
notice because they are failures of the *checking* layer rather than of a
measurement: a contract test that skipped itself into permanent green, and a
freeze guard that refused valid data. A test that cannot fail and a guard that
cannot pass are the same defect seen from two sides — an instrument nobody
verified. Both are now pinned, the first by a CI step that fails when the suite
skips more than its one unavoidable test, the second by a threshold derived from
19,900 measured unrelated pairs.
