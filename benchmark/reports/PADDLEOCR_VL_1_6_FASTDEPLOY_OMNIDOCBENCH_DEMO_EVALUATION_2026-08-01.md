# PaddleOCR-VL 1.6 FastDeploy — OmniDocBench Demo Evaluation

Date: 2026-08-01 KST
Claim class: internal reproducibility evidence
Promotion: partial metrics eligible; overall score unavailable

## Executive result

PaddleOCR-VL 1.6 completed all 54 blind inference cases through the official
FastDeploy service path: 18 Apache-2.0 OmniDocBench demo pages repeated three
times, with no failed case and no timeout. Mean wall time was 3.5249 seconds per
page at client concurrency eight on a single RTX 4090. Ten of 18 page Markdown
artifacts were byte-identical across all three repeats; the official aggregate
metrics varied only in text and reading-order edit distance.

This is a small heterogeneous reproducibility cohort, not a full OmniDocBench
leaderboard submission. CDM was not executed in the validated evaluator lane,
so no CDM or composite overall score is reported.

## Frozen identity

| Item | Frozen value |
| --- | --- |
| Candidate | `paddleocr-vl-1.6-fastdeploy-c8` |
| Model artifact manifest | `sha256:83482fee6ec1a6bd7b822f32dcc3cb9a412419786b2ae6cc87320290132334a2` |
| Inference bundle | `sha256:337570a4b572e869ef7e91b36df14a99593180fcf50af57d93ce4ae5feeb7316` |
| Inference run summary | `sha256:40d5079ddc999ba4abf40707da255082ed87f7462244bf3f7496de90d4fd9c92` |
| Official evaluator | OmniDocBench `193627ae9e97d89188468ed1ee3b7a856ff76044` |
| Corpus | OmniDocBench official demo, 18 images |
| Ground-truth SHA-256 | `146690eae39d35ae95eff9d92889876eb45137285cb73cd5af451329411c9207` |
| Inference ground truth mounted | No |
| GPU | NVIDIA GeForce RTX 4090, 24,564 MiB |
| Provider rate observed | USD 0.69 per GPU-hour |
| Service | FastDeploy 2.3.0, four workers, client concurrency 8 |

The inference worker contained only source images. Reference annotations were
introduced only in the separate local evaluator after inference outputs were
hashed and transferred.

## Accuracy results

| Official metric | Three-repeat mean | Population stddev | Direction |
| --- | ---: | ---: | --- |
| Text Edit distance, `ALL_page_avg` | 0.038209 | 0.000199 | lower is better |
| Formula Edit distance, `ALL_page_avg` | 0.113618 | 0.000000 | lower is better |
| Table TEDS, sample average | 0.906065 | 0.000000 | higher is better |
| Table TEDS structure-only, sample average | 0.938370 | 0.000000 | higher is better |
| Table Edit distance, `ALL_page_avg` | 0.051888 | 0.000000 | lower is better |
| Reading-order Edit distance, `ALL_page_avg` | 0.091270 | 0.002381 | lower is better |
| CDM | unavailable | — | not executed in validated toolchain |
| Overall | unavailable | — | CDM and full benchmark required |

Derived presentation companions are 96.179% text `1 - edit`, 88.638% formula
`1 - edit`, 90.606% Table TEDS, 93.837% structure-only TEDS, 94.811% table
`1 - edit`, and 90.873% reading-order `1 - edit`. The `1 - edit` values are not
renamed official leaderboard metrics.

## Runtime, stability, and cost

| Repeat | Completed | Failed | Wall time | Seconds/page |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 18 | 0 | 65.297 s | 3.628 |
| 2 | 18 | 0 | 62.667 s | 3.481 |
| 3 | 18 | 0 | 62.381 s | 3.466 |

- Mean: 63.448 seconds per 18 pages; 3.5249 seconds/page.
- Population standard deviation: 0.0729 seconds/page.
- Throughput at this batch shape: approximately 1,021.3 pages/GPU-hour.
- Estimated provider runtime cost: USD 0.0006756/page at USD 0.69/hour.
- Cost excludes storage, transfer, orchestration, initialization, and evaluator
  compute; it is not invoice reconciliation.
- Exact Markdown repeat stability: 10/18 pages (55.6%). Metric-level results
  were substantially more stable than byte-level generation.

## Failures that remain evidence

1. The default Paddle dynamic backend passed a GPU matrix-multiplication
   control but timed out in VLM inference. It is retained as a failed runtime
   diagnostic and is not mixed into formal timing.
2. FastDeploy 2.3.0 and PaddleFormers 1.2.0 had one upstream import-path
   mismatch. The exact one-line compatibility patch and before/after hashes are
   frozen in the runtime manifest.
3. RunPod's base nginx already owned port 8001; the metrics listener was moved
   to 18119, while the inference API remained loopback-only on 8118.
4. A single-concurrency FastDeploy run was stopped after proving that service
   scheduling, not model correctness, was the bottleneck. It is diagnostic only.
5. CDM's rendering chain was not validated. An unavailable metric is never
   converted into a zero score.

## Interpretation and routing consequence

On this cohort PaddleOCR-VL 1.6 is the faster and cheaper candidate and leads
MinerU pipeline on formula edit distance, Table TEDS, table edit distance, and
reading-order edit distance. MinerU retains the lower text edit distance, the
higher structure-only TEDS, and perfect byte-level repeat stability. Structara
therefore routes by page risk and output contract: Paddle is a strong fast lane
for table-content and formula-heavy pages, while deterministic or text-critical
pages can prefer MinerU and independent validators. Neither model receives sole
authority over numeric or provenance-sensitive facts.

## Reproduction artifacts

- Evidence JSON: `benchmark/reports/paddleocr-vl-1.6-fastdeploy-omnidocbench-demo-18-evidence-2026-08-01.json`
- Runtime manifest: `benchmark/reports/paddleocr-vl-1.6-fastdeploy-runtime-manifest-2026-08-01.json`
- Inference runner: `benchmark/runpod_eval/paddleocr_vl_stage2.py`
- Official evaluator runner: `benchmark/runpod_eval/evaluate_omnidoc_repeats.py`
- Raw artifacts: `artifacts/e2e-model-evaluation/paddleocr-vl-1.6-fastdeploy-omnidoc-demo-18x3-clean/` (git-ignored)

## Primary sources

- PaddleOCR-VL 1.6 model card: <https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6>
- PaddleOCR-VL pipeline documentation: <https://paddlepaddle.github.io/PaddleX/3.7/en/pipeline_usage/tutorials/ocr_pipelines/PaddleOCR-VL.html>
- OmniDocBench evaluator: <https://github.com/opendatalab/OmniDocBench>
