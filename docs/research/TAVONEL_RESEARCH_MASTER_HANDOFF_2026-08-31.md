# TAVONEL Research Master Handoff
## Verified Knowledge Compiler / Selective Recompilation / Semantic Risk / Semantic Preservation / Ontology & Graph

**Handoff date:** 2026-08-31 (KST)  
**Status basis:** Local repository/runtime state re-checked immediately before this handoff  
**Primary purpose:** Allow a new research/engineering worker to continue without re-discovering prior decisions, invalidating frozen evidence, or overstating paper claims.

---

# 0. Executive Status — Read This First

## 0.1 Is the research fully complete?

**No. The overall research and paper are not finished yet.**

However, several important parts are already closed at a strong evidence level:

- **Family B — typed change-channel separation / current-core selective recompilation:** **PROVEN for the declared public-revision projection.**
- **Semantic Risk Engine:** implementation is complete, development calibration is complete, and a new prospective confirmatory experiment has been frozen. **The confirmatory inference/evaluation is not complete yet.**
- **Semantic Preservation Contract:** core fail-closed implementation exists and Product-side E2E receipt binding is implemented/tested.
- **Product control plane:** semantic-risk/evidence-contract/ontology/graph receipt fields and promotion conditions are implemented/tested.
- **Verified Ontology Evolution contract:** Product-side fail-closed governance contract implemented/tested.
- **Derived Graph Projection contract:** Product-side canonical-truth boundary and reproducible projection contract implemented/tested.
- **Current confirmatory corpus acquisition (`SEM-RISK-CONF-02`):** **SUCCESS — 192 frozen input files acquired, GT not acquired, GPU 0 seconds.**
- **GPU inference for the new Semantic Risk confirmatory:** **NOT YET RUN.**
- **Paper final statistics, ablations, figures, manuscript, hostile review, submission bundle:** **NOT YET COMPLETE.**

The immediate next job is therefore **not to redesign the research**. It is to finish the already-frozen Semantic Risk confirmatory without changing its scientific parameters.

---

# 1. Core Research Goal

TAVONEL is being developed as a **Verified Knowledge Compiler**, not merely an OCR/RAG ingestion tool.

The research goal is to demonstrate that a document/knowledge compilation system can:

1. preserve source-verifiable canonical knowledge;
2. distinguish **where evidence moved** from **what meaning changed**;
3. recompile only the meaning-affected dependency closure instead of rebuilding everything;
4. remain equivalent to a full rebuild under declared conditions;
5. estimate **semantic risk** rather than relying only on parser confidence;
6. selectively escalate difficult or consequential content to another parser/specialist;
7. verify that critical meaning survives compilation using an enforceable **Semantic Preservation Contract**;
8. evolve ontology under evidence-backed governance rather than allowing an LLM to mutate canonical truth;
9. expose graph databases as **derived, rebuildable projections**, not the source of truth.

The strongest coherent paper story is:

> **A verified knowledge compilation architecture can reduce unnecessary recompilation while retaining full-rebuild semantic equivalence, and can use consequence-aware parser verification plus evidence-preservation contracts to make selective processing auditable and fail-closed.**

Do not dilute this into “we tried many OCR models.” OCR/model routing is an enabling layer; **verified compilation is the central research contribution.**

---

# 2. Recommended Paper Scope

## 2.1 Primary paper — recommended

Working theme:

**Verified Incremental Knowledge Compilation with Typed Change Channels, Semantic-Risk Routing, and Evidence Preservation**

The main paper should center on four contributions:

### Contribution C1 — Typed change-channel separation
Separate at least:

- locator/evidence movement,
- metadata change,
- semantic change,
- structural change,
- unresolved identity.

Key idea:

**`EVIDENCE_MOVED` must not automatically become a semantic traversal seed.**

### Contribution C2 — Safe selective recompilation
Use the typed change channels and stable identity to rebuild only the affected semantic dependency closure.

Primary evidence:
- fresh current-core public-revision experiment;
- full-rebuild equivalence;
- stale-left-behind = 0;
- measured work avoided.

### Contribution C3 — Semantic Risk routing
Parser routing should not be “low confidence → stronger model.”

Risk should decompose:

- probability that parsing is wrong,
- downstream consequence if wrong,
- authority/temporal/action criticality,
- dependency blast radius / downstream consumer risk.

Then route to **failure-class specialists**, not one universal “strong model.”

### Contribution C4 — Semantic Preservation Contract
Before a candidate world can be promoted/persisted, verify that source-backed critical meaning remains attached to valid evidence and the same source version.

This creates a clear fail-closed boundary between:
- parser/model output,
- compiled candidate,
- promoted knowledge world.

## 2.2 Secondary / follow-up paper candidate

**Verified Ontology Evolution and Reproducible Graph Projection**

Ontology/graph work is implemented enough to support the system paper, but unless strong empirical utility/regression data is added, it should **not dominate the primary paper**.

Potential second-paper questions:
- evidence-backed ontology proposal admission;
- backward compatibility;
- SHACL/shape validation;
- downstream retrieval/QA utility;
- ontology-change impact analysis;
- reproducible rebuilds of Neo4j/FalkorDB/Graphiti projections.

---

# 3. Evidence Classification Vocabulary

