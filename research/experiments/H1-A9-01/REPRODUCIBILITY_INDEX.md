# A9 / R4 reproducibility index

Every number A9 and R4 report traces to a receipt below. The order is the order
the work must be re-run in; each step consumes the receipts of the steps above
it and refuses if their hashes do not match.

Status vocabulary follows `docs/audit/V4_MIGRATION_MATRIX.md`. Nothing here is
authorized for filing or publication: `PATENT_FILING = NOT FILED`,
`PAPER_SUBMISSION = NOT SUBMITTED`.

---

## 1. Discovery (exploratory, sealed)

| step | script | receipt |
|---|---|---|
| official scoring, run A | (evaluator `193627ae9e97`) | `.chatgpt2codex/formal-runtime-v29/stage1/run-0b45d87ed856/evaluation/repeat-1/official-artifacts/` |
| official scoring, run B | same | `run-b75c0b9197cd/evaluation/repeat-1/official-artifacts/` |
| second-parser arm | frozen campaign `folynta-mineru344-quality-candidate-merged-2026-08-09` | `.chatgpt2codex/a9-two-parser-2026-08-18/mineru-staged/` |
| selective acceptance | `selective_acceptance_two_parser.py` | `selective-acceptance-two-parser-2026-08-18.json` |
| proxy arm | `confidence_proxy_arm.py` | `confidence-proxy-arm-2026-08-18.json` |
| instrument repair | `repaired_output_instruments.py` | `repaired-instruments-2026-08-18.json` |
| **evaluator alignment + validation** | `evaluator_aligned_instruments.py` | `evaluator-aligned-instruments-2026-08-18.json` |
| **R4 marginal analysis** | `r4_marginal_analysis.py` | `r4-marginal-2026-08-18.json` |
| missed-case census | `missed_case_forensics.py` | `missed-case-forensics-2026-08-18.json` |
| **seal** | `seal_discovery_set.py` | `discovery-set-seal-2026-08-18.json` |

The seal closes this column. Its manifest hash is
`21ddea8e2ebf73ca7bbebe370028463521974ca368269d65ada3c9ead8bc230f`; anything
downstream that touches a page in it is contaminated.

## 2. Design, fixed before the holdout existed

| step | script / document | receipt |
|---|---|---|
| power calculation | `holdout_power_calculation.py` | `holdout-power-v2-2026-08-18.json` |
| protocol | `A9_CONFIRMATORY_PROTOCOL_2026-08-18.md` rev 2 | — |
| amendment 01 | `A9_PROTOCOL_AMENDMENT_01_2026-08-18.md` | — |
| amendment 02 (instrument, post-hoc — see section 6) | `A9_PROTOCOL_AMENDMENT_02_2026-08-18.md` | — |

## 3. Holdout construction

| step | script | receipt |
|---|---|---|
| provenance audit | `holdout_provenance_audit.py` | `holdout-provenance-audit-2026-08-18.json` |
| freeze + leakage checks | `freeze_confirmatory_holdout.py` | `confirmatory-holdout-800-2026-08-18.json` |
| slice staging | `stage_holdout_slice.py` | `.chatgpt2codex/a9-holdout-800-v1/holdout-provenance.json` |
| upload bundle | `build_holdout_upload_bundle.py` | `holdout-800-source-only.receipt.json` |
| READY derivation | `finalize_holdout_assembly_ready.py` | `ovisocr2-v29-holdout800-ready.json` |

## 4. Holdout execution

| step | script | receipt |
|---|---|---|
| gated-parser run 1 | `run_stage1_v29_r2_v18_holdout_bundle.py` | `.chatgpt2codex/a9-holdout-800-v1/runs/run-*/stage1-receipt.json` |
| gated-parser run 2 | same | same |
| official scoring | evaluator `193627ae9e97` | `.../evaluation/repeat-1/official-artifacts/` |
| **every attempt, including the failed ones** | `holdout_execution_log.py` | `holdout-execution-log-2026-08-18.json` |
| **scored-page criterion** | `scored_page_criterion.py` | `scored-page-criterion-2026-08-18.json` |

Two entries above exist because of things that went wrong, and both are part of
the evidence rather than footnotes to it.

**The execution log** records nine controller attempts, not one. Seven failed at
assembly qualification with the same `TimeoutError` against the sealed
qualifier's 420-second vLLM health deadline, on COMMUNITY hosts whose cold-start
speed varies; run 1 cleared the same deadline, so the deadline was achievable
and the frozen bytes were never edited to make an attempt pass. Every failure
stopped before a page was read, so no failed attempt could influence a
threshold, an operating point or a statistic — the operational/semantic failure
separation the constitution requires. The log refuses if more than the two
pre-registered attempts ever reached inference, which is the check that makes
that claim falsifiable instead of rhetorical.

