# TAVONEL Recovery Paper — Internal Research Blueprint

Status: **PRE-FREEZE / INTERNAL / NOT FOR PUBLIC CLAIMS**

Working title:

> **Reliability Is a System Property: Evidence-Guided Escalation and Fail-Closed Recovery for Document AI**

Alternative short name: **TAVONEL-R**.

## 1. Separation from Paper 1

Paper 1 asks whether a versioned knowledge compiler can remain source-faithful under change. Its core chain is stable identity -> SourceFact evidence -> typed change -> dependency impact -> selective recompilation -> provenance/full-build verification.

Paper 2 asks a different question: whether a document intelligence runtime can spend stronger inference only where production-available evidence says the primary output is not trustworthy, while refusing unresolved outputs rather than silently accepting them.

The two papers may share TAVONEL architecture context but must not share a primary empirical claim.

## 2. Development evidence already available

All evidence in `DEVELOPMENT_EVIDENCE_REGISTER.json` is **spent development evidence**. It may motivate model roles, failure taxonomy, trigger design, and power/cost planning. It cannot score the fresh confirmatory claim.

Key historical evidence to preserve rather than rerun blindly:

- 5,132-document public campaign over ParseBench, OmniDocBench and olmOCR-Bench.
- 5,131/5,132 output completion; completion is not accuracy.
- 1,796/1,797 successful recovery when recovery was required; recovery completion is not accuracy.
- olmOCR-Bench 80.6% with recovery versus 53.7% in the single-variable no-recovery counterfactual.
- ParseBench/OmniDocBench metric degradation when recovered content is removed.
- DART/SEC 20-page A40 comparison with measured numeric fidelity, latency and VRAM.
- Known confident-omission failure: six consecutive financial-table rows disappeared from Hyundai p0526.
- Prediction-only blind quality ranking was NOT SUPPORTED against random/length-only controls.
- OvisOCR2 RTX 4090 one-page smoke is diagnostic only.

Historical official-evaluator-guided selective recovery is an **oracle/development procedure** because evaluation truth influenced candidate acceptance. It is not evidence that a production trigger can make the same choices without labels.

## 3. Research questions

### RQ1 — Detection

Can production-available independent evidence identify silent critical document errors better than prediction-only heuristics at a fixed escalation budget?

### RQ2 — Recovery

Conditional on escalation, can alternate/strong inference reduce silent critical error without silently replacing unresolved outputs?

### RQ3 — Economics

Can evidence-guided selective recovery approach the reliability of always-strong inference with materially lower strong-model invocation, GPU seconds, and external cost?

### RQ4 — Disagreement

How informative is independent parser disagreement about hidden evaluation error, and how often do models agree while jointly remaining wrong?

## 4. Primary arms

All arms operate on the same sealed fresh cohort and hidden evaluation labels.

1. `PRIMARY_ONLY`
   - primary path only.
   - no semantic recovery.

2. `ALWAYS_STRONG`
   - strong resolver on every unit.
   - quality/cost ceiling, not the proposed system.

3. `PREDICTION_ONLY`
   - historical blind signals only: emptiness, repetition, table shape, alpha ratio, length z-score, truncated tail.
   - fixed pre-freeze weights/budget.

4. `DISAGREEMENT_ONLY`
   - primary plus independent peer.
   - escalation determined by frozen disagreement normalization only.
   - disagreement means uncertainty, not correctness.

5. `TAVONEL_EVIDENCE_RECOVERY`
   - primary path.
   - production-available independent evidence checks.
   - peer only where the frozen evidence policy says primary verification is insufficient.
   - strong resolver on hard conflict or frozen disagreement/risk trigger.
   - provenance-preserving page/region replacement.
   - unresolved outputs remain `UNRESOLVED` and are not silently accepted.

6. `ORACLE_DIAGNOSTIC`
   - may read evaluation truth.
   - diagnostic upper bound only.
   - never eligible for a primary TAVONEL claim.

## 5. Evidence semantics

Allowed recovery-trigger evidence classes:

- `SOURCE_NATIVE`
- `RASTER_VISUAL`
- `PARSER_A`
- `PARSER_B`
- `STRUCTURAL_CONSTRAINT`
- `CRITICAL_TOKEN_CONSTRAINT`
- `AUTHORITY`

The runtime must never see confirmatory evaluator labels.

For SEC structured anchors, stable anchor IDs are hash-partitioned before inference into:

- trigger-visible production evidence;
- evaluation-only hidden truth.

The sets must be disjoint. Public benchmark annotations/evaluator labels are evaluation-only.

### Decision principle

```text
PRIMARY OUTPUT
  |
  +-- independently VERIFIED ----------------------> ACCEPT PRIMARY
  |
  +-- hard evidence CONFLICT ----------------------> STRONG RESOLVER
  |
  +-- evidence INSUFFICIENT ------------------------> INDEPENDENT PEER
                                                       |
                                                       +-- frozen calibrated low-risk agreement -> ACCEPT PRIMARY
                                                       |
                                                       +-- disagreement / risk ceiling miss ------> STRONG RESOLVER
                                                                                                     |
                                                                                                     +-- independently VERIFIED -> ACCEPT STRONG
                                                                                                     +-- otherwise -------------> UNRESOLVED
```

Agreement alone is not truth. Any consensus acceptance requires a calibration manifest created only from development/calibration data and frozen before cohort opening.

## 6. Fresh corpus plan

### 6.1 Dr.DocBench candidate lane

Current public candidate: Dr.DocBench (2026), difficult/expert document parsing. The published dataset card states the annotations are CC0; underlying source documents retain original publisher rights. Before use, bind the exact dataset revision/file digests and retain the source-rights caveat.

