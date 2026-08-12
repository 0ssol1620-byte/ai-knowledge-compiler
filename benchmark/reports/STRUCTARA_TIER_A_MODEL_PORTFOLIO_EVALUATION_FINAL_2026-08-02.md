# Structara Tier A Parser/OCR Portfolio — Final Reproducibility Report

Completed: 2026-08-02 KST
Evidence class: internal reproducibility evidence
Publication boundary: official partial metrics on the OmniDocBench demo subset;
not a full leaderboard result

## Executive decision

Five candidates completed the same ground-truth-isolated 18-page corpus three
times on the same RTX 4090 class, for 270 successful formal inference cases and
zero hard failure. There is no universal winner.

- **Fast lane — PaddleOCR-VL 1.6 FastDeploy c8.** Fastest and cheapest; best
  formula edit distance among the five. It also beats OvisOCR2 on every formal
  accuracy metric in this cohort.
- **Quality escalation — MinerU 3.4.4 VLM c1.** Best Table TEDS, structure-only
  TEDS, table edit distance, and reading order; 100% byte-exact repeats. Use
  selectively because it costs 9.85 times Paddle's runtime per page.
- **Text-fidelity challenger — DeepSeek-OCR-2.** Best text edit distance and
  100% byte-exact repeats, but the slowest and most expensive candidate. Admit
  only when calibrated text-risk reduction justifies the latency.
- **Deterministic structural fallback — MinerU 3.4.4 pipeline.** 100% exact
  repeats with a medium runtime. It remains useful where deterministic replay
  and its stronger structure score relative to Paddle matter.
- **Measured shadow lane — OvisOCR2 0.9B cu129.** Formal and reproducible enough
  to measure, but currently quality-and-cost dominated by Paddle apart from
  stronger exact-repeat stability. Do not route default traffic to it.

The router must select by page family, evidence lower bound, budget, and hard
validator outcome. It must abstain when evidence is not calibrated for that
family. No candidate receives sole authority over numeric, table, provenance,
or continuity decisions.

## Common protocol

| Contract | Frozen value |
| --- | --- |
| Corpus | OmniDocBench official demo, 18 images, Apache-2.0 |
| Formal repetitions | 3 per candidate |
| Formal inference cases | 270 total |
| Hard failures/timeouts | 0 |
| Ground truth on inference worker | forbidden and absent |
| Evaluator | `OmniDocBench@193627ae9e97d89188468ed1ee3b7a856ff76044` |
| GPU | RunPod Secure Cloud, NVIDIA GeForce RTX 4090, 24,564 MiB |
| Observed GPU rate | USD 0.69/hour |
| Ground-truth SHA-256 | `146690eae39d35ae95eff9d92889876eb45137285cb73cd5af451329411c9207` |
| Public evidence bundle | `daf40605df692107fec0db2e08afb05e7a940e1ca21db91d8eb3761a79f90af5` |

Each candidate was frozen by source/model revision and artifact hash. Inference
ran without labels. The official evaluator ran later in a separate local
environment. Failed diagnostics were retained but never assigned a quality
score. CDM and overall were unavailable for every candidate and are not zero.

## Accuracy matrix

Lower is better for edit distance; higher is better for TEDS.

| Candidate | Text edit ↓ | Formula edit ↓ | Table TEDS ↑ | Structure TEDS ↑ | Table edit ↓ | Reading order edit ↓ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MinerU pipeline | 0.036507 | 0.153424 | 0.890803 | 0.946825 | 0.434287 | 0.095701 |
| PaddleOCR-VL | 0.038209 | **0.113618** | 0.906065 | 0.938370 | 0.051888 | 0.091270 |
| MinerU VLM c1 | 0.034258 | 0.122975 | **0.959696** | **0.984524** | **0.022737** | **0.076693** |
| DeepSeek-OCR-2 | **0.032428** | 0.139538 | 0.871838 | 0.912497 | 0.107487 | 0.100267 |
| OvisOCR2 0.9B | 0.097963 | 0.138752 | 0.894063 | 0.938370 | 0.059688 | 0.142573 |

The metric repeat standard deviation is zero for all aggregate cells. This does
not imply every raw artifact is identical: Ovis had two byte-level variants
that did not change its aggregate official result.

## Runtime, cost, and stability