**The scored-page criterion** exists because 51 of the 800 pages carry no
official text score and therefore leave the primary endpoint's denominator. That
is a bias threat, not a detail: an exclusion correlated with output quality would
strip the worst pages out of the measurement invisibly. Measured — a page is
scored if and only if its *ground truth* contains a `text_block`, `title`,
`reference` or `code_txt` region, reproducing the evaluator on 800 of 800 pages
with no exceptions in either direction. The rule reads no prediction, so the
exclusion is fixed before the model runs. The first attempt at this rule used the
evaluator's 16-category matched-element group and was wrong on 48 pages, which is
why the category set is pinned by a test.

## 5. The single confirmatory test

| step | script | receipt |
|---|---|---|
| primary + secondary | `confirmatory_test.py` | `confirmatory-result-2026-08-18.json` |
| secondary forensics | `holdout_missed_forensics.py` | `holdout-forensics-2026-08-18.json` |
| confirmatory cost-quality tiers | `r4_marginal_analysis.py` | `r4-confirmatory-2026-08-18.json` |
| metric-level reproducibility (secondary) | `metric_reproducibility.py` | `metric-reproducibility-2026-08-18.json` |

That last row found something the design had not anticipated: **the scoring
harness is not deterministic.** 15 byte-identical pages scored differently
across the two evaluation runs and 5 flipped the severe label, because a
wall-clock stall-recovery timeout routes identical bytes through two different
matching algorithms depending on machine load.

The first reading of this — that the noise is independent of the gate and
therefore only attenuates the association — **was wrong, and is retracted.** The
gate not *reading* the evaluator makes it independent of the evaluator's output,
not of the evaluator's failure mode; both the gate decision and the matcher's
running time are functions of the same page. Tested rather than argued, the
fallback fired on 12.87% of abstained pages against 3.70% of accepted ones
(Fisher exact p = 0.00050) and also tracked the outcome, which makes it a
confounder of the primary endpoint rather than benign noise. That is what moved
this from a limitation to a defect requiring re-measurement — section 6.

**Result under the frozen evaluator, superseded by section 6:** 749 scored
pages, 6.48% severe among 648 accepted against 15.84% among 101 abstained,
Fisher exact two-sided p = 0.0025.

**Result under the corrected deterministic evaluator, which is the one that
stands:** the same 749 pages and the same 648/101 partition, **5.86% against
11.88%, Fisher exact two-sided p = 0.032**, one test at the pre-registered
operating point. The null is rejected. The rate difference is 6.02pp with a
bootstrap 95% CI of −0.21 to 12.79pp, which **includes zero** — so the
association is established and its magnitude is not.

Run order matters and is enforced by the driver `after_run2.sh`: the primary
test executes before any secondary analysis touches the holdout outcomes, so no
secondary result can influence how the primary is read.


## 6. Instrument correction and re-measurement

Section 5's last row exposed a defect in the measuring device rather than in the
experiment, so the device was repaired and the same frozen evidence measured
again. The model outputs, the gate, the operating point, the severe-error
definition, the holdout membership, the test and α are untouched; every
corrected receipt is written to a new path so both readings stay on the record.

| step | script | receipt |
|---|---|---|
| is the fallback independent of the gate? | `fallback_independence_test.py` | `fallback-independence-2026-08-18.json` |
| corrected evaluator identity + full diff | `evaluator_version_receipt.py` | `evaluator-version-deterministic-v1.json` |
| determinism contract (repeat / parallelism / order) | `evaluator_determinism_contract.py` | `evaluator-determinism-2026-08-18.json` |
| did it change only the fallback pages? | `correction_locality.py` | `correction-locality-2026-08-18.json` |
| the confirmatory test again | `confirmatory_test.py` | `confirmatory-result-deterministic-2026-08-18.json` |
| before vs after, side by side | `evaluator_correction_comparison.py` | `evaluator-correction-comparison-2026-08-18.json` |
| metric-level reproducibility, corrected | `metric_reproducibility.py` | `metric-reproducibility-deterministic-2026-08-18.json` |
| residual forensics, corrected labels | `holdout_missed_forensics.py` | `holdout-forensics-deterministic-2026-08-18.json` |
| R4 tiers, corrected labels | `r4_marginal_analysis.py` | `r4-confirmatory-deterministic-2026-08-18.json` |

The first row is why the rest exist. The second and third are what makes the
repair auditable rather than asserted: a one-file, 18-line diff with no metric or
threshold in it, and a measured demonstration that identical bytes now produce
identical scores under every condition that used to change them.

The fourth row is the one that can falsify the whole argument. If a page that
never hit a fallback scores differently under the corrected evaluator, then more
than the wall-clock decision was removed and the re-measurement is not the
neutral act it is claimed to be. It refuses rather than reports when that
happens.

The narrative account, including the retracted reasoning that preceded it, is
`EVALUATOR_CORRECTION_2026-08-18.md`.

