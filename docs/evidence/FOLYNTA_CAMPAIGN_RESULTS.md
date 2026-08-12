# FOLYNTA — public benchmark campaign, results and state

**As of 2026-08-09.** Every number below comes from a receipt in this repository.
Where a result is still being measured it says so; where a result went against
the hypothesis it is written down rather than dropped.

The artifacts are under `docs/evidence/artifacts/`, each with the sha256 that
`docs/evidence/folynta-public-claims-pack.json` binds it to. A figure with no
artifact behind it does not belong in this file.

---

## 1. What was measured

5,132 documents across three public benchmarks, scored by each benchmark's own
official evaluator at a pinned revision.

| benchmark | documents | evaluator revision |
|---|---:|---|
| ParseBench | 2,078 | `1d460294` |
| OmniDocBench | 1,651 | `193627ae` |
| olmOCR-Bench | 1,403 | `cfa88c1e` |

The pipeline under test is MinerU 3.4.4 (VLM engine) as the extraction model,
inside the FOLYNTA recovery runtime. The runtime is what this campaign is about;
the base model is a component of it.

---

## 2. Completion and recovery

**5,131 of 5,132 documents produced output — 99.98%.**

This is the share that finished, not a measure of whether the output was right.
The two are different questions and the claims pack forbids merging them.

The single unresolved case is `parsebench:docs/text/text_sparse__blank`, a page
whose source is blank. Its empty output is correct, and the harness recording it
as a failure is a false positive discussed in §7.

**Of the documents that actually broke, 99.94% were recovered.**

```
documents that needed recovery        1,797
recovered                             1,796
recovered only after >1 round            11
attempted and never recovered             1
```

The denominator is the retry plan, not the corpus. Quoting 99.94% without it
reads as a completion rate.

Delivery split across the campaign:

```
baseline run                          3,337 documents
operational recovery lane             1,794 documents   (35.0% of the corpus)
```

Without the recovery lane, 1,794 documents would carry no output at all — they
would be absent from the corpus, not merely lower quality.

---

## 3. Accuracy

### olmOCR-Bench — 80.6%

```
overall            80.6%        (7,137 of 8,413 checks)
95% CI             79.62–81.57
```

This is a pass rate over 8,413 adversarially chosen checks. The highest published
system scores 83.1, so the reference point is not 100. **72.3% of documents carry
at least one failure**, which is why nothing here implies flawless output.

Per document type, because a single average hides a 99% to 36.9% spread:

| document type | checks passed | accuracy |
|---|---:|---:|
| Standard digital documents | 1,380 / 1,394 | 99.0% |
| Documents with headers and footers | 722 / 760 | 95.0% |
| Table-heavy documents | 904 / 1,022 | 88.5% |
| Academic papers with equations | 2,505 / 2,927 | 85.6% |
| Multi-column layouts | 718 / 884 | 81.2% |
| Long documents in small type | 351 / 442 | 79.4% |
| Old scans containing equations | 363 / 458 | 79.3% |
| **Low-quality scans** | **194 / 526** | **36.9%** |

Degraded scans are the hard case. If that is the corpus, 36.9% is the number to
plan against, not the average.

### OmniDocBench — customer-facing fidelity

```
text character match          94.2%     (edit distance 0.0583)
reading order match           85.9%     (edit distance 0.1408)
table structure accuracy      95.5%     (TEDS structure-only)
table full accuracy           92.6%     (TEDS)
```

These measure something different from the 80.6% check pass rate. Where both
appear, each must be labelled.

### ParseBench

```
rule failures                39,413 across 2,553 evaluated examples
```

---

## 4. What the recovery lane is worth

The strongest result in the campaign, and the one that distinguishes the runtime
from the model inside it.

**Single-variable comparison.** Model, evaluator revision, corpus, source
manifest, test set and settings identical. The only difference is whether the
582 documents the recovery lane delivered carry their content.

```
                        with recovery      recovery disabled
olmOCR-Bench overall    80.6               53.7
95% CI                  79.62–81.57        52.62–54.93
rule failures           1,276              3,818
```

The confidence intervals do not overlap.