Selection must be by stable document/page identity and a frozen hash rule, not by observed model difficulty. Any hash/family already present in historical TAVONEL evidence is excluded through the spent manifest.

### 6.2 Fresh SEC lane

Use SEC public submissions/XBRL metadata and official filings. SEC `data.sec.gov` APIs require no authentication and provide submissions/XBRL data; bulk archives are preferred for large acquisition. Exact accession/document hashes already used by TAVONEL demos, failure analysis, or earlier experiments are spent and excluded.

The selection rule must be frozen before any model output is observed. Form/period stratification is allowed only when declared before inference.

### 6.3 OpenDART secondary lane

OpenDART exposes original disclosure documents and XBRL through authenticated APIs. Fresh Korean external-validity expansion is allowed only if an already-authorized credential can be used without exposing it and only after the same spent/selection/evaluation-leakage gates are satisfied. Paper 2 does not depend on this lane for its primary result.

## 7. Freshness and leakage controls

Before cohort opening, bind:

- source-manifest digest;
- spent-manifest digest;
- family/near-duplicate exclusion result;
- selection-rule digest;
- model/runtime/prompt pins;
- trigger policy and normalization;
- calibration manifest and any risk ceilings;
- evidence trigger/evaluation split salt and manifest;
- evaluator revision/container/environment;
- primary endpoints and statistical plan;
- GPU budget guardrail.

Forbidden after cohort opening:

- threshold retuning;
- model-role substitution based on outcomes;
- source-family rebalancing because one arm performs poorly;
- accepting only recovery candidates that hidden ground truth says improved;
- deleting failed/unresolved cases;
- padding a short cohort with development/spent cases.

## 8. Model roles

Freeze semantic roles, not marketing tiers:

- `primary`: existing cost/quality candidate selected only from development evidence.
- `peer`: independent parser/model family used for disagreement evidence; it may be deterministic/native and need not be GPU-backed.
- `strong`: resolver selected only on development/calibration evidence.

Current registry warning: multiple parser candidates are `measured_partial_runtime_image_pending` or `identity_pending`. A fresh confirmatory freeze therefore requires a research runtime attestation that pins exact model artifacts, source revisions, dependency lock, launch recipe, prompt/schema, base runtime/image identity, and resulting digest. Do not convert a historical ad-hoc RunPod environment into a reproducibility claim by prose.

## 9. Primary endpoints

Primary reporting must include both correctness and abstention:

- accepted silent critical error rate;
- critical semantic exactness;
- unresolved rate;
- recovery success conditional on escalation;
- strong-model invocation fraction;
- GPU seconds per 1,000 pages;
- actual external cost per 1,000 pages.

Secondary diagnostics:

- P(hidden error | peer disagreement);
- P(hidden error | peer agreement);
- false escalation rate;
- missed escalation rate;
- document-type/failure-type heterogeneity;
- latency p50/p95/p99;
- operational versus semantic recovery counts.

Never report one aggregate “TAVONEL accuracy” that hides document/failure slices.

## 10. Statistics

- paired correctness: McNemar exact where the unit is paired binary correctness;
- silent-error and rare-event tables: exact tests / exact intervals where appropriate;
- effect size and document-family cluster bootstrap 95% CI before p-values;
- latency/cost: paired bootstrap or permutation without assuming Gaussian tails;
- multiple primary comparisons: Holm correction;
- repeated executions estimate variance and are not independent N.

## 11. GPU spend policy

No fresh GPU spend until:

1. protocol is frozen by committed bytes;
2. fresh cohort is sealed;
3. CPU/synthetic hostile controls are GREEN;
4. model/runtime/artifact/prompt pins are complete;
5. evaluation labels are isolated from runtime;
6. budget receipt is within the predeclared cap.

Stage 1 cap: 300 pages / 18,000 GPU-s / $30 external cost.

Stage 2 cap: 1,000 pages / 72,000 GPU-s / $120 external cost, only after Stage 1 is GREEN.

Larger spend requires a separate explicit budget receipt. Secrets are never serialized into receipts, logs, metadata, hashes-for-display, or repository files.

## 12. Paper claim ladder

### Allowed from historical development evidence

- recovery materially affected prior public benchmark results under the recorded conditions;
- operational recovery prevented many document-processing failures;
- model families exhibited different latency/fidelity/failure modes;
- prediction-only blind ranking failed under the tested historical setting.

### Requires fresh confirmation

- production-available evidence predicts hidden error better than prediction-only baselines;
- disagreement provides useful incremental error evidence;
- selective evidence-guided escalation improves the quality/cost frontier;
- fail-closed recovery reduces accepted silent critical errors at a measured yield cost;
- TAVONEL approaches always-strong reliability with lower strong-model spend.

### Forbidden without new evidence

- universal superiority;
- “99.98% accuracy”;
- “99.94% accurate”;
- all-model/all-document guarantees;
- perfect hallucination/error detection;
- claims derived from oracle-guided historical candidate selection as if it were production routing.

## 13. Definition of done

Paper 2 becomes publication-draft ready only when:

- development evidence register is locally receipt/hash bound;
- exact fresh source/spent/selection manifests are frozen before opening;
- model roles and runtime attestations are frozen;
- hostile controls demonstrate ground-truth leakage and secret serialization are caught;
- fresh cohort is sealed once;
- all five primary arms complete or fail with preserved terminal evidence;
- scorer runs only after the result seal;
- statistical tables and quality-cost frontier are derived from sealed results;
- negative/unresolved outcomes remain in the manuscript;
- claim matrix maps every quantitative sentence to a receipt/digest.