All future writing must use these labels consistently.

## PROVEN
Fresh or otherwise appropriately frozen evidence supports the declared claim boundary.

## IMPLEMENTED
Code and tests exist, but the scientific claim has not yet been confirmatorily established.

## DEVELOPMENT / DIAGNOSTIC
Useful for engineering/calibration; must not be presented as confirmatory evidence.

## FROZEN — PENDING EXECUTION
Protocol/selection/evaluator are fixed prospectively, but required inference/evaluation is unfinished.

## BLOCKED / TRANSPORT FAILURE
The scientific experiment did not produce an evaluable result because transport/infrastructure failed. Never call this a negative scientific result.

---

# 4. Repository / Worktree State

## 4.1 Core research worktree

**Project ID:** `local-ai-knowledge-compiler-vkc-research-15966eb25f`  
**Filesystem:** `D:\CodexProjects\ai-knowledge-compiler-vkc-research`  
**Branch:** `agent/tavonel-vkc-research`  
**Base observed when work started:** canonical lineage around commit `a939f17`

Important:
- This is an **isolated research worktree** intentionally used to avoid contaminating other ongoing/frozen work.
- Work performed in this handoff lineage is **uncommitted unless a later worker explicitly verifies otherwise**.
- No push was performed by this worker.
- Before any commit, inspect `git status`, diffs, experiment receipts, and the current canonical branch.

## 4.2 Product/control-plane worktree

**Project ID:** `local-tavonel-saas-foundation-vkc-research-26ff794434`  
**Filesystem:** `D:\CodexProjects\tavonel-saas-foundation-vkc-research`  
**Branch:** `agent/tavonel-vkc-product-contract`

Also isolated and uncommitted unless verified otherwise.

## 4.3 Critical rule

Do **not** casually merge these worktrees into canonical before:
- reviewing all frozen experiment boundaries;
- deciding which code belongs in canonical core vs research-only;
- running full regressions;
- preserving receipts/provenance.

---

# 5. Frozen Work That Must Be Preserved

## 5.1 Family A

The active SFIR10R-family confirmatory work is already frozen.

**Do not alter its holdout, gates, or confirmatory evidence.**

This handoff did not consume its holdout or GPU.

## 5.2 Family B H3 V03 seal

The Family B public-revision V03 experiment was re-verified after later development work:

- V03 protocol tests: PASS
- actual `verify_seal()`: PASS

Therefore, the existing Family B H3 evidence remains intact.

Do not modify files included in that V03 frozen hash map.

---

# 6. Family B — Typed Change Separation / Selective Recompilation

## 6.1 Historical discovery

An older Aug-14 branch snapshot showed `EVIDENCE_MOVED` entering semantic changed IDs.

That snapshot is obsolete.

The current canonical lineage already contains typed separation behavior (landed in commit lineage around `4823d5d`), separating evidence movement from semantic traversal.

## 6.2 Fresh current-core prospective experiment

Experiment lineage:

- `H3-B-CURRENT-CORE-PUBLIC-REVISION-01`
- `H3-B-CURRENT-CORE-PUBLIC-REVISION-02`
- `H3-B-CURRENT-CORE-PUBLIC-REVISION-03`

### V01
- predeclared 12 titles;
- scientific gates frozen before fetch;
- HTTP 429 before corpus persistence;
- persisted corpus = 0;
- GPU = $0 / 0 seconds.

Classification: **transport-blocked, no scientific result.**

### V02
Transport-only batch-query amendment.
- failed because MediaWiki revision-window parameters are invalid for multi-page query;
- corpus persisted = 0;
- GPU = 0.

Classification: **transport-blocked, no scientific result.**

### V03
Transport-only amendment:
- one page per MediaWiki request;
- fixed pacing;
- retry only HTTP 429;
- non-429 errors fail closed;
- complete `akc_cir/*.py` included in seal.

V03 ran successfully.

## 6.3 V03 result

**Pairs:** 12  
**Full-rebuild equivalence:** **12/12 PASS**  
**All pairs equivalent:** `True`  
**Stale left behind:** **0**  
**Unresolved identity:** 2 — abstained rather than force-matched  
**Total artifacts:** 361  
**Total rebuilt:** 40  
**Mean rebuild fraction:** `0.1468143086298593`  
**Median rebuild fraction:** `0.10661764705882354`  
**Max rebuild fraction:** `0.3333333333333333`  
**Mean work avoided:** `0.8531856913701407` = **85.32%**  
**Safety gate:** PASS  
**Evidence adequacy:** PASS  
**GPU:** 0

Change channels:
- locator: 300
- metadata: 300
- semantic: 13
- structural: 2
- unresolved: 2

Change kinds:
- `evidence_moved`: 300
- `metadata_changed`: 300
- `modified_claim`: 12
- `structure_changed`: 2
- `unit_added`: 1
- `identity_unresolved`: 2

## 6.4 Claim allowed

Allowed:

> On the declared public-revision projection, typed locator/metadata changes can be excluded from semantic traversal while preserving full-rebuild equivalence and leaving no stale artifacts, with 85.32% mean work avoided in this experiment.

Not allowed:

> TAVONEL always avoids 85% of work on every document type.

Not allowed:

> This proves all incremental compilation is universally safe.

## 6.5 Next robustness extension after current Semantic Risk work

Once the current confirmatory is closed, expand Family B robustness beyond Wikipedia-like public revisions into production-shaped sources, ideally:
- Git/versioned technical docs,
- eCFR/regulatory,
- SEC filings,
- internal revision-shaped synthetic corpora with tables/IDs/dates.

Do not replace the successful H3 evidence; add robustness evidence.

---

# 7. Semantic Risk Engine

## 7.1 Core implementation

Implemented in:

`packages/cir-python/src/akc_cir/semantic_risk.py`

The feature vector preserves 10 explainable signals:

1. parser error probability
2. parsing uncertainty
3. cross-model disagreement
4. critical-token sensitivity
5. semantic-role criticality
6. entity criticality
7. temporal significance
8. authority significance
9. dependency blast radius
10. downstream-consumer risk

The engine computes decomposed notions of:
- parser error likelihood;
- downstream semantic impact;
- authority/temporal/action criticality;
- expected semantic damage.

The design deliberately avoids collapsing every raw signal too early.

## 7.2 Parser verification integration

`parser_verification.py` now accepts:

`semantic_risk: SemanticRiskAssessment | None`

while keeping legacy scalar risk compatibility.

When both are supplied:
- semantic-risk assessment wins.

Verification decision receipts record:
- `effective_risk`
- `risk_source`

## 7.3 Important semantic-risk engineering correction

A development test exposed a real design weakness:

A version corruption such as:

`1.5.3 -> 1.5.8`

could have high overall text similarity and initially remain too low risk.

The quality-layer peer signal was strengthened so **critical-token set disagreement acts as a hard semantic signal** rather than being washed out by average edit similarity.

Tests passed after the correction.

Do not remove this behavior.

---

# 8. Semantic Risk Development Calibration — NOT Confirmatory

Experiment:

`research/experiments/SEM-RISK-DEV-CAL-01/`

Classification:

**RETROSPECTIVE_DEVELOPMENT_CALIBRATION_ONLY**

It uses the already existing frozen OmniDocBench 18-page demo evidence.

No new GPU inference was used.

## 8.1 Model context

Primary:
- PaddleOCR-VL 1.6

Specialist/challenger:
- MinerU VLM c1

Three repeats were available for 18 pages for both model paths.

## 8.2 Existing official aggregate context

Paddle:
- text edit: `0.038208855307978`
- formula edit: `0.11361807442948028`
- table edit: `0.05188793071921827`
- table TEDS: `0.9060647206933243`
- table structure TEDS: `0.9383699633699635`
- reading-order edit: `0.091270108297707`

MinerU:
- text edit: `0.03425784639018182`
- formula edit: `0.12297493624315398`
- table edit: `0.022737127440760996`
- table TEDS: `0.9596961750183709`
- table structure TEDS: `0.9845238095238097`
- reading-order edit: `0.07669309996566243`

Critical interpretation:

**MinerU is not a universal oracle.**
Paddle was better on the formula aggregate in this evidence.
Therefore future routing must be failure-class-specific.

## 8.3 Custom development metric result

Always-primary mean custom semantic damage:
`~0.2008730579954079`

Page-oracle mean:
`~0.16896875334379247`

Oracle reduction:
`~0.03190430465161542`

Always-strong mean:
`~0.215102` — worse than always-primary under the custom development metric.

Current semantic-risk scores under the available proxy signals:
- maximum ~`0.009997986`
- effectively near zero
- tested production-like thresholds did not escalate pages.

Diagnosis:

**UNDER_SENSITIVE_UNDER_AVAILABLE_DEVELOPMENT_FEATURE_PROXIES**

This is the crucial conclusion:

> Do not “fix” this by simply lowering the threshold post hoc.

The problem is missing/weak independent error and downstream-consequence signals, not merely the numeric threshold.

## 8.4 What the dev calibration taught us

The next confirmatory must test:

- cheap independent peer disagreement;
- primary repeat instability where native peer is impossible;
- critical-token instability;
- structure/failure class;
- downstream consequence features;
- specialist selection.

It must not use the same 18 pages to choose production thresholds and then call them confirmatory.

---

# 9. Cheap Peer Strategy

## 9.1 Existing native PDF parser

A deterministic native PDF parser already exists:

`packages/native-parsers/src/akc_native_parsers/pdf_parser.py`

It uses `pypdf` and extracts:
- text objects;
- page geometry;
- embedded images;
- vector/graphics placements;
- source references;
- CIR blocks.

This provides a promising **cheap independent peer** for born-digital PDFs.

## 9.2 Boundary

Native PDF extraction only provides useful text disagreement when the PDF has a meaningful text layer.

It is not an OCR peer for image-only/scanned pages.

Therefore the frozen Semantic Risk confirmatory uses two different signal lanes:

### Lane A — born-digital PDF
Use:
- Paddle primary parse
- deterministic native peer disagreement

### Lane B — image-only / OCR benchmark
Native peer unavailable.
Use:
- Paddle repeat instability
- critical-token repeat instability
- structural/failure features

Do not pretend these are the same signal.
Report them separately.

## 9.3 Docling / Tesseract investigation