Two readings of the same gap, named for their denominators because one number
called "relative delta" is how the flattering one gets quoted:

```
score share lost without recovery     33.37%   (0.269 / 0.806)
score uplift over no recovery         50.09%   (0.269 / 0.537)
```

Per document type, the lane matters most exactly where extraction is hardest:

| type | with | without |
|---|---:|---:|
| Standard digital | 0.990 | 0.579 |
| Table-heavy | 0.885 | 0.488 |
| Multi-column | 0.812 | 0.484 |
| Academic w/ equations | 0.856 | 0.528 |
| Low-quality scans | 0.369 | 0.266 |
| Headers/footers | 0.950 | 0.961 |

**The headers/footers row goes up without recovery, and that is not noise.**
Tests of the "absent" type check that text is *not* present, and an empty
document passes them trivially — their pass rate rises from 0.9453 to 0.9635.
The no-recovery score is therefore generous, not harsh.

### The other two benchmarks agree

```
ParseBench rule failures          39,413  →  82,163
ParseBench table GriTS             0.9017 →  0.5321
ParseBench content faithfulness    0.8376 →  0.5243
OmniDocBench text edit distance    0.0583 →  0.2640
OmniDocBench table TEDS            0.9257 →  0.7140
```

**One caveat that must travel with the ParseBench figures.** Removing recovery
makes the layout group's pass rate go *up*, 0.757 → 0.770, because a document
with no content has no elements to score: the denominator falls from 40,287 to
23,025. Quote the absolute failure counts. A rate alone makes no-recovery look
better.

---

## 5. Reproducibility

A stratified audit re-ran 128 cases per suite, three times each — 1,152
inferences — to separate pipeline variance from evaluator variance.

```
identical markdown across all three repeats     384 / 384 documents   (100%)
stable terminal status across repeats           384 / 384             (100%)
```

Official scores across the three repeats:

```
olmOCR overall score            0.7763, 0.7763, 0.7763    (σ = 0)
olmOCR rule failures            208, 208, 208             (σ = 0)
ParseBench rule failures        2,557, 2,557, 2,557       (σ = 0)
OmniDocBench element failures   209, 210, 210             (σ = 0.47)
```

**The only variance in the entire audit is one OmniDocBench element failure**,
and since the pipeline emitted byte-identical markdown all three times, that
variance is in the evaluator, not in us.

Latency was stable too — ParseBench range 35 s over runs averaging 9,854 s
(0.36%).

---

## 6. Beyond extraction — what can be proved about compilation

The public benchmarks score extraction only. No public benchmark scores whether
a corpus was organised well, and inventing one would be marking our own homework.
The compilation stages are deterministic, so their properties are provable
instead.

Measured over 1,000 documents and 7 built-in blueprints:

```
architecture plans stable across repeats           yes, all 7 blueprints
distinct blueprints produce distinct plans         yes
unresolved internal links in an emitted vault      0
files lost silently across 5 merge policies        0
export targets from one compiled core              4  (obsidian, ontology, neo4j, rag)
```

**Vault compilation is fail-closed**, and the numbers show what that costs:
of 1,000 documents offered, 596 compiled and **404 were refused** — every refusal
for a link the compiler could not resolve. The dominant cause is a referenced
figure asset that was not supplied alongside the markdown. A vault with a broken
link cannot be emitted, by design.

**Merge safety, measured on a real overlap** (601 existing files, 902 incoming,
301 genuine conflicts): no policy loses a file silently. `error` and
`replace_same_source` are correctly reported as *not* safe to apply against that
overlap; `keep_existing`, `rename_incoming` and `update_managed` are.

These are structural guarantees. They say nothing about whether the extracted
text is correct — §3 measures that separately.

---

## 7. Results that went against us

Written down because a campaign that only records its wins is not evidence.

### Blind quality detection — **hypothesis not supported**

*Can prediction-only signals, with no ground truth, select the documents that
official evaluation shows are worst?*

Measured over 5,116 cases and 42,506 official failure records: **no.**

```
budgets where blind ranking beats random          none
budgets where blind ranking beats length-only     none
```