---

## Contract tests

Run with the repository's normal test command; all are ordinary pytest files.

| file | what it pins |
|---|---|
| `test_evaluator_alignment_contract.py` | the table extraction unit equals the evaluator's own function, executed from its source |
| `test_a9_instrument_contract.py` | instrument behaviour, the LaTeX-math correction, and the fast Fisher against the exact-integer form |
| `test_holdout_provenance_contract.py` | freeze status, disjointness, document-level split, seed reproducibility, threshold validity |
| `test_official_eval_staging_contract.py` | prediction names match page identity, not case id |
| `test_cuda_at_least_contract.py` | the host filter is `>=`, and every wrapper still reaches the payload |
| `test_scored_page_criterion_contract.py` | the confirmatory denominator's exclusion is decided by ground truth alone, and the category set is the minimal measured one |
| `test_evaluator_determinism_contract.py` | the fallback was measured dependent on the gate; deterministic mode nulls every wall-clock field and bypasses the timer thread; the correction is one file; one score hash and one label hash across every condition with zero fallbacks from two independent sources; and only pages that fell back could move |

These run in CI as the `research-instrument-contracts` job in
`.github/workflows/ci.yml`, in their own job rather than through `testpaths` so
research code does not move the core coverage ratchet. The job's second step
runs `assert_contracts_executed.py`, which fails when more than the one
unavoidable skip occurs — the evaluator-equivalence test cannot run without the
private OmniDocBench checkout. That guard is there because this suite has
already been green while verifying nothing: the alignment test computed its
repository root with `parents[3]` instead of `parents[4]`, skipped silently for
a whole session, and the 88-versus-60 table-counting defect it exists to catch
was live the entire time.

## Operational record

`OPERATIONAL_NOTES_2026-08-18.md` — leftover object-storage artifacts flagged
rather than deleted, the marginal 420-second qualifier deadline, the two
cohort-size constants that failed only at 800 pages, and the single
post-unsealing code change.

## Retracted and superseded

Kept, not deleted, so the provenance of the correction is traceable.

| artifact | status | superseded by |
|---|---|---|
| `r4-cost-quality-gating-2026-08-18.json` | **SUPERSEDED** — `evidence_validity` inflated by the LaTeX-delimiter defect | `r4-marginal-2026-08-18.json` |
| `holdout-power-2026-08-18.json` | **SUPERSEDED** — sized on the retracted primary signal | `holdout-power-v2-2026-08-18.json` |
| `confidence-proxy-arm-2026-08-18.json` | **PARTIALLY WITHDRAWN** — its structural and evidence arms used broken instruments | `evaluator-aligned-instruments-2026-08-18.json` |
| A9-12, "cheapest usable signal", p = 0.0014 | **RETRACTED** | `A9_CLAIM_TRIAGE_2026-08-18.md` A9-12 |
| "the second parser is unnecessary" | **RETRACTED** | `R4_OPERATING_TIERS_2026-08-18.md` |
| 64-bit near-duplicate hash, threshold 5 | **SUPERSEDED** — 5 unrelated discovery pairs fell inside it | 256-bit hash, threshold 20 |
| A9-3 "the runtime is reproducible at the metric level", per-page half | **RESCOPED, then resolved** — under the frozen evaluator the aggregate reproduced (58 severe in both runs) while per-page labels did not, the cause being the harness rather than the runtime; the corrected evaluator removes the per-page instability entirely — 0 of 717 byte-identical pages move score, 0 flip label | `metric-reproducibility-2026-08-18.json`, `metric-reproducibility-deterministic-2026-08-18.json` |
| "a share of severe errors are annotation-convention mismatches" | **WITHDRAWN** — held on all 6 discovery residuals, indistinguishable from the corpus rate on 42 holdout residuals | `holdout-forensics-2026-08-18.json` |
| the structural-validity gate as a weak but zero-cost positive | **OVERTURNED** — absolute risk reduction −0.53pp on 749 holdout pages | `r4-confirmatory-deterministic-2026-08-18.json` |
| "the evaluator noise is independent of the gate and only attenuates the association" | **RETRACTED** — measured dependent, Fisher p = 0.00050 | `fallback-independence-2026-08-18.json` |
| every confirmatory figure scored by the frozen evaluator (p = 0.0025, 9.36pp, 58 severe) | **SUPERSEDED** — first reading of a defective instrument, kept for audit | `evaluator-correction-comparison-2026-08-18.json` |
| the coverage-matched agreement-only gate as strictly dominated | **WITHDRAWN** — not dominated under the corrected instrument ($0.195 per additional error) | `r4-confirmatory-deterministic-2026-08-18.json` |
| the stability gate alone as a significant effect | **DOWNGRADED** — Fisher p = 0.055 under the corrected instrument; cheapest tier, not an established one | `r4-confirmatory-deterministic-2026-08-18.json` |