Repository inspection found:
- source-native references/files: 24
- Tesseract references: 0
- Docling references: 4

Docling is present only as an unpromoted candidate/reference:
- repository: `docling-project/docling`
- observed candidate revision: `bbdc862`
- license: MIT
- current status: candidate remains unpromoted

Do not state Docling is already integrated.

Future cheap-peer work may evaluate Docling, but it is not required before finishing the already-frozen current confirmatory.

---

# 10. New Prospective Semantic Risk Confirmatory

This is the most important unfinished research item.

## 10.1 V01 — `SEM-RISK-CONF-01`

A new prospective protocol was built and frozen.

Selection design:
- full OmniDocBench v1.6 metadata space;
- development demo 18 pages explicitly excluded;
- 128 selected pages total;
- Lane A = 64
- Lane B = 64
- lane overlap = 0;
- selection chosen deterministically before GT evaluation.

Pre-freeze tests passed.

H3 V03 seal was reverified before freeze.

### V01 acquisition failure

Lane A acquisition successfully downloaded its selected born-digital inputs.

Observed after failure:
- Lane A images: 64
- Lane A PDFs: 64
- Lane B images: 0

Then Lane B hit HTTP 404.

Root cause:
- OmniDocBench annotation recorded image paths as basename-only;
- actual Hugging Face tree used an `images/` path prefix.

This was a **transport representation mismatch**, not a scientific result.

Ground truth remained unopened/not acquired.
GPU remained 0.

V01 partial corpus must be preserved as failed transport evidence.
Do not reuse it as a “clean” confirmatory corpus.

---

# 11. Semantic Risk Confirmatory V02 — Current Frozen Experiment

Experiment:

`research/experiments/SEM-RISK-CONF-02/`

## 11.1 Amendment type

**TRANSPORT_ONLY**

Scientific parameters were not changed.

The following scientific artifacts were copied byte-for-byte from V01:
- protocol;
- selection manifest;
- native lane runner;
- inference-manifest builder;
- evaluator.

The V02 transport layer adds only:
- complete Hugging Face tree pagination;
- basename -> unique real tree path resolution;
- fail-closed handling if missing/ambiguous.

Full repository tree inspection showed:
- first API page = 1000 paths;
- second cursor page = 651 paths;
- total = 1651;
- selected Lane B cases uniquely resolved = **64/64**;
- missing/ambiguous = 0.

## 11.2 V02 pre-execution validation

V02-related pre-run tests:

**23/23 PASS**

These covered:
- scientific artifact equality to V01;
- transport-only scope;
- fail-closed resolution;
- preserved H3 V03 boundary.

## 11.3 V02 current acquisition result — SUCCESS

The latest runtime state shows the V02 acquisition job completed successfully.

Result:

- `file_count`: **192**
- `gpu_seconds`: **0.0**
- `ground_truth_acquired`: **false**
- `lane_b_unique_transport_resolutions`: **64**
- `transport_version`: **V02**

192 expected input files correspond to:
- 64 Lane A images
- 64 Lane A source PDFs
- 64 Lane B images

This is the exact current handoff boundary.

## 11.4 Absolute rule

**Do not edit the frozen V02 science/evaluator/selection files after this point.**

Treat the experiment directory’s frozen scientific/transport artifacts as immutable.

If a transport or runtime defect is found:
- preserve V02;
- create a new explicitly classified amendment lineage;
- prove scientific artifacts unchanged.

If signal definitions, thresholds, selection, specialist policy, or evaluator change:
- that is a **scientific amendment** and must not be disguised as transport-only.

---

# 12. Exact Next Steps for `SEM-RISK-CONF-02`

Proceed in this order.

## Step 1 — Reverify frozen integrity

Before doing any inference:
- verify V02 transport/science hashes;
- reverify H3 V03 seal;
- confirm GT is absent from inference input directories;
- confirm 192 acquired inputs exactly match the acquisition receipt.

## Step 2 — Run Lane A deterministic native parser

Entry point:

`research/experiments/SEM-RISK-CONF-02/run_lane_a_native.py`

Purpose:
- parse the 64 born-digital source PDFs;
- produce native text/CIR-derived peer output;
- freeze/hash outputs.

This should require no GPU.

Do not let the native parser read ground truth.

## Step 3 — Build inference manifests

Entry point:

`research/experiments/SEM-RISK-CONF-02/build_inference_manifests.py`

Produce ground-truth-free manifests for:
- Paddle;
- MinerU/specialist;
- the two lanes as frozen.

The manifest must bind:
- case IDs;
- source SHA-256;
- dataset revision;
- expected counts;
- no-GT boundary.

## Step 4 — GPU inference

Run the exact pinned:
- PaddleOCR-VL 1.6 primary
- MinerU specialist/challenger

using the frozen model revision/artifact identities already recorded in the repository protocol/candidate registry.

### Critical warning

An attempt to reuse:

`research/tavonel_recovery_eval_v1/runpod_qualification.py`

was correctly **REFUSED** with:

`spent qualification smoke input is absent`

Reason:
that entry point belongs to an older recovery-campaign qualification flow and expects an already-consumed old smoke input.

Do **not** weaken or bypass that gate.

