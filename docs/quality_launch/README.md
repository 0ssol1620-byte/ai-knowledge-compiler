# P1 mixed-document quality qualification

This track answers a narrow launch question: whether one candidate output meets
all frozen quality gates on a pinned mixed-document suite. It does not infer
production readiness from service health, model identity, or a generated file.

## Evidence boundary

The v1 suite uses four existing repository fixtures: Korean HTML, SRT and VTT,
plus the six-page English synthetic report. Their bytes are SHA-256 pinned before
any score is calculated. The reference candidate proves the evaluator and its
failure modes; it is not evidence that a production parser achieved these scores.
No provider, LLM, network endpoint, Foundation repository, or RunPod worker is
called. Reports therefore state `runpod_execution: not_observed` and
`production_runtime_claim: false`.

## Gates

| Dimension | Metrics | Launch rule |
| --- | --- | --- |
| OCR text | character and word accuracy | both pass |
| OCR layout | block type F1, reading order, bbox IoU | all pass |
| Citations | exact page and region IoU | all pass |
| Entity resolution | pairwise precision and recall | false merges weighted by precision gate |
| Claims | entailment/contradiction/unknown accuracy and macro F1 | all labels retained |
| Temporal authority | bitemporal field and as-of accuracy | unknown dates must remain unknown |
| Ontology/graph | node/edge F1 and structural validity | no dangling, self, unknown or ungrounded edge |
| Adaptive chunking | source/citation coverage, token cap, protected boundaries | all pass |
| Retrieval | MRR, recall@k and nDCG@k | all pass |
| Downstream AI | compiled exact score, gain over raw, per-task non-regression | all pass |

There is no compensating aggregate. One failed dimension yields
`not_qualified`. Missing dimensions and fixture drift stop evaluation rather than
being converted to zero or silently skipped.

## Run

```powershell
python -m tools.quality_launch `
  --suite tests/quality_launch/golden_suite.json `
  --candidate tests/quality_launch/reference_candidate.json `
  --output artifacts/quality_launch/reference-acceptance-report.json

python -m pytest tests/quality_launch -q
```

To qualify a real pipeline, export its output into the candidate contract,
retain provider/model/runtime receipts separately, and rerun this command. A
representative, licensed, reviewer-annotated customer-like holdout must be added
before using the report for an external accuracy or AI-performance claim.