| Candidate | Mean sec/page | Estimated USD/page | Exact page repeats | Relative runtime vs Paddle |
| --- | ---: | ---: | ---: | ---: |
| PaddleOCR-VL | **3.525** | **0.000676** | 10/18 | 1.00× |
| OvisOCR2 0.9B | 6.171 | 0.001183 | 16/18 | 1.75× |
| MinerU pipeline | 6.959 | 0.001334 | **18/18** | 1.97× |
| MinerU VLM c1 | 34.708 | 0.006652 | **18/18** | 9.85× |
| DeepSeek-OCR-2 | 47.200 | 0.009047 | **18/18** | 13.39× |

Cost applies the observed GPU-hour rate to measured inference runtime only.
It excludes model download, engine initialization, orchestration, storage,
transfer, evaluation, taxes, and invoice reconciliation.

## Candidate identities and evidence

| Candidate | Frozen identity | Evidence SHA-256 |
| --- | --- | --- |
| MinerU pipeline | MinerU 3.4.4 source `79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7` | `039ad9a40be6e04fe69127e8a183abd29c3a0059cf40f6ec5b2d92a4a17e98f1` |
| PaddleOCR-VL | FastDeploy artifact `83482fee6ec1a6bd7b822f32dcc3cb9a412419786b2ae6cc87320290132334a2` | `b309e6c59ce7c583b550c7645faa345cc2eeb4614df9b822199bfbc4d4f9a6eb` |
| MinerU VLM c1 | MinerU 3.4.4 source `79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7` | `ac3ea843e96d333d8bddcb6cee4089e72ce6a69c0a80aa6ee7b753f83f2b5365` |
| DeepSeek-OCR-2 | revision `aaa02f3811945a91062062994c5c4a3f4c0af2b0` | `ff7ef2a6058e702c1f2122405fcb5525649e345eb18c0f4fac3d58a220848c2e` |
| OvisOCR2 0.9B | revision `65c619d374b55d4152e85150fc1b003700bc1f0c`, vLLM 0.22.1+cu129 | `3ce8e385c087591de8ea5af270109356b7e551f48a7ae3d8b008c42b8b8d5c83` |

## Risk-constrained routing policy

1. Static preflight and page-family evidence define eligible candidates; a
   model outside its calibrated family is not silently extrapolated.
2. Ordinary throughput-sensitive pages prefer PaddleOCR-VL when its quality
   lower bound satisfies the page contract.
3. Table-dense, mixed-layout, and reading-order-risk pages may escalate to
   MinerU VLM c1, followed by numeric, table, source, and continuity validators.
4. Text-heavy pages may compare DeepSeek-OCR-2 against the incumbent only when
   expected error reduction exceeds its incremental latency and credit cost.
5. MinerU pipeline remains the deterministic fallback when byte-stable replay
   and structural fidelity outweigh Paddle's speed.
6. OvisOCR2 stays shadow-only until a page-family study demonstrates an
   advantage not present in this cohort.
7. Any hard validator failure triggers bounded repair or abstention, never an
   unverified “best effort” publication.

The repository implements Beta-Binomial sequential evidence, calibrated
lower-bound selection, Monte Carlo schedule estimates, ValidationEvidence 0–10,
semantic EWMA/CUSUM health, and immutable recovery scopes to enforce this
policy. Learned routing remains shadow-only until held-out calibration exists.

## Diagnostic history retained

- MinerU VLM concurrency three: 6/54 completed and 48/54 tensor-shape failures;
  recovered as the separate c1 lane.
- Paddle default runtime: GPU matrix/import incompatibilities; recovered under
  the frozen FastDeploy runtime.
- Ovis PyPI vLLM path: fork reinitialization and CUDA 13 host-runtime failures;
  recovered under the separate official cu129 identity.
- Ovis cu129 admission: two additional pre-inference attempts found the spawned
  worker's missing `ninja` PATH; fixed before Stage 1. No failed attempt entered
  the scored table.

## Limits and next evidence

The official demo is deliberately small and cannot support a universal model
claim, production SLO, or public leaderboard position. Next promotion evidence
requires a rights-cleared full or domain-stratified corpus, held-out calibration,
field latency distributions including orchestration, invoice reconciliation,
and deployed fault/security exercises. The current portfolio remains usable as
a reproducible internal routing prior, not final field truth.

## Primary sources

- MinerU: <https://github.com/opendatalab/MinerU>
- PaddleOCR-VL 1.6: <https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6>
- DeepSeek-OCR-2: <https://huggingface.co/deepseek-ai/DeepSeek-OCR-2>
- OvisOCR2: <https://huggingface.co/ATH-MaaS/OvisOCR2>
- OmniDocBench: <https://github.com/opendatalab/OmniDocBench>
- vLLM GPU installation: <https://docs.vllm.ai/en/latest/getting_started/installation/gpu/>
