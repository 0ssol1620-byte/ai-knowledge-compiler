# TAVONEL Verified Knowledge Compiler — Research Execution State

Date: 2026-08-31 (KST)

## 0. Product/research definition

TAVONEL is not an ontology generator and is not a parser/OCR wrapper. The protected product invariant is:

> TAVONEL decides whether derived knowledge remains source-faithful, which changes are semantic versus merely positional/locational, what must be recomputed, what must be escalated to stronger parsing/verification, and which candidate world is safe to promote for RAG/Agents/MCP.

Provider technologies (PaddleOCR, Docling, MinerU, Graphiti, Neo4j, LLMs) remain replaceable compiler backends/projections. Canonical IR, stable identity, evidence lineage, semantic risk, dependency semantics, candidate-world verification, ontology governance, and promotion policy remain TAVONEL-owned semantics.

## 1. Research state discovered from the actual repositories

### 1.1 Family A — Failure-Class-Aware Recovery

Status: **ACTIVE CONFIRMATORY / DO NOT DISTURB**

The canonical research checkout is currently at `a939f17` (`research(sfir10r4): INSTRUMENT FROZEN before partition four`). `research/tavonel_eval_v2/runtime/sfir10r4/state.json` reports `INSTRUMENT_FROZEN`. The active SFIR10R4 instrument and its frozen evidence were intentionally not modified by this work.

Decision: keep Family A execution isolated. Do not use this new worktree to reopen its holdout, change its gates, or consume GPU.

### 1.2 Family B — Verified Incremental Recompilation

Status: **CORE ALGORITHM LANDED; H3.5 FRESH CURRENT-CORE PUBLIC-REVISION EVIDENCE PASSED**

The current canonical lineage already contains typed change-channel separation (`4823d5d`, `feat(core): land typed identity/change separation and selective recompilation`). `EVIDENCE_MOVED` is a locator channel rather than a semantic traversal seed. The old `agent/tavonel-protected-core-promotion` worktree is an obsolete Aug-14 snapshot and must not be used to infer current Core behavior.

A local diagnostic receipt in the dirty canonical checkout reports 330/330 full-rebuild equivalence, zero stale artifacts, and mean rebuild fraction ~0.12626 after semantic-channel promotion. Treat that as a useful diagnostic only: it is not being reclassified here as a new prospective current-core public-corpus result.

A new prospective public-revision experiment was therefore prepared in this isolated worktree:

`research/experiments/H3-B-CURRENT-CORE-PUBLIC-REVISION-01/`

Integrity properties:

- 12 titles selected before fetch and disjoint from the previously known public-revision title set.
- cutoff, section projection, safety gates, and claim boundary fixed before fetch.
- rebuild fraction/work avoided are measurements, not post-hoc PASS thresholds.
- protocol, runner, and live Core hashes sealed before network access; the final V03 seal covers the entire `akc_cir/*.py` package plus the V01/V02 transport lineage.
- offline protocol/seal/current-core smoke tests passed.
- external GPU forbidden; cost remains $0.

Transport lineage was preserved rather than silently editing the frozen experiment. V01 was blocked by HTTP 429 before any persisted corpus or evaluation result. V02 was a predeclared transport-only amendment that also persisted zero corpus and produced no evaluation result because MediaWiki rejects revision-window parameters (`rvstart`/`rvlimit`) with multi-title batch queries (`invalidparammix`). V03 therefore preserved every V01 scientific parameter while predeclaring API-supported single-page requests, a 2-second minimum inter-request interval, bounded 429-only retries, and `Retry-After` handling. V03 was tested and sealed before its first corpus request.

Final V03 execution result on 2026-08-31: **PASS**.

- 12/12 evaluated public revision pairs achieved full-rebuild equivalence.
- stale-left-behind total: **0**.
- 11/12 pairs contained at least one semantic traversal change, exceeding the pre-registered minimum of 8.
- unresolved identity total: **2**; these remained explicit abstentions rather than forced matches.
- total artifacts: **361**; selective rebuild artifacts: **40**.
- mean per-pair rebuild fraction: **0.1468143086**; median: **0.1066176471**; max: **0.3333333333**.
- mean per-pair work avoided: **0.8531856914 (85.32%)**.
- pooled artifact rebuild ratio is 40/361 = **0.1108**, i.e. pooled work avoided is **88.92%**; this pooled statistic is descriptive and was not a pre-registered PASS gate.
- observed channels across the 12 pairs: locator 300, metadata 300, semantic 13, structural 2, unresolved 2. The corresponding change kinds include 300 `evidence_moved`, 300 `metadata_changed`, 12 `modified_claim`, 1 `unit_added`, 2 `structure_changed`, and 2 `identity_unresolved`.
- external GPU cost: **$0.00**.

