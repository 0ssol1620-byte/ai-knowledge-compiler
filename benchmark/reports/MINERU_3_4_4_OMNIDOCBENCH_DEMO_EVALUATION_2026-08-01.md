# MinerU 3.4.4 Pipeline — OmniDocBench Demo Evaluation

Date: 2026-08-01 KST
Claim class: internal reproducibility evidence
Promotion: partial metrics eligible; overall score unavailable

## Executive result

MinerU 3.4.4 pipeline completed all 54 blind inference cases: 18 official
OmniDocBench demo pages, repeated three times, with no failed case and no
timeout. Every page produced the same Markdown SHA-256 in all three repeats.

The valid official metrics show strong text fidelity and table structure on
this small, heterogeneous demo subset. They do not constitute a full
OmniDocBench leaderboard result. CDM was not executed in the validated
portable evaluator lane, so no formula-CDM value and no composite overall
score are reported.

## Frozen identity

| Item | Frozen value |
| --- | --- |
| Candidate | `mineru-3.4.4-pipeline` |
| MinerU source revision | `79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7` |
| Model artifact manifest | `sha256:fc2064a510e5f836b106356b07915935438f62b052d445050278165c20b5e766` |
| Inference bundle | `sha256:72726a56d49eae2f4a290eb0e0af821727e54400603ffd48ab2edb0618fb9014` |
| Inference run summary | `sha256:a10f660307119715a8cd6ae237a8dd14cdcf29023a9ffe440624abf14f14d529` |
| Official evaluator | OmniDocBench `193627ae9e97d89188468ed1ee3b7a856ff76044` |
| Evaluator metric result | `sha256:fdf484fffa8040a22b9604d5981d46e902dde30c0e76595b6f8cc5e862fe2bda` |
| Corpus | OmniDocBench official demo, 18 images |
| Ground-truth SHA-256 | `146690eae39d35ae95eff9d92889876eb45137285cb73cd5af451329411c9207` |
| Inference ground truth mounted | No |
| GPU | NVIDIA GeForce RTX 4090, 24,564 MiB |
| Driver / runtime | 570.158.01 / Torch 2.8.0+cu128 |
| Provider rate observed | USD 0.69 per GPU-hour |

The inference Pod contained only the 18 source images. The annotation JSON and
reference Markdown directory were explicitly absent. Ground truth entered the
workflow only after hashed inference outputs were copied into the separate
local evaluator environment.

## Accuracy results

All three repeats produced the same official metric-result hash and identical
scores.

| Official metric | Result | Direction | Readable companion |
| --- | ---: | --- | ---: |
| Text Edit distance, `ALL_page_avg` | 0.036507 | lower is better | 96.349% `1 - edit` |
| Formula Edit distance, `ALL_page_avg` | 0.153424 | lower is better | 84.658% `1 - edit` |
| Table TEDS, sample average | 0.890803 | higher is better | 89.080% |
| Table TEDS structure-only, sample average | 0.946825 | higher is better | 94.683% |
| Table Edit distance, `ALL_page_avg` | 0.434287 | lower is better | 56.571% `1 - edit` |
| Reading-order Edit distance, `ALL_page_avg` | 0.095701 | lower is better | 90.430% `1 - edit` |
| CDM | unavailable | — | not executed in validated toolchain |
| Overall | unavailable | — | CDM and full benchmark required |

The readable `1 - edit` values are derived presentation aids, not renamed
official leaderboard metrics. TEDS and TEDS structure-only remain the official
sample-average scores.

## Runtime, stability, and cost

| Repeat | Completed | Failed | Wall time | Seconds/page |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 18 | 0 | 123.781 s | 6.877 |
| 2 | 18 | 0 | 127.168 s | 7.065 |
| 3 | 18 | 0 | 124.832 s | 6.935 |

- Mean: 125.261 seconds per 18 pages; 6.9589 seconds/page.
- Population standard deviation: 0.0786 seconds/page.
- Throughput at this batch shape: approximately 517.3 pages/GPU-hour.
- Estimated provider runtime cost: USD 0.0013338/page at the observed
  USD 0.69/hour rate.
- Cost is a runtime estimate. It is not invoice reconciliation and excludes
  storage, transfer, orchestration, and evaluator compute.
- Determinism: 18/18 page-level Markdown hashes matched across all three
  repeats.

## Failures that remain evidence

1. The upstream MinerU 3.4.4 runtime omitted `six`; the first smoke stopped
   with `ModuleNotFoundError`. `six==1.17.0` was then pinned.
2. A first 18-page timing repeat overlapped with unrelated engine installation
   and was excluded from latency claims. Its quality output was retained as
   diagnostic evidence only.
3. The first Windows evaluator attempt used the wrong interpreter and failed
   dependency import. The formal evaluation ran in a dedicated Python 3.10
   environment matching OmniDocBench's declared Python range.
4. CDM's TeX/ImageMagick/Ghostscript rendering chain was not validated in the
   portable evaluator environment. It is unavailable, never coerced to zero.

## Interpretation and routing consequence

This result supports MinerU 3.4.4 pipeline as a reliable medium-cost candidate
for heterogeneous pages where deterministic text and table-structure recovery
matter. It does not justify sole authority for numeric, formula-CDM, or
provenance-sensitive output. Structara should continue to route authority-aware
facts through native sources and validators, and escalate difficult formula,
table-content, or continuity cases to an independent candidate.

## Reproduction artifacts

- Machine-readable evidence:
  `benchmark/reports/mineru-3.4.4-pipeline-omnidocbench-demo-18-evidence-2026-08-01.json`
- Inference runner: `benchmark/runpod_eval/mineru_stage2.py`
- Official evaluator runner: `benchmark/runpod_eval/evaluate_omnidoc_repeats.py`
- Evidence summarizer: `benchmark/runpod_eval/summarize_omnidoc_evidence.py`
- Raw artifacts are retained under the git-ignored
  `artifacts/e2e-model-evaluation/mineru-3.4.4-pipeline-omnidoc-demo-18x3-clean/`
  directory.

## Primary sources

- OmniDocBench repository and evaluator: <https://github.com/opendatalab/OmniDocBench>
- OmniDocBench Apache-2.0 license: <https://github.com/opendatalab/OmniDocBench/blob/main/LICENSE>
- MinerU 3.4.4 source: <https://github.com/opendatalab/MinerU>
