# MinerU 3.4.4 VLM c1 — OmniDocBench Demo Evaluation

Date: 2026-08-01 KST
Claim class: internal reproducibility evidence
Promotion: partial metrics eligible; overall score unavailable

## Executive result

MinerU 3.4.4 VLM completed all 54 blind inference cases after its runtime was
constrained to one concurrent request: 18 official OmniDocBench demo pages,
repeated three times, with no failed case and no timeout. All 18 page-level
Markdown hashes were identical in all three repeats.

This lane produced the best valid partial accuracy of the three formally tested
candidates on this small demo subset, but it was also the slowest and most
expensive. That is evidence for selective escalation, not for sending every page
through the VLM lane. CDM and the composite overall score remain unavailable.

## Frozen identity

| Item | Frozen value |
| --- | --- |
| Candidate | `mineru-3.4.4-vlm-c1` |
| MinerU source revision | `79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7` |
| Model artifact manifest | `sha256:1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84` |
| Inference bundle | `sha256:77f04e0e1d86f2a89706923fe84633f0359e64f9c3667b2ec29dd582c506a4b0` |
| Inference run summary | `sha256:ee5046059fae45bf40b2b42910a72e2718cfaebd7eb3ee3c887607a16ccfddf5` |
| Official evaluator | OmniDocBench `193627ae9e97d89188468ed1ee3b7a856ff76044` |
| Evaluator metric result | `sha256:6aa5e65a73b77784d66d973d492fd44654eb726cdf45153ad39112e0e793f479` |
| Corpus | OmniDocBench official demo, 18 images |
| Ground-truth SHA-256 | `146690eae39d35ae95eff9d92889876eb45137285cb73cd5af451329411c9207` |
| Inference ground truth mounted | No |
| GPU | NVIDIA GeForce RTX 4090, 24,564 MiB |
| Provider rate observed | USD 0.69 per GPU-hour |
| Concurrency recovery | `MINERU_API_MAX_CONCURRENT_REQUESTS=1` |

## Accuracy results

All three repeats produced the same official metric-result hash and scores.

| Official metric | Result | Direction | Readable companion |
| --- | ---: | --- | ---: |
| Text Edit distance, `ALL_page_avg` | 0.034258 | lower is better | 96.574% `1 - edit` |
| Formula Edit distance, `ALL_page_avg` | 0.122975 | lower is better | 87.703% `1 - edit` |
| Table TEDS, sample average | 0.959696 | higher is better | 95.970% |
| Table TEDS structure-only, sample average | 0.984524 | higher is better | 98.452% |
| Table Edit distance, `ALL_page_avg` | 0.022737 | lower is better | 97.726% `1 - edit` |
| Reading-order Edit distance, `ALL_page_avg` | 0.076693 | lower is better | 92.331% `1 - edit` |
| CDM | unavailable | — | not executed in validated toolchain |
| Overall | unavailable | — | CDM and full benchmark required |

The readable `1 - edit` values are derived presentation aids. They are not
renamed official leaderboard metrics.

## Runtime, stability, and cost

| Repeat | Completed | Failed | Wall time | Seconds/page |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 18 | 0 | 626.566 s | 34.809 |
| 2 | 18 | 0 | 625.121 s | 34.729 |
| 3 | 18 | 0 | 622.533 s | 34.585 |

- Mean: 624.740 seconds per 18 pages; 34.7078 seconds/page.
- Population standard deviation: 0.0927 seconds/page.
- Throughput at this execution shape: approximately 103.7 pages/GPU-hour.
- Estimated provider runtime cost: USD 0.0066523/page at USD 0.69/hour.
- Determinism: 18/18 page-level Markdown hashes matched across all repeats.
- Cost excludes storage, transfer, orchestration, and evaluator compute.

## Failure and recovery evidence

The original concurrency-three diagnostic completed only 6 of 54 cases. The
remaining 48 failed with an internal tensor-shape mismatch. That failure is
retained in `MINERU_3_4_4_VLM_RUNTIME_DIAGNOSTIC_2026-08-01.md`; it was not
deleted or counted as a successful formal run. Concurrency one then passed an
18-page Stage 1 gate before this 54-case formal run was admitted.

## Routing consequence

MinerU VLM c1 is the measured quality-escalation lane for pages where static
preflight, sampling, or validation predicts difficult tables, reading order, or
mixed layouts. PaddleOCR-VL remains the measured fast lane; MinerU pipeline is a
deterministic middle lane. Structara should route by calibrated risk and verify
outputs independently instead of declaring one universal winner.

## Reproduction artifacts

- Machine-readable evidence:
  `benchmark/reports/mineru-3.4.4-vlm-c1-omnidocbench-demo-18-evidence-2026-08-01.json`
- Inference runner: `benchmark/runpod_eval/mineru_stage2.py`
- Official evaluator runner: `benchmark/runpod_eval/evaluate_omnidoc_repeats.py`
- Raw artifacts: git-ignored
  `artifacts/e2e-model-evaluation/mineru-3.4.4-vlm-c1-omnidoc-demo-18x3-clean/`

## Primary sources

- OmniDocBench: <https://github.com/opendatalab/OmniDocBench>
- MinerU: <https://github.com/opendatalab/MinerU>