Ranking documents by prediction length alone — which requires no detector at all
— reaches more failure mass at every budget tested. The reason is structural:
failure mass scales with document size, so selecting for defects selects against
size and therefore against mass.

Two individual signals do discriminate, and the honest reading is that they
discriminate for *density*, not mass:

```
empty_output          20 flagged   21.5 failures/1k chars   (corpus: 3.7)
alpha_ratio < 0.7    640 flagged    1.7 failures/1k chars
```

The "flag anything above zero" operating point reaches recall 1.0 with 1,418
false positives out of 5,116 — it flags the whole corpus, which is not selection.

**This is not shipped as a product feature and no detection rate is claimed.**

### The harness cannot tell an empty page from an empty result

Four documents were classified as failures for producing no markdown. One of
them, `parsebench-f6545fdd1d015f31402c0fc9`, measures **100.00% near-white** —
it is a blank page, and zero characters is the correct output. The campaign's
single unresolved case is likewise named `text_sparse__blank`.

The failure taxonomy checks whether output is empty. It does not check whether
the *source* was. That is a real gap in the measurement, and the numbers above
are conservative by these cases rather than wrong.

### Two documents were scored as empty when they were not

An audit of the composite found two cases whose run summary records `failed` with
the empty-string hash while a non-empty extraction (145 and 72 bytes) sits on
disk. The published evaluation followed the summary and scored them as empty.

**The published figures are conservative by two documents.** The discrepancy
predates this session's work and is recorded rather than corrected, because
correcting it would change what the published baseline measured.

---

## 8. Cost

```
GPU cost per 1,000 pages, healthy worker      $1.23
GPU cost per 1,000 pages, whole campaign      $5.92
throughput, healthy worker                     600 pages / pod-hour
GPU class                                      RTX 4090 @ $0.74/hr
```

The healthy-worker figure is one worker that ran without stalling — the rate a
healthy fleet sustains. The whole-campaign figure includes every stall, retry and
failed worker the campaign actually hit: 41.03 pod-hours for 5,132 documents.

**Both are raw GPU cost, not a price.** They exclude engineering, orchestration,
storage, egress, support and margin, and must not be placed beside a competitor's
retail price.

The spread between them is itself a finding: **operational failure cost 4.8× the
GPU budget of a clean run.**

---

## 9. Where this sits against published systems

Our measurement, on the same public dataset
(`allenai/olmOCR-bench` @ `54a96a6f`) and an unmodified scoring path:

```
MinerU 3.4.4 + FOLYNTA recovery runtime     80.6   (95% CI 79.62–81.57)
MinerU 3.4.4, recovery lane disabled        53.7   (95% CI 52.62–54.93)
```

Published board, retrieved 2026-08-08 from `github.com/allenai/olmocr`:

```
Chandra OCR 0.1.0       83.1 ± 0.9
Infinity-Parser 7B      82.5
olmOCR v0.4.0           82.4 ± 1.1
PaddleOCR-VL            80.0 ± 1.0
Marker 1.10.1           76.1 ± 1.1
DeepSeek-OCR            75.7 ± 1.0
MinerU 2.5.4            75.2 ± 1.1
Mistral OCR API         72.0 ± 1.1
```

**What is defensible:** on the same public dataset and an unmodified scoring
path, the pipeline scores 80.6. Disabling only the recovery lane drops the
identical pipeline to 53.7, below every system on the board. The recovery lane,
not the base model, is what places the pipeline in the competitive range.

**What is not defensible, and why:**

- *"We beat MinerU by 5.4 points."* The published MinerU row is 2.5.4; we ran
  3.4.4. That gap is confounded by model version.
- Our evaluator checkout is a single-commit copy of jina-ai/olmocr-bench adding
  lxml, plus a local 7-line Windows path-separator fix. Scoring logic is
  unchanged, but the checkout is not AllenAI's own.
- The board reflects the state around olmOCR v0.4.0 (October 2025). Listed
  systems may have improved since.

Those rows are quoted, not reproduced by us.

---

## 10. Still being measured

**The targeted quality retry.** 372 documents with the highest officially
attributed failure mass were re-run on fresh workers with a different worker
assignment than the one that produced them.