Post-run integrity verification passed: the V03 seal still verifies, the corpus contains 12 source-metadata records plus 24 immutable revision snapshots (36 files total), every selected revision is before the pre-registered cutoff, and no blocked-execution receipt remains in the successful V03 result directory.

Claim boundary: this closes H3.5 for the stated deterministic English-Wikipedia section projection on the current typed-change-channel Core. It does not by itself prove OCR quality, ontology correctness, legal/regulatory domain correctness, or customer-data performance. The old ~0.12626 diagnostic remains diagnostic; the V03 0.14681 mean per-pair rebuild fraction is the fresh prospective evidence.

## 2. New implementation: Semantic Risk Engine

Status: **IMPLEMENTED + UNIT/REGRESSION TESTED; CALIBRATION RESEARCH NOT YET COMPLETE**

New module:

`packages/cir-python/src/akc_cir/semantic_risk.py`

The existing `parser_verification.py` previously accepted an externally supplied opaque `risk: float`. It now accepts an explainable `SemanticRiskAssessment` as the preferred routing input while keeping the scalar route explicitly marked `legacy_scalar` for migration compatibility.

The feature vector is preserved independently:

- parser error probability
- parsing uncertainty
- cross-model disagreement
- critical-token sensitivity
- semantic-role criticality
- entity criticality
- temporal significance
- authority significance
- dependency blast radius
- downstream-consumer risk

The engine decomposes parser-error probability, downstream semantic impact, authority/temporal/action criticality, and expected semantic damage. The parser decision records both `effective_risk` and `risk_source`, so the routing receipt can explain why a strong parser was or was not selected.

Tests explicitly cover the intended asymmetry:

- uncertain low-value courtesy text can remain low semantic risk;
- a high-confidence date field with strong model disagreement and temporal/action significance becomes critical risk;
- Semantic Risk Engine output overrides a contradictory low legacy scalar when both are supplied;
- legacy scalar behavior remains available and explicitly labeled during migration;
- features fail closed outside `[0,1]`.

What is **not** proven yet: the current aggregation law and thresholds are not claimed as empirically optimal. They require calibration on a frozen parser-disagreement corpus with downstream semantic-damage labels and cost/latency measurements.

### 2.1 Zero-GPU development calibration performed

Status: **RETROSPECTIVE DEVELOPMENT CALIBRATION COMPLETE; CURRENT SCORE UNDER-SENSITIVE UNDER THE AVAILABLE PROXIES**

Experiment:

`research/experiments/SEM-RISK-DEV-CAL-01/`

This study reused only the already-spent August-1 OmniDocBench 18-page × 3-repeat evidence and its exact local ground truth. No OCR/VLM inference, network access, or GPU spend was performed. The input manifest SHA256-pins the GT, 18×3 Paddle markdown outputs, 18×3 MinerU VLM markdown outputs, official partial-evaluation results, and the current sealed `semantic_risk.py` bytes.

The official preserved aggregate evaluator still shows the known specialist split: MinerU VLM is stronger on text/table/reading-order metrics, while Paddle remains better on formula edit distance. Page-level routing analysis uses a separate deterministic TAVONEL custom development damage metric and is explicitly **not** called an official OmniDocBench metric.

Development findings:

- current Semantic Risk score range: **0.000000–0.009998**;
- predeclared thresholds 0.25 / 0.50 / 0.55 / 0.75 therefore escalated **0/18 pages**;
- always-primary custom mean damage: **0.200873**;
- always-strong custom mean damage: **0.215102** — worse than always-primary on this custom page-level objective;
- page oracle mean damage: **0.168969**, leaving **0.031904** mean damage reduction available to a correct specialist router;
- MinerU had lower custom damage on **8** pages, higher damage on **9**, and tied on **1**;
- 12 pages contained critical tokens, 9 contained GT tables, and 2 contained GT isolated formulas;
- the Paddle-vs-MinerU disagreement proxy cannot be treated as cheap routing evidence here because observing it already requires the strong parser on all pages.

Interpretation: do **not** respond by lowering the production threshold after seeing these 18 pages. The development evidence instead shows that the current risk computation collapses when the independent error signal and semantic-consequence dimensions are absent. The next fresh study must provide a genuinely cheap independent peer/model uncertainty signal plus temporal/authority/dependency/downstream annotations. Until then, the current 0.55 product-shell value remains a policy placeholder rather than an empirically selected production threshold.

## 3. New implementation: Semantic Preservation Contract

