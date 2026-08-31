# Semantic Risk Development Calibration — SEM-RISK-DEV-CAL-01

**Classification:** retrospective development calibration only. This is not a production threshold study or fresh confirmatory evidence.

## What was reused

The study reuses the already-spent 18-page × 3-repeat OmniDocBench demo evidence for PaddleOCR-VL 1.6 FastDeploy and MinerU 3.4.4 VLM, plus the exact local OmniDocBench demo ground truth. No OCR/VLM inference, network access, or GPU spend was performed.

## Important metric separation

`official_aggregate_snapshot` in the machine receipt is read directly from the preserved official OmniDocBench evaluator outputs. The page-level `damage` used below is a TAVONEL custom development metric and MUST NOT be described as an official OmniDocBench score.

## Development result

Always-primary mean custom damage: **0.2009** at $0.01216 simulated parser cost for the 18 pages.
Always-strong mean custom damage: **0.2151** at $0.11974.
Current Semantic Risk at threshold 0.55 escalated **0/18** pages and produced mean damage **0.2009**.
The current risk score range was only **0.000000–0.009998**. Because the predeclared grid starts at 0.25, every current-engine threshold route collapsed to always-primary on this cohort.
Yet the page oracle shows non-trivial selective opportunity: MinerU had lower custom damage on **8** pages, higher damage on **9**, and tied on **1**. Oracle mean damage is **0.1690**, versus **0.2009** for always-primary.

### Predeclared policy grid

| Policy | Escalation | Mean damage | Damage Δ vs primary | Cost USD | Regret vs oracle |
|---|---:|---:|---:|---:|---:|
| always_primary | 0.0% | 0.2009 | +0.0000 | 0.01216 | 0.0319 |
| always_strong | 100.0% | 0.2151 | -0.0142 | 0.11974 | 0.0461 |
| semantic_risk>=0.25 | 0.0% | 0.2009 | +0.0000 | 0.01216 | 0.0319 |
| semantic_risk>=0.5 | 0.0% | 0.2009 | +0.0000 | 0.01216 | 0.0319 |
| semantic_risk>=0.55 | 0.0% | 0.2009 | +0.0000 | 0.01216 | 0.0319 |
| semantic_risk>=0.75 | 0.0% | 0.2009 | +0.0000 | 0.01216 | 0.0319 |
| strong_disagreement_proxy>=0.1 | 77.8% | 0.2237 | -0.0228 | 0.13190 | 0.0547 |
| strong_disagreement_proxy>=0.2 | 72.2% | 0.2175 | -0.0167 | 0.13190 | 0.0486 |
| strong_disagreement_proxy>=0.3 | 38.9% | 0.2016 | -0.0007 | 0.13190 | 0.0326 |
| strong_disagreement_proxy>=0.4 | 16.7% | 0.2004 | +0.0005 | 0.13190 | 0.0314 |

## Interpretation

The current engine was intentionally evaluated *as sealed*, with unavailable production dimensions set to zero rather than inferred from ground truth. In this historical cohort we do not have the cheap source-native peer disagreement, downstream dependency blast radius, authority/temporal role, or consumer-risk annotations that the full TAVONEL design expects. Primary repeat instability is used only as a development proxy for parser uncertainty; producing three repeats is not assumed to be a free production feature.

**Development diagnosis:** the current score is under-sensitive under the *available feature proxies*, not proven globally under-sensitive. The maximum score stayed below 0.01 even though the lower-damage parser varies by page. This is evidence that the next experiment must supply/measure the missing independent error signal and semantic consequence dimensions; it is not a justification to simply lower the production threshold after seeing these 18 pages.

Paddle-vs-MinerU disagreement is reported as a counterfactual signal, but it is not cost-free routing evidence here: observing it already requires the strong parser on all pages. The receipt therefore charges the operational observation cost accordingly and separately reports the counterfactual cost if an equivalent signal later comes from a negligible-cost independent peer.

No production threshold is selected from 18 already-observed pages. The next confirmatory study must freeze a new heterogeneous corpus before parser outputs are opened, include a cheap independent peer or model-native uncertainty signal, label downstream semantic roles and dependency impact, and evaluate date/quantity/table/authority preservation together with cost/latency.

## Candidate region only

Predeclared Semantic Risk thresholds that reduced this custom development damage while remaining cheaper than always-strong: **[]**. This is a calibration region, not a chosen product threshold.