```
delivered by the retry                371 / 372
overlay applied to the candidate      368 / 368   (inference failures: 0)
merged candidate corpus               5,132 / 0
official re-evaluation                running
no-regression gate                    pending
```

Two facts from the retry that stand on their own:

**315 of 368 documents re-ran byte-identical.** Only 53 files differ between the
baseline corpus and the candidate. Same model, same settings, different worker,
different day.

**Three documents that every prior MinerU run failed to produce were recovered by
giving them a worker with time.** Worker 6's ParseBench run hit its suite wall
clock at 48 of 51 and exited 124; the three it never attempted were rerouted to
an idle worker and all three completed:

```
                     alternate model lane      MinerU, given time
041add7de36b…        PaddleOCR  1,531 chars    1,533 chars
4a3a15df06e5…        PaddleOCR    528 chars   14,256 chars
e06796b65216…        PaddleOCR    783 chars   19,399 chars
```

Routing to a different model rescued the case. Re-running the *same* model with
adequate wall clock produced 18–27× more content on two of them.

No improvement figure will be published before the no-regression gate runs.
`quality-retry-improvement` is withheld in the claims pack until then.

---

## 11. Publishability

`docs/evidence/folynta-public-claims-pack.json` — 15 claims, generated from the
receipts, each bound to its artifact by sha256.

```
approved      11
conditional    2     publish only with the stated conditions
withheld       2     quality-retry-improvement, blind-quality-detection
```

Every approved claim carries the sentence that must accompany its number and the
phrasings that must not appear. The hard rules:

- The 99.98% completion rate is never described as accuracy.
- Every rate carries its denominator.
- Leaderboard rows for other systems are quoted, never claimed as reproduced.
- The $1.23 is GPU cost, never placed beside a competitor's price.
- `benchmark_slice` values (`old_scans.jsonl` and similar) are internal
  identifiers and never render.
- The 36.9% low-quality-scan row stays in the table.

All 14 cited artifacts are in the repository and hash-verify from a clone. That
was not true a day ago: eleven lived only on the machine that produced them and
nine claims cited a path with no hash at all.

---

## 12. What the campaign learned about running itself

The recovery product had to recover its own campaign several times. These are
recorded because they are the same class of problem the product addresses.

**A watchdog deleted four working pods mid-run**, losing a retry at 117 of 372.
Two causes: a deadline set before an unrelated outage and never recalculated, and
a provisioner that started the watchdog with no liveness probe at all — so the
"stop if busy" protection existed in code and had never once been active. The
probe now resolves the pod's current address from the provider at the deadline,
because a restarted pod comes back on a different port and an unanswered probe is
not evidence of an idle pod.

**Every worker stopped within one second of each other.** That is the shape of an
exhausted account, not nine independent failures, and buying replacements cannot
fix it. The supervisor now names that pattern and stops instead of spending into
it.

**Stopping a pod keeps `/workspace` and discards the container disk.** A restart
came back without the MinerU CLI. Bootstrapping is now part of resume.

**A worker running out of wall clock is not a document that cannot be processed.**
§10 is the measurement of that distinction.

---

## 13. State of the repository

```
backend test suite            1,989 passed
ruff · mypy (209 files)       clean
migration chain               single head over 33 revisions, both guards agree
repository policy validator   passed
web: eslint · tsc · vitest    clean · clean · 259 passed
web: next build               green
RunPod resources              0 pods, 160 GB volume released, teardown receipt
```

Two gates were added because the failures above were invisible to the suite:

- `tests/unit/test_migration_graph.py` — fails on a forked revision graph, a
  second head, a dangling parent, a cycle, or an unreachable revision. Verified
  against the real duplicate-0023 case.
- The claims pack generator refuses to emit a claim citing a git-ignored file, or
  a path without a hash.

**Known limitations, unfixed:**

- The RunPod API key has no billing scope, so account balance cannot be read
  preemptively — only inferred after the fact from a provider-wide stop.
- No network volume, so a stopped pod still loses its container disk.
- Cost figures are runtime-rate estimates from the provider's pod API, not
  invoices.