Instead build/use a **confirmatory-specific RunPod controller** that reuses the secure provider lifecycle principles:
- exact model/runtime pins;
- process-local secret handling;
- GT-free upload;
- immutable receipts;
- provider billing receipt;
- timeout/watchdog;
- guaranteed cleanup;
- verify provider absence after deletion;
- no secret values in logs/receipts.

Do not expose or copy credential values into the repository.

## Step 5 — Freeze model outputs before GT

For every model output/repeat:
- hash raw artifacts;
- freeze run summaries;
- record model revision/artifact digest;
- record runtime/GPU identity;
- record input-manifest digest;
- record latency;
- record failures explicitly.

Only after all inference artifacts are frozen may GT evaluation begin.

## Step 6 — Evaluate with the already-frozen evaluator

Entry point:

`research/experiments/SEM-RISK-CONF-02/evaluate_confirmatory.py`

The evaluator was intentionally designed to:
1. hash/freeze inference outputs first;
2. then read GT;
3. not persist GT into inference output roots.

Do not alter it after seeing results.

## Step 7 — Decide claim using preregistered gates

Do not “massage” the result.

If the gate passes:
- Semantic Risk routing becomes prospective evidence.

If it fails:
- report honest confirmatory failure;
- use it to design V2 research;
- do not retune threshold on the same cohort and call the retuned result confirmatory.

---

# 13. What the Semantic Risk Confirmatory Must Compare

At minimum preserve the frozen policy comparison logic.

Conceptual baselines:

1. **Primary only**
2. **Always specialist**
3. **Cheap-peer / repeat-instability routing**
4. **Semantic-risk + specialist routing**
5. Optional page oracle only as an explanatory upper bound — never deployable policy

Report:

- mean semantic damage;
- critical-token/date/quantity/version loss;
- table fidelity;
- formula fidelity;
- false-safe rate;
- false-escalation rate;
- escalation fraction;
- latency;
- GPU seconds;
- estimated/actual provider cost;
- specialist class distribution;
- failures/timeouts;
- by-lane metrics.

The paper needs both:
- **quality/safety**
- **economics/compute**

A routing method that improves quality only by always running both expensive parsers is not a strong selective-routing result.

---

# 14. Semantic Preservation Contract

## 14.1 Core implementation

Implemented in:

`packages/cir-python/src/akc_cir/semantic_preservation.py`

The first enforceable preservation layer verifies:

1. referenced source blocks exist;
2. referenced table cells belong to the attached source blocks;
3. source references remain on the same canonical document/version;
4. declared critical tokens remain present in evidence.

Violation output includes local repair scope:
- quarantine block IDs;
- quarantine page indexes;
- recovery action such as rerender/stronger-parser/reverify.

Examples tested:
- table fact `N2 -> Version -> 1.5.3`;
- corruption to `1.5.8`;
- detached cells;
- cross-version evidence;
- missing source blocks.

## 14.2 Product-side E2E strengthening

The Product compile envelope now goes beyond a simple:
`semanticPreservation == passed`

Candidate persistence verifies that preservation/routing/verification receipts are bound to the same:
- job;
- source version;
- candidate world;
- contract/policy version;
- valid digest lineage.

This closes a major systems gap: a random PASS receipt cannot authorize another candidate.

Product tests for this area passed.

---

# 15. Product Control Plane

Key file:

`tavonel-saas-foundation-vkc-research/shared/productCoreCompileEnvelope.ts`

Implemented route fields:
- `semanticRiskPolicy`
- `evidenceContractVersion`
- `ontologyVersion`

Semantic risk policy includes:
- explicit version;
- escalation threshold;
- review threshold;
- feature-vector preservation;
- fail-closed flag.

Receipt fields include:
- semantic-risk policy version;
- disposition;
- evidence contract version;
- ontology version;
- routing receipt ID;
- verification receipt ID;
- graph projection version;
- semantic preservation result.

Artifact kinds now include:
- `canonical_ir`
- `knowledge_units`
- `dependency_graph`
- `ontology_manifest`
- `evidence_graph`
- `candidate_world`
- `graph_projection`
- `retrieval_projection`

Backward compatibility is preserved for old jobs that do not opt into the new evidence contract.

---

# 16. Verified Ontology Evolution

Product-side implementation:

`shared/verifiedOntologyEvolution.ts`

Tests:

`server/foundation/verifiedKnowledgeEvolution.test.ts`

## 16.1 Required direction

Keep the earlier ontology governance skeleton:
- deterministic candidate proposal;
- coverage;
- distinctiveness;
- stability;
- lifecycle/reviewer governance.

Strengthen it with:
- source support;
- shape/schema validation;
- backward compatibility;
- downstream impact;
- versioned ontology receipts.

## 16.2 Canonical rule

**LLM-generated ontology proposals are non-authoritative.**

An LLM may:
- propose class/property names;
- summarize candidate evidence;
- suggest relations.

It may not directly mutate canonical ontology.

Promotion requires deterministic/evidence-backed gates.

## 16.3 Product-side contract status

Implemented fail-closed behavior for:
- missing support;
- duplicate/conflicting class/property changes;
- missing parent/domain;
- unsafe deprecation;
- invalid migration/backward-compatibility state;
- review/reject disposition.

A previous TypeScript compatibility error involving Set spread was corrected.
Final tests/typecheck passed.