Status: **IMPLEMENTED + UNIT/REGRESSION TESTED; FIRST ENFORCEABLE CONTRACT LAYER**

New module:

`packages/cir-python/src/akc_cir/semantic_preservation.py`

The first product-enforceable invariants are:

1. referenced source blocks still exist;
2. referenced table cells still belong to the attached source blocks;
3. all source references remain bound to the same canonical document/version;
4. declared critical tokens (dates, quantities, versions, identifiers, etc.) remain present in the attached evidence.

Violations return a local repair scope (`quarantine_block_ids`, `quarantine_page_indexes0`) and the recovery action `rerender_or_stronger_parser_then_reverify`. This deliberately avoids making full-document reprocessing the default response.

Tests cover a table-derived world fact `N2 -> Version -> 1.5.3`, silent value corruption (`1.5.8`), detached cells, cross-version evidence, and missing source blocks.

What is **not** proven yet: token/source preservation is not equivalent to complete natural-language semantic correctness. The next contract layer must preserve table row/column attachment, claim argument roles, entity/relation bindings, temporal validity, authority semantics, and world-fact provenance through Candidate World promotion.

## 4. Product control-plane integration

Status: **IMPLEMENTED IN ISOLATED PRODUCT WORKTREE + TESTED**

Product worktree:

`D:\CodexProjects\tavonel-saas-foundation-vkc-research`

Branch:

`agent/tavonel-vkc-product-contract`

`CompileJobEnvelope.route` now has additive migration fields for:

- `semanticRiskPolicy`
- `evidenceContractVersion`
- `ontologyVersion`

The semantic-risk policy requires an explicit policy version, escalation/review thresholds, feature-vector preservation, and fail-closed behavior.

`CompileReceipt` now has additive fields for:

- semantic-risk policy version/disposition
- evidence-contract version
- ontology version
- routing receipt ID
- verification receipt ID
- graph-projection version
- semantic-preservation result

Artifact kinds now include `ontology_manifest`, `evidence_graph`, `graph_projection`, and `retrieval_projection` in addition to the existing canonical IR / knowledge units / dependency graph / candidate world.

Promotion boundary change: when an evidence contract is enabled, candidate persistence now requires semantic preservation PASS plus routing and verification receipts. Existing jobs without the new contract remain backward-compatible.

Verification performed:

- focused product contract + field-map: **13/13 PASS**
- TypeScript: **`tsc --noEmit` PASS**

## 5. Existing ontology branch — preserve, then strengthen

Status: **GOOD GOVERNANCE SKELETON; INDUCTION SEMANTICS STILL V1**

Actual branch inspected: `agent/tavonel-ontology-gates`.

The branch already contains deterministic induction based on mention frequency and co-occurrence/affinity, with quality gates for coverage, distinctiveness, and stability. It also has lifecycle transition validation and reviewer-note requirements. This is valuable infrastructure and should be preserved.

Do **not** replace this with an LLM-only ontology generator. The next research layer should feed additional candidates/evidence into the existing proposal/governance machinery:

- LLM candidate extraction (proposal only)
- learned graph candidates (Graphiti or equivalent, proposal only)
- domain packs / RDF/OWL alignment
- source-support evidence
- SHACL constraint validation
- backward-compatibility checks
- retrieval/downstream-utility tests
- semantic impact analysis before activation

Ontology generation and ontology activation must remain separate operations.

## 6. Graph runtime boundary

Status: **ARCHITECTURAL DECISION — DO NOT MAKE EXTERNAL GRAPH RUNTIME CANONICAL TRUTH**

Graphiti/Neo4j/FalkorDB should be derived graph projections from TAVONEL Canonical Knowledge IR. They may own temporal/hybrid retrieval runtime behavior but must not become the authority for canonical evidence identity, source lineage, valid-time history, or promotion state.

Required boundary:

`Canonical Knowledge IR -> versioned graph projection adapter -> Graphiti/Neo4j/FalkorDB -> retrieval`

A graph projection must therefore be reproducible from a promoted world and carry `graphProjectionVersion` in the compile receipt.

## 7. Revised research order

### Priority 0 — preserve ongoing frozen work

- Do not modify SFIR10R4 frozen Family A evidence.
- Do not open sealed holdouts casually.
- Do not spend GPU merely because a new direction was proposed.

### Priority 1 — preserve and extend the now-passed Family B H3.5 evidence

H3.5 is now closed on its declared public-revision projection: 12/12 equivalence, stale 0, evidence adequacy PASS, and mean work avoided 85.32%. The next Family B work is robustness expansion rather than repairing the core claim: add non-Wikipedia document families and production-shaped revision fixtures without changing the already-sealed V03 result or retroactively widening its claim boundary.

