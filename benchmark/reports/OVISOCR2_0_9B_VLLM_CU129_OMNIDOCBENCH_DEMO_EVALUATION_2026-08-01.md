# OvisOCR2 0.9B · vLLM CUDA 12.9 — OmniDocBench Demo Evaluation

Evaluation completed: 2026-08-02 KST
Claim class: internal reproducibility evidence
Promotion: eligible for the partial-metric model portfolio

## Outcome

The recovered OvisOCR2 runtime completed 54 of 54 blind inference cases with no
failure or timeout: 18 Apache-2.0 OmniDocBench demo images repeated three times.
Sixteen of 18 page artifacts were byte-identical across all repeats. Two pages
differed between the first, JIT-warming repeat and repeats two and three, so the
exact-repeat ratio is reported as 88.89% rather than rounded up to deterministic.

On this cohort OvisOCR2 was faster than both MinerU lanes and DeepSeek-OCR-2,
but slower and more expensive than PaddleOCR-VL. It did not lead any official
partial accuracy metric. It is a formally measured challenger lane, not the
default production route.

## Frozen identity

| Field | Value |
| --- | --- |
| Model | `ATH-MaaS/OvisOCR2` |
| Model revision | `65c619d374b55d4152e85150fc1b003700bc1f0c` |
| Artifact manifest SHA-256 | `847f485bc71908a70075fe6b0d76609f52bc7f1e730c03670c764da56da08c9a` |
| Runtime | Python 3.11.10, `vLLM 0.22.1+cu129`, Torch 2.11.0+cu129 |
| Worker mode | spawn |
| GDN prefill | Triton |
| Hardware | RunPod Secure Cloud, NVIDIA GeForce RTX 4090, 24,564 MiB |
| Observed provider rate | USD 0.69 per GPU-hour |
| Corpus | OmniDocBench official demo, 18 images |
| Ground truth on worker | No |
| Evaluator | `OmniDocBench@193627ae9e97d89188468ed1ee3b7a856ff76044` |
| Prompt SHA-256 | `c0fb65bf41705f32189c0e2407d824db52a68a365024239b2029a7a283f64567` |

The raw three-repeat archive matched remotely and locally at SHA-256
`3d82abe7b97801add70ecd5e74173a749dfe307310a2962c9bac177fb3e08701`.

## Official partial metrics

| Metric | Mean across three repeats | Direction |
| --- | ---: | --- |
| Text edit distance, page average | 0.097963 | lower is better |
| Formula edit distance, page average | 0.138752 | lower is better |
| Table TEDS, sample average | 0.894063 | higher is better |
| Table TEDS, structure-only | 0.938370 | higher is better |
| Table edit distance, page average | 0.059688 | lower is better |
| Reading-order edit distance, page average | 0.142573 | lower is better |

Despite two page-level byte differences, all three official aggregate metric
results were identical and share SHA-256
`8998ded17b7145cf1b0440f494878b8e08f98396d9c71bc0bcbfd7df73066755`.
CDM and overall were unavailable and are not reported as zero.

## Runtime and estimated cost

| Repeat | 18-page latency | Seconds/page | Estimated USD/page |
| ---: | ---: | ---: | ---: |
| 1 | 122.558 s | 6.809 | 0.001305 |
| 2 | 105.306 s | 5.850 | 0.001121 |
| 3 | 105.385 s | 5.855 | 0.001122 |
| Mean | 111.083 s | 6.171 | 0.001183 |

Repeat one retains inference-time JIT warmup costs. Model loading and engine
initialization are recorded separately by the runner and are not hidden inside
one chosen repeat. Cost is a runtime estimate, not invoice reconciliation.

## Stability evidence

- Exact across all repeats: 16/18 pages.
- First-repeat-only variants:
  `jiaocaineedrop_Evans_PDE_Solution_Chapter_6_Second-Order_Elliptic_Equations.pdf_5`
  and `jiaocaineedrop_jiaocai_needrop_en_3361`.
- Repeats two and three were byte-identical for both variant pages.
- Completed inference: 54/54; failures and timeouts: 0.
- Run-summary SHA-256:
  `2ae67f243591bff9bce35cbb9377bb27eb0565cc47b34c69599cd3c513459eb1`.
- Evidence-summary SHA-256:
  `3ce8e385c087591de8ea5af270109356b7e551f48a7ae3d8b008c42b8b8d5c83`.

## Recovery chronology

The original PyPI runtime failed before inference because its compiled vLLM
extension required CUDA 13 while the host exposed CUDA 12.x compatibility. A
Torch cu128-only retry still inherited that CUDA 13 vLLM binary. The candidate
was recovered with the official vLLM 0.22.1 CUDA 12.9 release wheel and Torch
2.11.0+cu129. Two further pre-inference attempts exposed and then fixed the
spawned worker's missing `ninja` PATH. Every failed attempt remains diagnostic
evidence and contributes no quality score.

The recovered identity is deliberately distinct from the failed PyPI identity.
It passed a fresh 18/18 Stage 1 before the 18×3 formal run.

## Routing interpretation

OvisOCR2 may remain in shadow traffic for page families where its lower model
size or future throughput tuning could matter. Current evidence does not justify
routing away from PaddleOCR-VL on the fast lane: Paddle is both faster and more
accurate on text, formula, table, and reading order in this cohort. Pages chosen
for Ovis must retain downstream validators and a calibrated abstention path.

## Limitations

This is an 18-image reproducibility cohort rather than a full leaderboard
submission or field SLO. The small sample cannot establish universal quality.
CDM and overall are unavailable. Runtime cost excludes orchestration, storage,
transfer, evaluation, taxes, and invoice reconciliation.

## Sources

- OvisOCR2 model card: <https://huggingface.co/ATH-MaaS/OvisOCR2>
- vLLM GPU installation: <https://docs.vllm.ai/en/latest/getting_started/installation/gpu/>
- OmniDocBench evaluator: <https://github.com/opendatalab/OmniDocBench>