---

# 17. Graph Projection Boundary

Product implementation:

`shared/graphProjectionContract.ts`

## 17.1 Architectural rule

Canonical truth is:

**Canonical Knowledge IR / promoted knowledge world**

Graph stores such as:
- Neo4j
- FalkorDB
- Graphiti

must remain:

**derived projections**

Correct direction:

`Canonical Knowledge IR -> versioned graph projection adapter -> graph store -> retrieval`

Not:

`graph DB -> canonical truth`

## 17.2 Why this matters

The graph must be:
- reproducible;
- rebuildable from canonical promoted state;
- versioned;
- receipt-bound;
- safe to discard/recreate.

This prevents graph-store mutations or embedding/runtime drift from silently becoming canonical knowledge.

Product graph/ontology tests passed.

---

# 18. Product-side Test Status

Latest observed Product-side result after the compatibility fix:

- Product–Core envelope + preservation tests
- Verified ontology evolution
- graph projection behavior

**16/16 tests PASS**

Full TypeScript typecheck:

**PASS**

There was an earlier intermediate target-compatibility failure:
- Set iteration under low JS target.

It was fixed and is not a remaining defect.

---

# 19. Core Test Status

Important successful checkpoints during this work:

- Semantic Risk + parser verification focused tests: 11 PASS
- Semantic Risk + Preservation + parser verification: 16 PASS
- broader semantic-diff/recompilation/CI/parser regression: 83 PASS
- broader suite including H3 V01/V02/V03 protocol tests: **90/90 PASS**
- peer semantic-signal tests after critical-token hardening: **6/6 PASS**
- Semantic Risk confirmatory pre-freeze suite: **14 PASS**
- V02 transport/scientific-equality suite: **23/23 PASS**
- H3 V03 seal verification after later work: PASS

Intermediate development failures were fixed before freeze and must not be described as final product failures.

---

# 20. Research Incidents / Lessons — Do Not Repeat

## INC-SR-01 — Development risk score under-sensitive
Cause:
- available dev proxies lacked cheap independent error signal and downstream consequences.

Correct response:
- add proper signal acquisition and confirmatory evaluation.

Incorrect response:
- post-hoc lower threshold on same 18 pages.

## INC-SR-02 — Critical version token washed out by edit similarity
Cause:
- averaging text similarity could hide a one-token critical mutation.

Fix:
- critical-token set disagreement hardened.

## INC-CONF-01 — V01 HF path 404
Cause:
- annotation basename path != actual `images/...` tree path.

Classification:
- transport only.

Fix:
- V02 full-tree cursor pagination + unique basename resolution.

## INC-RUNPOD-01 — old qualification flow refused
Message:
`spent qualification smoke input is absent`

Meaning:
- old recovery-specific qualification contract is not the current confirmatory runner.

Correct response:
- new confirmatory-specific controller with equivalent secure lifecycle.

Incorrect response:
- bypass old guard or recreate “spent” evidence.

## INC-ONTOLOGY-TS-01
Cause:
- Set spread incompatible with target.

Fix:
- target-compatible construction.
Final typecheck passes.

---

# 21. RunPod / GPU Rules for the Next Worker

GPU is authorized for research, but evidence integrity has priority.

Do not launch GPU until:
- V02 frozen hashes verified;
- 192-input inventory verified;
- native lane complete;
- inference manifests built;
- exact model/runtime identities resolved;
- GT confirmed absent from inference environment;
- cleanup/watchdog path exists.

Provider lifecycle must record:
- pre-run inventory if applicable;
- create/provision receipt;
- runtime identity;
- exact GPU identity;
- model artifact identity;
- inference outputs;
- input manifest hash;
- timestamps;
- billing;
- cleanup;
- provider absence/orphan audit.

Never:
- print API keys;
- put key values in repo;
- copy secrets to endpoint environment unnecessarily;
- leave paid pods alive after failure.

---

# 22. Research Direction After the Current Confirmatory

Do not start these before closing `SEM-RISK-CONF-02` unless parallel work cannot contaminate it.

## Priority 1 — Finish Semantic Risk prospective confirmatory
Highest priority.

## Priority 2 — Preservation Contract real-output E2E
Use actual parser outputs and compiled facts, not only synthetic unit structures.

Measure:
- date corruption detection;
- quantity corruption;
- version/ID corruption;
- table cell detachment;
- cross-version source mismatch;
- repair locality.

## Priority 3 — Specialist routing by failure class
Build explicit mapping such as:
- formula specialist;
- table specialist;
- reading-order/layout specialist;
- text-omission specialist;
- native extraction peer.

Do not use “strong model” as a monolithic concept.

## Priority 4 — Parser Arena / replaceable backend plane
Make parser selection replaceable and receipt-bound.

Potential candidates:
- PaddleOCR-VL
- MinerU
- DeepSeek-OCR-2
- OvisOCR2
- Docling candidate
- future source-native adapters

Promotion requires benchmark + license/runtime identity.

## Priority 5 — Verified Ontology Evolution empirical evidence
Current contract exists.
Add data showing:
- accepted proposal quality;
- rejected unsafe change examples;
- backward compatibility;
- downstream retrieval/QA utility.