### Priority 2 — fresh Semantic Risk confirmatory after the completed development calibration

The 18-page retrospective calibration is now complete and found the current score under-sensitive under its available proxies. The next study must be a new frozen corpus selected before parser outputs are observed. Compare at minimum:

- always-primary
- always-strong
- genuinely cheap independent parser-consensus/disagreement routing
- TAVONEL semantic-risk routing

Measure semantic error, critical-token/date/quantity preservation, table semantic fidelity, temporal/authority correctness, dependency blast radius, escalation ratio, GPU seconds, cost, and latency. Use a development partition to fit any feature normalization, then seal a separate untouched confirmatory partition before the final threshold/policy evaluation. Do not use the existing 18 pages to select the production threshold.

### Priority 3 — expand Semantic Preservation Contract end-to-end

Extend evidence attachment from block/cell/token to:

`pixel/bbox -> cell/span -> claim arguments -> entity/relation/event -> temporal/authority fact -> world fact`

A contract violation must identify the minimal repair region and force reparse/reverification before candidate promotion.

### Priority 4 — Parser Arena as a replaceable backend plane

Preserve the already measured Primary / source-native peer / Strong role separation. Add Docling/native format adapters at input normalization; keep high-assurance VLMs behind routing/licensing/cost policy. TAVONEL owns the routing/evidence contract, not any parser model.

### Priority 5 — Verified Ontology Evolution

Strengthen the existing `ontology-gates` proposal and lifecycle machine with source support, SHACL, backward compatibility, downstream utility, and impact analysis. Produce candidate ontology versions; never silently auto-activate schema changes.

### Priority 6 — derived temporal graph projection

Add Graphiti/Neo4j/Falkor adapters only after canonical evidence/ontology version contracts are explicit. Test projection rebuildability and historical preservation; external graph state is disposable/derivable.

### Deferred — Minimal Verification Frontier

Do not prioritize minimal-oracle research ahead of Semantic Risk and Semantic Preservation. It is potentially valuable, but it is less directly tied to near-term product correctness/economics and has a denser prior-art surface.

## 8. Verification ledger for this worktree

Focused Semantic Risk + parser verification: **11 PASS**.

Semantic Risk + Semantic Preservation + parser verification: **16 PASS**.

H3-B protocol/seal/current-core offline smoke + new modules: initial run found a test-only dynamic import helper defect (18 PASS / 2 FAIL); fixed before seal and before corpus fetch. Re-run: **21 PASS**.

Broader semantic-diff/recompilation/knowledge-CI/parser/new-contract regression scope: **83 PASS**.

H3-B V01 execution: **BLOCKED, HTTP 429, corpus persisted 0, evaluation results 0, GPU $0**.

H3-B V02 transport-only amendment: pre-seal tests **24 PASS**; execution **BLOCKED, MediaWiki `invalidparammix`, corpus persisted 0, evaluation results 0, GPU $0**.

H3-B V03 transport-only amendment: pre-seal tests **28 PASS**; sealed prospective execution **PASS** — 12 pairs, 11 changed pairs, 12/12 equivalence, stale 0, evidence adequacy PASS, mean rebuild fraction 0.1468143086, mean work avoided 85.32%, GPU $0. Post-run seal/corpus/cutoff integrity checks PASS.

Semantic Risk retrospective development-calibration instrumentation: initial run found one signed-decimal critical-token extraction defect before calibration execution; fixed before producing the final receipt. Final calibration tests: **7 PASS**. Calibration completed on 18×3 already-preserved outputs with **new GPU $0**, then H3-B V03 seal re-verification **PASS**.

No commit or push was performed by this work.

## 9. Claim discipline

Use these labels consistently:

- **PROVEN**: backed by frozen/registered experiment evidence on the stated scope.
- **IMPLEMENTED**: code exists and regression tests pass, but scientific performance/optimality may remain unproven.
- **DIAGNOSTIC**: useful observed evidence not eligible for a fresh confirmatory claim.
- **BLOCKED**: protocol/instrument may be ready, but a named external or gate condition prevented the requested evidence from being produced.

Current bottom line:

**Family B change-channel separation is implemented and now has passed prospective current-core public-revision H3.5 evidence on its declared projection: 12/12 full-rebuild equivalence, stale 0, and mean per-pair work avoided 85.32%. Semantic Risk and Semantic Preservation are now real product code with passing regressions but still need frozen empirical calibration/validation. The SaaS control plane now has the contract surface needed to carry those receipts. Ontology governance should be strengthened rather than replaced, and graph systems must remain derived projections.**
