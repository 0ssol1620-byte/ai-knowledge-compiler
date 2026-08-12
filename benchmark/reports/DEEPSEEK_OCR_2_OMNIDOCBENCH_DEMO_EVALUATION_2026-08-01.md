# DeepSeek-OCR-2 — OmniDocBench Demo Evaluation

Evaluation completed: 2026-08-02 KST
Claim class: internal reproducibility evidence
Promotion: eligible for the partial-metric model portfolio

## Outcome

DeepSeek-OCR-2 completed 54 of 54 blind inference cases with no failure or
timeout: 18 images from the official Apache-2.0 OmniDocBench demo, repeated
three times. All 18 page-level Markdown artifacts were byte-identical across
the three repeats. On this cohort it produced the lowest text edit distance in
the formal portfolio at the time of evaluation, but was slower and more
expensive than every already-promoted lane and did not lead the formula, table,
or reading-order metrics. It is therefore a selective text-fidelity challenger,
not the default route.

## Frozen identity

| Field | Value |
| --- | --- |
| Model | `deepseek-ai/DeepSeek-OCR-2` |
| Model revision | `aaa02f3811945a91062062994c5c4a3f4c0af2b0` |
| Artifact manifest SHA-256 | `ddb70c12791d2583344b73a065c8b4757e5827aa2fe608e763074c33bfab876c` |
| Inference runner | repository `deepseek_ocr2_stage2.py` |
| Runtime | Python 3.12.9, Torch 2.6.0+cu124, Transformers 4.46.3, FlashAttention 2.7.3 |
| Hardware | RunPod Secure Cloud, NVIDIA GeForce RTX 4090, 24,564 MiB |
| Observed provider rate | USD 0.69 per GPU-hour |
| Corpus | OmniDocBench official demo, 18 images |
| Ground truth on worker | No |
| Evaluator | `OmniDocBench@193627ae9e97d89188468ed1ee3b7a856ff76044` |

The frozen artifact was downloaded and hashed before inference. The raw
three-repeat archive matched remotely and locally at SHA-256
`9db373c0388ddc3f93088e5ca7bea52393201cc073ab8c875c1b89eeb1cade1f`.

## Official partial metrics

| Metric | Mean across three repeats | Direction |
| --- | ---: | --- |
| Text edit distance, page average | 0.032428 | lower is better |
| Formula edit distance, page average | 0.139538 | lower is better |
| Table TEDS, sample average | 0.871838 | higher is better |
| Table TEDS, structure-only | 0.912497 | higher is better |
| Table edit distance, page average | 0.107487 | lower is better |
| Reading-order edit distance, page average | 0.100267 | lower is better |

The official metric result was identical in every repeat and has SHA-256
`fe6cfab67e12f24175d4d74fe60d19ad08049e91fc4a3f8d965f96f2cc697bf8`.
CDM was unavailable in the evaluator environment and was excluded. No overall
score is reported, and an unavailable value is never converted to zero.

## Runtime and estimated cost

| Repeat | 18-page latency | Estimated USD/page |
| ---: | ---: | ---: |
| 1 | 851.260 s | 0.009064 |
| 2 | 848.838 s | 0.009039 |
| 3 | 848.710 s | 0.009037 |
| Mean | 849.603 s | 0.009047 |

Mean runtime was 47.200 seconds per page. The estimate applies the observed
USD 0.69 GPU-hour rate to measured inference runtime only; orchestration,
storage, transfer, evaluation, taxes, and invoice reconciliation are outside
scope.

## Reproducibility and failure policy

- Completed inference: 54/54.
- Hard failures and timeouts: 0.
- Exact repeat stability: 18/18 pages.
- Ground-truth isolation: enforced; labels were available only to the separate
  local evaluator.
- Run-summary SHA-256:
  `23be642af7c7e06c67b5b12e6412dae62624b73d979ea2427a9a1c4ef64388e6`.
- Evidence-summary SHA-256:
  `ff7ef2a6058e702c1f2122405fcb5525649e345eb18c0f4fac3d58a220848c2e`.

## Routing interpretation

DeepSeek-OCR-2 is eligible when a page is text-heavy, its text-fidelity lower
bound justifies the added spend, and the latency budget admits a long-tail
transformer pass. It must not replace PaddleOCR-VL as the measured fast lane or
MinerU VLM c1 as the measured table and reading-order escalation lane on the
basis of this small demo cohort. The risk-constrained router should use the
per-metric posterior and abstain when the page family lacks calibrated evidence.

## Limitations

This is a reproducibility study on the 18-image official demo subset, not a full
OmniDocBench leaderboard submission and not production field evidence. The
cohort is too small for universal model claims. CDM and overall remain
unavailable. Provider cost is a runtime estimate rather than an invoice.

## Sources

- DeepSeek-OCR-2 model card: <https://huggingface.co/deepseek-ai/DeepSeek-OCR-2>
- OmniDocBench evaluator: <https://github.com/opendatalab/OmniDocBench>