## Priority 6 — Graph projection empirical evidence
Show:
- deterministic rebuild;
- projection hash stability;
- source-world version binding;
- no canonical mutation from graph store.

## Priority 7 — Family B robustness expansion
Move from declared Wikipedia public revisions to other revision ecosystems.

---

# 23. Paper Research Questions / Hypotheses

Suggested final formulation:

## RQ1 / H1 — Safe selective recompilation
Can typed change channels reduce recompilation while remaining semantically equivalent to a full rebuild?

Evidence status:
**Strong / PROVEN on declared H3 projection.**

## RQ2 / H2 — Semantic-risk routing
Can cheap independent disagreement + consequence-aware risk selectively identify pages where specialist verification is worthwhile?

Evidence status:
**FROZEN PROSPECTIVE CONFIRMATORY — inference/evaluation pending.**

## RQ3 / H3 — Semantic preservation
Can an explicit evidence contract detect critical semantic corruption and localize repair before candidate promotion?

Evidence status:
**IMPLEMENTED, strong tests; real-output scientific E2E still needed.**

## RQ4 / H4 — Verified ontology evolution
Can ontology change be admitted through evidence/compatibility/impact gates without allowing an LLM or graph runtime to mutate canonical truth?

Evidence status:
**IMPLEMENTED contract; empirical utility/regression study pending.**

---

# 24. Suggested Paper Structure

## Abstract
Problem:
document ingestion systems either rebuild too much or silently trust parser/model output.

Method:
Verified Knowledge Compiler with typed change channels, selective recompilation, semantic-risk routing, and evidence preservation.

Results:
- H3 selective recompilation equivalence/work avoided;
- Semantic Risk confirmatory results once complete;
- preservation detection/locality results once complete.

## 1. Introduction
- knowledge bases change continuously;
- RAG pipelines often treat parsing + chunking as disposable preprocessing;
- errors and change provenance propagate downstream;
- need verified compilation.

## 2. Problem Formulation
Define:
- source version;
- canonical IR;
- knowledge unit;
- dependency graph;
- change channel;
- candidate world;
- promoted world;
- semantic damage;
- evidence preservation.

## 3. System Architecture
Pipeline:
source -> parser arena -> canonical IR -> semantic diff -> dependency closure -> candidate compile -> preservation verification -> promotion -> derived graph/retrieval projections.

## 4. Typed Change Channels
Formalize:
- locator
- metadata
- semantic
- structural
- unresolved identity

Explain why evidence movement is not automatically semantic change.

## 5. Selective Recompilation
Algorithm and complexity.
Equivalence oracle/full rebuild comparison.

## 6. Semantic Risk and Parser Verification
10-axis risk vector.
Cheap peer/repeat instability.
Specialist routing.

## 7. Semantic Preservation Contract
Evidence attachment and critical tokens.
Fail-closed repair locality.

## 8. Experiments
- H3 public revision
- Semantic Risk confirmatory
- Preservation E2E
- robustness/ablation

## 9. Results
Safety first, then work avoided/cost/latency.

## 10. Discussion
- unresolved identity as abstention;
- born-digital vs scanned;
- model specialization;
- ontology/graph boundaries.

## 11. Limitations
Explicit scope limits.

## 12. Related Work
Incremental computation, document AI, RAG ingestion, semantic diff, knowledge graphs, ontology evolution, provenance.

## 13. Conclusion

---

# 25. Figures and Tables Needed

## Figure 1 — Verified Knowledge Compiler architecture
Show full truth boundary and promotion gate.

## Figure 2 — Typed change channels
Example where evidence location changes but semantic unit is unchanged.

## Figure 3 — Selective recompilation dependency closure
Full rebuild vs selective rebuild.

## Figure 4 — Semantic Risk routing
Primary -> cheap peer / instability -> risk decomposition -> specialist or accept.

## Figure 5 — Semantic Preservation Contract
Fact -> evidence refs -> critical tokens -> PASS/quarantine/local repair.

## Figure 6 — Canonical truth vs derived graph projection
Canonical IR at center; Neo4j/FalkorDB/Graphiti as rebuildable projections.

## Table 1 — H3 Family B
Include:
- pairs
- equivalence
- stale
- unresolved
- rebuild fraction
- work avoided

## Table 2 — Semantic Risk confirmatory
Policies × damage × critical loss × escalation × latency × GPU/cost.

## Table 3 — Failure-class specialist comparison
Formula/table/text/order etc.

## Table 4 — Preservation contract fault injection
Fault class × detection × repair scope.

## Table 5 — Ablations
Remove:
- critical-token hard signal;
- cheap peer;
- downstream consequence;
- structural criticality.

---

# 26. Claims That Are Currently Safe

Safe now:

- TAVONEL has a typed change-channel implementation separating evidence movement from semantic change.
- On the frozen 12-pair public-revision experiment, selective recompilation matched full rebuild for 12/12 pairs with stale-left-behind = 0.
- Mean work avoided in that experiment was 85.32%.
- Semantic Risk, Preservation Contract, Product receipt binding, ontology governance, and graph projection contracts are implemented and tested.
- The 18-page Semantic Risk calibration is development-only and identified under-sensitive available proxies.
- A new 128-page prospective Semantic Risk cohort is frozen, with V02 inputs successfully acquired without GT and without GPU use.

