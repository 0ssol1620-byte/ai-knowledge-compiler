# MinerU 3.4.4 Pipeline, PaddleOCR-VL 1.6, and MinerU VLM c1

> Portfolio update: DeepSeek-OCR-2 and OvisOCR2 later passed the same formal
> gates. The five-candidate decision record is
> `STRUCTARA_TIER_A_MODEL_PORTFOLIO_EVALUATION_FINAL_2026-08-02.md`. This report
> remains the frozen three-candidate comparison from its evaluation stage.

Date: 2026-08-01 KST
Scope: 18 official OmniDocBench demo images × 3 repeats per candidate
Claim class: internal reproducibility evidence; not a full leaderboard claim

## Decision summary

The formal results support a three-lane portfolio rather than a universal
winner. PaddleOCR-VL was the fastest and least expensive. MinerU VLM c1 led all
valid partial accuracy metrics except formula edit distance, but required about
9.85× Paddle's runtime per page. MinerU pipeline occupied the deterministic
middle lane. The correct product behavior is calibrated routing plus independent
verification.

## Repeated official metrics

| Metric | MinerU pipeline | PaddleOCR-VL 1.6 | MinerU VLM c1 | Best on this cohort |
| --- | ---: | ---: | ---: | --- |
| Text Edit distance ↓ | 0.036507 | 0.038209 | **0.034258** | MinerU VLM |
| Formula Edit distance ↓ | 0.153424 | **0.113618** | 0.122975 | PaddleOCR-VL |
| Table TEDS ↑ | 0.890803 | 0.906065 | **0.959696** | MinerU VLM |
| Table TEDS structure-only ↑ | 0.946825 | 0.938370 | **0.984524** | MinerU VLM |
| Table Edit distance ↓ | 0.434287 | 0.051888 | **0.022737** | MinerU VLM |
| Reading-order Edit distance ↓ | 0.095701 | 0.091270 | **0.076693** | MinerU VLM |
| CDM / Overall | unavailable | unavailable | unavailable | no claim |

All values are identical across three official evaluator repeats. Ground truth
was absent from every inference worker and introduced only in the local hashed
evaluator lane.

## Runtime and operational evidence

| Evidence | MinerU pipeline | PaddleOCR-VL FastDeploy c8 | MinerU VLM c1 |
| --- | ---: | ---: | ---: |
| Completed / attempted | 54 / 54 | 54 / 54 | 54 / 54 |
| Mean seconds/page | 6.9589 | **3.5249** | 34.7078 |
| Approx. pages/GPU-hour | 517.3 | **1,021.3** | 103.7 |
| Estimated runtime USD/page | 0.0013338 | **0.0006756** | 0.0066523 |
| Exact Markdown across 3 repeats | **18/18** | 10/18 | **18/18** |

The execution shapes reflect the production candidates: MinerU pipeline used
its directory CLI, Paddle used a four-worker FastDeploy service with client
concurrency eight, and MinerU VLM used one request at a time after concurrency
three exposed a reproducible tensor-shape failure.

## Routing policy derived from evidence

- Route ordinary throughput-sensitive pages to PaddleOCR-VL when its sampled
  risk forecast is inside the calibrated quality bound.
- Route deterministic text or structure work to MinerU pipeline when replay
  stability is worth its moderate runtime premium.
- Escalate difficult tables, reading-order layouts, or validation disagreement
  to MinerU VLM c1; do not pay its cost on every page.
- Keep formula-sensitive pages eligible for PaddleOCR-VL and verify formulas
  independently because formula CDM is unavailable here.
- Run numeric, source-anchor, schema, continuity, and evidence-sufficiency gates
  regardless of parser choice.
- Keep this 18-page demo cohort separate from future full-corpus benchmark or
  field-SLO claims.

Machine-readable evidence and the evidence-bundle manifest are stored in
`benchmark/reports/`. Raw predictions and evaluator output remain in the
git-ignored `artifacts/e2e-model-evaluation/` tree.