---

# 27. Claims That Are NOT Yet Safe

Do not claim:

- Semantic Risk routing has already been confirmatorily proven.
- The current threshold is validated.
- 85.32% work avoidance generalizes to all corpora.
- MinerU is universally stronger than Paddle.
- A graph database is canonical truth.
- Docling is integrated/promoted.
- Ontology evolution improves downstream QA unless measured.
- Preservation Contract has been validated at production scale.
- the paper is complete.
- GPU confirmatory inference has already run.
- V01 HTTP failure was a model/scientific failure.

---

# 28. Final Definition of Done

The research program should not be called “paper complete” until all of the following are satisfied.

## A. Semantic Risk confirmatory closed
- V02 integrity verified
- native lane complete
- Paddle inference complete
- MinerU/specialist inference complete
- all outputs frozen before GT
- evaluator run once
- preregistered gate adjudicated
- cost/latency/GPU receipts complete
- provider cleanup verified

## B. Preservation scientific E2E
- realistic parser outputs
- critical fault injection
- detection metrics
- repair-locality metrics
- no stale candidate promotion

## C. Family B robustness
At least one non-Wikipedia production-shaped revision source, preferably multiple.

## D. Ontology/graph empirical appendix or follow-up
If retained as paper claims:
- empirical validation required.

## E. Reproducibility package
- exact Git commits/worktree snapshot
- model revisions
- dataset revisions
- input manifests
- SHA-256s
- scripts
- environment/runtime identity
- raw immutable receipts
- final tables generated from receipts, not hand-entered values

## F. Manuscript
- figures
- tables
- methods
- limitations
- related work
- threat-to-validity section
- appendix/protocols

## G. Hostile review
Run an adversarial review asking:
- Did any holdout leak?
- Was any threshold changed after result?
- Was a transport amendment mislabeled?
- Was a development result presented as confirmatory?
- Is every headline number derivable from immutable receipts?
- Can the graph mutate truth?
- Can an LLM mutate ontology?
- Can a PASS receipt from another job promote this candidate?
- Can unresolved identity silently force-match?

Only after this should “final paper ready” be declared.

---

# 29. Next Worker — First 60 Minutes

Do these first, in order.

1. Read this handoff fully.
2. Open project constitution / agent rules.
3. Inspect both isolated worktrees with `git status`.
4. Confirm no one modified the frozen experiment after this handoff.
5. Re-run H3 V03 seal verification.
6. Inspect `SEM-RISK-CONF-02`:
   - protocol
   - selection manifest
   - transport amendment
   - acquisition receipt
   - corpus counts
7. Confirm:
   - 192 files
   - Lane A 64 images + 64 PDFs
   - Lane B 64 images
   - GT absent
8. Run `run_lane_a_native.py`.
9. Freeze/hash native outputs.
10. Run `build_inference_manifests.py`.
11. Build the confirmatory-specific secure RunPod controller.
12. Dry-run/preflight the controller.
13. Only then launch GPU inference.

Do not spend the first session rethinking the research direction unless frozen evidence exposes a real defect.

---

# 30. Practical Search Anchors for the Next Worker

Core concepts/symbols to search:

- `SemanticRiskFeatures`
- `SemanticRiskAssessment`
- `assess_semantic_risk`
- `select_verification_parsers`
- `semantic_preservation`
- `PeerSemanticRiskSignals`
- `critical_token`
- `EVIDENCE_MOVED`
- `changed_logical_ids`
- `identity_unresolved`
- `run_lane_a_native`
- `evaluate_confirmatory`
- `SEM-RISK-CONF-02`

Product:
- `productCoreCompileEnvelope`
- `canPersistCandidate`
- `verifiedOntologyEvolution`
- `graphProjectionContract`

H3:
- `H3-B-CURRENT-CORE-PUBLIC-REVISION-03`
- `verify_seal`

RunPod:
- `infra/runpod/v6`
- `paddleocr_vl_stage2.py`
- `mineru_stage2.py`
- `runpod_qualification.py` — reference lifecycle only; do not reuse blindly for current confirmatory.

---

# 31. Bottom-Line Handoff State

At this handoff:

### Closed / strongest
- Family B H3 public-revision selective recompilation: **PROVEN on declared scope**
- H3 V03 frozen evidence: **intact**
- Product Preservation/receipt binding: **implemented/tested**
- Verified Ontology Evolution contract: **implemented/tested**
- Derived graph projection contract: **implemented/tested**
- Product tests/typecheck: **green**

### Frozen and ready to execute
- `SEM-RISK-CONF-02`
- 128-page prospective cohort
- 18 development pages excluded
- 192 GT-free inputs acquired successfully
- GPU not yet used

### Immediate unfinished work
- Lane A native execution
- inference manifests
- confirmatory-specific RunPod controller
- Paddle/MinerU inference
- freeze outputs
- GT evaluation
- preregistered result adjudication

### After that
- Preservation real-output E2E
- Family B non-Wikipedia robustness
- ontology/graph empirical validation if used as major paper claims
- manuscript/figures/tables/reproducibility/hostile review

**The next worker should continue execution from this exact boundary, not restart the research program.**
