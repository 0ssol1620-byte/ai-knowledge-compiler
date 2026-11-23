# ADR-012: The router against v5 Phase 6 — what exists, what the evidence supports, the shadow step

- Status: **Proposed — decision record, no code.** Nothing here enables, routes, runs a model or
  changes a customer output. The incumbent page path stays authoritative.
- Date: 2026-11-23
- Work order: WO-RTR-0 (`D:/CodexProjects/v34-lanes/workorders/router-mcp-20261123.md:23-61`), lane
  `codex/v34-rtr-0`, base `codex/v34-core-int` 783d8d0703878fcd805afb7fd136b6aae694aeb3.
- Founder direction (2026-11-23, verbatim): "그럼 모델라우터 완료하고 적용해야지. MCP도 완료해서 적용해야지."
  Lead decision (4) under delegation: no switch-on without the ladder (`LEDGER.md:1581`).
- Sibling record, **pending**: ADR-011 (WO-E-ARN-1, branch `codex/v34-arn-1`, commit ba9f9de, under
  review) decides go/stop for the frozen S4 recipe. This record does not repeat or pre-empt that
  decision; it covers the router as a whole.
- Receipts: `D:/CodexProjects/v34-lanes/receipts/WO-RTR-0/` (`commands.txt`, `arith.py`,
  `arith.out.json`, `pr72.json`, `pr76.json`).
- Inputs read and nothing else: router and caller source; the v5 masterplan
  (sha256 `35e6bcec…6b19b7`, equal to the constitution's pin); the intake register
  (sha256 `ddcab571…3242f` at this base); `LEDGER.md`; `receipts/WO-E-CORE-0/`; the S4 recipe
  (`8b03c773…d31991`) and the S4 aggregate file `S4/s4.json/s4.json` (`5a84a13a…7d3f`); PR #72's head
  `0b163d86` by `git show` (read-only); Foundation `fnd-int` 379db63e source, read-only. **Not
  opened:** anything under `D:/CodexProjects/v34-lanes/corpus/`, any gold, record, manifest, raw page
  or census output. Production was not contacted.

## Decision in one paragraph

The router is not finished and is not in production. Its code exists in two Core lineages; the one
on this base is called by `services/api` and `workers/cpu-document`, neither of which is in the live
Core V2 bundle. The evidence supports exactly what production already does — native text where a
page carries it, the incumbent reader otherwise — plus one measured recipe on two strata that no
production page can be recognised as belonging to. The next step is therefore not a routing change:
it is a **zero-authority production shadow** that writes a per-page decision trace from the
evidence table below, internally, in the founder's workspace only, with the incumbent untouched.
It needs no Core release. Running two readers in production is a founder decision (spend and
weight licences) and is not part of this step.

## 1. Inventory

Status vocabulary: `docs/audit/V4_MIGRATION_MATRIX.md:22-30`. Row 8 of that matrix classifies
"legacy routing — `packages/parallel-runtime/.../routing.py`, `packages/router/`" as
KEEP LEGACY → REPLACE, **PARTIAL**, "v4 shadow router, 0→5→25→50→100 rollout"
(`V4_MIGRATION_MATRIX.md:77`).

"Live source" below means AKC `main` 6b3a27bf, from which the live Core V2 bundle reproduces
(`receipts/WO-E-CORE-0/LINEAGE.md:28`). Same-file comparison: `git rev-parse <commit>:<path>` on both
sides (`commands.txt` §2). **None of `akc_router` is in the live bundle:** the staging script
vendors only `akc_cir`, `akc_domain_packs`, `akc_product_core`
(`git show 6b3a27bf:infra/product-core/vercel/stage_release.py`, lines 17-21), and
`grep -c akc_router` over both recorded release manifests returns 0
(`receipts/WO-E-CORE-0/release-manifest.6b3a27bf.json`, sha256 `181a2743…667f`, and
`…783d8d0.json`). Whether `services/api` or `workers/cpu-document` run anywhere in production is
"not established" (`LINEAGE.md:81`).

### 1a. `packages/router/src/akc_router` at this base

| module | decides | product callers (this base) | tests | status | in live source 6b3a27bf |
|---|---|---|---|---|---|
| `engine.py` | first route per page (`select_first_route`, :140) and the escalation step after a quality signal (`decide_escalation`, :240); a decision whose route is not in `ready_routes` becomes `UNRESOLVED` (`_require_ready_route`, :105) | `services/api/src/akc_api/services.py:467, 3513, 3846, 4237`; `workers/cpu-document/src/akc_worker_document/worker.py:2073, 2111`; `benchmark/evaluators/system_algorithms.py:29`; `benchmark/screen/native_census.py:22` | `tests/unit/test_router_extended.py`, `tests/unit/test_router_preflight.py`, `packages/router/tests/test_complementarity.py` | IMPLEMENTED_NOT_PROVEN — PR #72's report: "production routes 84% of pages to NATIVE and that route is unmeasured on the Arena" (`0b163d86:docs/audit/V5_ROUTER_PHASE6_REPORT_2026-09-18.md:92`) | byte-identical |
| `preflight.py` | `native_candidate` (:158), `classify_page` (:208), `preflight_difficulty`; since WO-D07-5 a metric named in `unknown_metrics` is skipped, not read as its sentinel | worker.py:2078-2079; `native_census.py:105` | `packages/router/tests/test_native_census_routing.py` (6 tests, :71-213) | IMPLEMENTED_NOT_PROVEN; every cut-off in it (e.g. 100 chars, reading order 0.80 at :160-166) is uncalibrated | **differs**: WO-D07-5 commit 86dbfc8 is on this base only |
| `complementarity.py` | the second reader for a cross-check, per element, from 120 measured rescue rows (`_MEASURED_ROWS` :102, `select_cross_check_peer` :274); no measured peer → no second read, no default partner | engine.py:63-102 only | `test_complementarity.py` (re-reads both artifacts and fails on drift) | IMPLEMENTED_NOT_PROVEN: rows are a frozen record of the 2026-09-06 OmniDocBench study; routing on them is unmeasured. Peers `OVIS_VL`, `INFINITY_FLASH` are not servable (`models.py:44-49`), so every decision that would pick one falls closed | byte-identical |
| `models.py` | route, profile, flag, context and decision contracts; all feature flags default `False` (:58-67) | every caller above | via the above | IMPLEMENTED_NOT_PROVEN | byte-identical |
| `estimation.py` | collection cost/duration estimate; `build_zero_authority_learned_router_shadow` (:575) builds a record with `authority: "zero"` and `promotion_eligible: False` (:250-302) | `services/api/src/akc_api/collection_api.py:4024` | `tests/unit/test_collection_estimation.py:235` | IMPLEMENTED_NOT_PROVEN | byte-identical |
| `expected_verified_cost.py` | min expected verified cost under a critical-failure bound | none outside tests and an audit list (`tools/audit_folynta_v1_masterplan.py:28`) | `test_verified_cost_router.py:16` | IMPLEMENTED_NOT_PROVEN, unused by the product path | byte-identical |
| `champion_matrix.py`, `calibration.py` | one promoted champion per page family; expected calibration error | none outside tests | `test_verified_cost_router.py:6, 25` | IMPLEMENTED_NOT_PROVEN, unused | byte-identical |
| `research.py` | Beta-binomial stop rule, schedule Monte Carlo, risk-constrained candidate | none outside tests | `test_research.py` (3 tests) | IMPLEMENTED_NOT_PROVEN, unused | byte-identical |
| `providers.py` | parser/knowledge provider protocol and registry | no caller found by `git grep` | — | IMPLEMENTED_NOT_PROVEN, unused | byte-identical |

The router suites pass at this base: `pytest packages/router/tests tests/unit/test_router_preflight.py
tests/unit/test_router_extended.py` → **60 passed** (`commands.txt` §3). Passing says the code does
what its author intended; it measures no routing outcome.

### 1b. The pieces the work order names

| piece | where it is | state |
|---|---|---|
| Shadow hook `ROUTER_V2_SHADOW` | **only** on PR #72's head: `git show 0b163d86:packages/router/src/akc_router/engine.py`, lines 100-163 — env read per call (`== "1"`), process-local sink, every failure swallowed and logged without page content, the legacy decision returned regardless | not on this base (`git grep ROUTER_V2_SHADOW` → no match; case-insensitive, only the policy string `router-v2-shadow` in a test fixture, `services/api/tests/test_parallel_runtime_store.py:180`), not in 6b3a27bf. PR #72's own report: "SOFTWARE_DONE / NOT_RUNNING … no production host installs a sink because the live product (Core v2 on Vercel) has no model choice to shadow" (`0b163d86:docs/audit/V5_ROUTER_PHASE6_REPORT_2026-09-18.md:96`) |
| Expected verified cost | `expected_verified_cost.py` above; PR #72 adds a planner that uses it | unused by the product path |
| Complementarity matrix | `complementarity.py` above; artifacts `research/model_arena_20260903/reports/complementarity_20260906/` bound by sha256 (:58-63) | in base and live source; its candidates (`ovisocr2`, `infinity_parser2_flash`) are not the S4 members, and its measure (page edit distance on OmniDocBench) is not S4's (critical-field exactness on SEC pages) — the two are not same-condition with each other |
| Native census routing (WO-D07-5) | fix in `preflight.py` (86dbfc8) + `benchmark/screen/native_census.py` | the census command passes `unknown_metrics` (:105). **The worker does not**: worker.py:2056 sets the sentinel `handwriting_probability=0.5` and worker.py:2078 calls `classify_page(router_metrics)` with no `unknown_metrics`, so preflight.py:212 labels such a page `HANDWRITTEN`. The hand-off to the worker was left to "hand-off H1" (`workorders/core-intake-parsers.md:628`) and has not happened |
| Second-reader lineage, PR #76 | `gh pr view 76` → **CLOSED, not merged** (closed 2026-09-27T06:29:14Z; base `main`, head `agent/router-second-reader-20260923`, head oid d6f77b8e) | its content reached `main` anyway: commits 72264b4 ("router: name the second reader…") and ba497b9 are ancestors of 6b3a27bf (`git merge-base --is-ancestor`, `commands.txt` §4) |
| Router v2 + governed authority, PR #72 | `gh pr view 72` → **OPEN** since 2026-09-18, base `main`, head `agent/router-phase6-20260918`, head oid 0b163d86 | not an ancestor of 6b3a27bf. Carries the planner, `RoutingAuthorityRouter`, `ProductionRouteOutcome` (migration renumbered `0041_arena_persistence`), ROD-v1 and its own `ADR-007-router-execution-authority.md` (a second ADR-007; this base already has two ADR-007 files) |
| Second lineage in parallel-runtime | `packages/parallel-runtime/src/akc_parallel_runtime/routing.py`: `AdaptiveRouter` (:259, objective = a weighted sum of estimated pass rate, numeric exactness, cost and latency, :304-330), `evaluate_router_promotion` (:232, `minimum_shadow_samples=100`) | caller `services/scheduler/src/akc_scheduler/autonomous_v6_pipeline.py:793`; not in the live bundle (same stage script) |
| Not this router | Foundation `nextjs/lib/adaptive-router.ts` + `router-activation-gate.ts` (fnd-int 379db63e) select a **retrieval** runtime (`lib/retrieval-runtime-config.ts:448`) behind an activation contract requiring arena / oracle / familyHoldout / shadow / canary receipts (`router-activation-gate.ts:5, 47`) | named here only so it is not confused with page routing |

### 1c. What production actually does with a page

The page decision in production is not made by any router module. In the Foundation OCR worker
source (`fnd-int/workers/foundation-ocr-gpu/app.py`, 379db63e), `read_pages` (:585-608) takes the
page's embedded text when pdfium yields any with at least one text rectangle (`native_page_region`,
:463-486, region id `native-pNNNN`) and otherwise rasterises the page for RapidOCR
(`OCR_ENGINE_RELEASE = "rapidocr-3.9.2-ko-pass-nocls-v3-selftest"`, :70; region ids
`ocr-pNNNN-lNNNNN`, :439). "A page with usable native text is never rasterized" (:605). Which build
of which worker serves production, and at which digest, was not read (no production contact).
Foundation accepts the result only if its keys are exactly the v2/v3 set
(`nextjs/lib/collection-compile-run.ts:261-269`), then dispatches Core
(`dispatchProductCoreV2`, :451).

## 2. v5 Phases 4–6: exit criteria

Quoted from `docs/north-star/TAVONEL_MASTERPLAN_v5.0.md` (v4 not restated).

| phase | exit, verbatim | met? |
|---|---|---|
| 4 — Arena harness + prompt calibration (:1779-1787) | "**Exit:** 50-case smoke and 200-page screening complete; no test leakage." | **Partly.** 200-page screening: met in count by d10-screen-v1 — holdout 450 pages (225 source + 225 synthetic `scan_poor`) scored once (`LEDGER.md:1325, 1458`; `s4.json` `parts.R.pages`/`parts.H.pages` = 225/225). No leakage, for that screen: holdout disjoint from dev by company and source hash (`LEDGER.md:1325`), one holdout access-log line (`s4.json` `inputs.access_log.lines` = 1), and a 372-page sensitivity subset with no shared filing prefix (`s4.json` `sensitivity_subset`). **Not met:** no receipt read here records a 50-case smoke (the register names a "A2a 30-page smoke", `TECHNOLOGY_INTAKE_REGISTER.yaml:646`); the phase's "100-page calibration corpus" (:1781) does not exist — PR #72 lists "prompt-calibration corpus" as founder-gated (`pr72.json` body); for the 2026-09-03 public Arena, contamination (ARENA-10, :1894) cannot be excluded |
| 5 — Arena v1, 1,000 pages (:1789-1799) | "**Exit:** DPM/Oracle matrix exists; survivors chosen by evidence." | **Partly.** Oracle matrix: ROD-v1, 1,557 OmniDocBench pages × 9 paths, family-level split 920/320/317 — on PR #72's unmerged head only (`0b163d86:research/router_oracle_dataset_20260918/`, REPORT.md sha256 `6aec20ac…9d02`, RESULTS.json `26037108…01ff`). Survivors by evidence: the d10 screen chose C3 → C7 by the preregistered 5H rule (`LEDGER.md:1407, 1458`). **Not met:** the phase's corpus — 400 public, 300 DART/SEC, 200 Failure Zoo, 100 Clean Control (:1791-1794) — was not assembled; d10 is SEC pages plus synthetic degradation; DART/Korean, Failure Zoo, Clean Control and real scans are unmeasured |
| 6 — Execution planner + shadow router (:1801-1805) | "Arena oracle를 이용해 deterministic bootstrap policy를 만든다. **Exit:** 100% shadow on named corpus/production-safe sample; no active routing yet." | **Not met.** "No active routing": true — §1c. Bootstrap policy: built offline and negative (ROD-v1, §3 row N). 100% shadow: no shadow has run anywhere in production; the only hook is on unmerged PR #72 and has no sink. Definition of Done item 21, "Shadow Router의 oracle regret/trust violation/cost report가 있다" (:2141), exists only as the offline ROD-v1 report, not as a shadow report |

## 3. What the evidence supports, and nothing more

Each row cites its receipt. Candidates by registry id only. No threshold here is calibrated. Every
figure is either copied from a receipt or arithmetic on the S4 aggregates, shown in
`receipts/WO-RTR-0/arith.out.json` (script `arith.py` checks the aggregate file's sha256 and stops on
a mismatch or a missing key).

| row | page class (as measured) | route the evidence supports | receipt | what it does **not** support |
|---|---|---|---|---|
| RT-1 | page with embedded native text | **native text, as the incumbent already does** | production rule: `foundation-ocr-gpu/app.py:585-608` (behaviour, not evidence); classification only: d10 native census, 33 dev pages (`LEDGER.md:1325`, receipt `7d63ab5d…7174`, inside the corpus directory, **not opened**) | quality of native text on structured content. The one native arm that was scored is negative: olmOCR-Bench, 1,403 pages, mean per-JSONL pass rate 0.194 including baseline, "Math buckets pass 0 rules; the table bucket passes 1/1,022 … Native text availability is therefore insufficient evidence to accept structured content" (`0b163d86:research/router_native_arm_20260909/README.md:26-29`, sha256 `d987e1ef…c6b9`). No other reader was compared on these pages under the same condition → **the incumbent stays**; no alternative is supported |
| RT-2a | S4 stratum **R**: SEC filing source pages, read as images (`receipts/d10-screen-v1/S4/RUNBOOK-S4.md:23`) | frozen recipe `sha256:2efdbac7…0234`: primary `mineru_vlm` (C3), peer `ovisocr3` (C7), a field is held (escalated) on disagreement or no value (`S4/recipe.json`) — **for this stratum, in the evaluation, pending ADR-011** | `s4.json` `parts.R`: 225 pages, 2,330 critical fields; escalated 81/2,330 = 0.0348; accepted exact 2,249/2,249 (Wilson 95% 0.9983–1.0); false accept 0/2,249 (0–0.0017); C3 alone exact 2,250/2,330 = 0.9657; C0 (`mineru` baseline) 1,925/2,330 = 0.8262; derived cost 0.007837 USD per accepted page (× 1,000 = 7.84; stated price × measured latency, **not billed**, one C7 page without cost) | production: in production these pages are born-digital and go native (RT-1); the recipe was compared with C0, not with native text and not with the incumbent RapidOCR. The incumbent production reader is not C0 (`workorders/core-loop-20261123.md:164-165`) |
| RT-2b | S4 stratum **H**: the same pages synthetically degraded (`scan_poor`: 100 dpi, JPEG 35, blur, noise, skew ≤ 2.5°; `recipe.json` `degradation`) — not real scans | same recipe, same pending status | `s4.json` `parts.H`: 225 pages, 2,330 fields; escalated 293/2,330 = 0.1258; accepted exact 1,958/2,037 = 0.9612 (0.9519–0.9688); **false accept 79/2,037 = 0.0388 (0.0312–0.0481)**; recipe yield 1,958/2,330 = 0.8403; C3 alone 2,044/2,330 = 0.8773; C0 386/2,330 = 0.1657; derived 0.011035 USD per accepted page (× 1,000 = 11.04, not billed) | real scans, photos, Korean, any non-SEC document. No production page is observable as "synthetically degraded", so **no production page can be assigned to this row**. A held field must never be accepted; 79 wrong values were accepted under the recipe on this stratum |
| RT-3 | every other class: real scans, photos, handwriting, Korean/DART, tables and formulas as such, office formats, charts | **no same-condition evidence: the incumbent stays** | absence: §2 (Phase 5 corpus not assembled); register `not_cleared` "Korean … UNVERIFIED" for C7 (`TECHNOLOGY_INTAKE_REGISTER.yaml:847`) | — |
| N | per-class model selection (ROD-v1) | **negative — do not route per page class on this evidence** | "Even with a perfect page classifier, choosing a model per page class does not beat the best single model on this corpus" (`0b163d86:docs/audit/V5_ROUTER_PHASE6_REPORT_2026-09-18.md:72`, sha256 `bf22208d…491e`); production-bound set +0.0011 quality, 95% CI −0.0069 to +0.0093 at 1.43× cost (:56); all nine paths −0.0022, CI −0.0093 to +0.0023 against always-`ovisocr2` (:69); oracle headroom 0.013 on both (:70). Page-class features there are ground truth, so these are upper bounds | — |
| N2 | a scalar blind quality score as a router input | **not used, by rule** | constitution "Never route on a scalar blind quality score"; the campaign published it as not supported (`docs/evidence/FOLYNTA_CAMPAIGN_RESULTS.md:242`) | the existing code still has two scalar gates the table does **not** adopt: `decide_escalation` accepts at `signal.score >= 0.82` (engine.py:355-374, ADR-005's gate score) and `AdaptiveRouter._objective` is a weighted scalar (`routing.py:304-330`). Neither is used by §5 |

S4 failure classes kept apart as recorded: C7 one `operational` (`http_520`), C0 five `model_answer`
(`empty_output`), C3 none (`s4.json` `failures`). The aggregate file is `publishable: false`; nothing
above is a public claim. S4's billed total for all three readers' pods was USD 4.7667506
(`s4.json` `billed`, RunPod billing read by the lead) and is not mixed into the derived figures.

## 4. Legal holds

From `docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml` at this base. No claim analysis and no opinion on any
third party's rights are given; nothing is described as legally reviewed, cleared or free to operate.

| entry | recorded instruction (quoted) | design choice that follows it |
|---|---|---|
| `red: tech_ibm_sequential_inference` (:43-58), status `DESIGN_AROUND`, touches "Adaptive Economic Router; Patent Family A" | "The broad sequential-inference shape: first model → QoS comparison → conditional execution of a second model. Avoid expressions that read onto it." | §3 executes no second model for any production class. §5's shadow executes **no model at all**: it records which evidence row a page falls under. Any stage that would run a second reader (WO-E-ARN-2…4) goes through the FTO-1A engineering conformance check the lead kept after the founder's FTO-1 answer (`LEDGER.md:1498`) before it opens. The existing `decide_escalation` path from a failed quality gate to another route (engine.py:391-419) is not extended, enabled or described by this record |
| `binding_now` IP & Research (:95-106) | Family A must stay clear of the sequential-inference shape (:97); the IP track "recommended not claiming parser routing, cost-aware routing, multi-engine ensembling" (:101-106) | this record makes no novelty claim and proposes no public copy about routing; the trace is internal |
| `proposed_not_started` (:143) | "RouteLLM / AdaParse baseline adapters — Arena only" | nothing from either enters §3 or §5 |
| `model_mineru_vlm` (C3, :635-691), ORANGE, `EVALUATION_ONLY` | weights: "No LICENSE file in the weights repository … Evaluation use rests on that metadata"; `not_cleared`: "Production use (weights licence is metadata only); redistribution of the weights; redistribution of the C3 image" | C3 appears only as a measured candidate (RT-2a/b); no production route names it; question F-1 below |
| `model_ovisocr3` (C7, :816-847), GREEN, `EVALUATION_ONLY` | `not_cleared`: "Production use; Korean (no mention on the card, UNVERIFIED)." | same; RT-3 keeps Korean on the incumbent |
| FTO-1 (:152-159) and the founder's answer (`LEDGER.md:1498`) | answer: the held items do not wait for counsel; "every RED entry stays `DESIGN_AROUND` … a weight without a commercial licence still does not ship" | §5 needs no weight; nothing in it ships a model |

## 5. The production shadow step

**What it is.** A per-page decision trace written internally, beside the incumbent, from the §3
table held as versioned data. The incumbent stays authoritative and the customer's output is
byte-identical with the trace on or off.

**Why not `select_first_route` from `packages/router`.** It needs a `PageMetrics` of 25 fields
(`preflight.py:69-94`); the production path computes none of the visual ones, and filling them with
sentinels is exactly the defect WO-D07-5 removed from the census and the worker still has (§1b).
The production-observable class is what the OCR result already says per page. Options considered:
(a) port `akc_router` into the Core V2 bundle and compute there — Core receives text and regions,
not page images, and it would add a vendored package to a release (stage script :17-21); (b) add a
field to the OCR result body — Foundation refuses any unknown key on v3 (`collection-compile-run.ts:267-268`),
so every compile would fail closed; (c) **derive the class in Foundation from the regions it has
already verified, and write the trace there** — chosen: no new model, no new image, no Core change.

| item | decision |
|---|---|
| Hook | Foundation `nextjs/lib/collection-compile-run.ts`, after the OCR bodies pass the binding checks (:255-291) and independent of `dispatchProductCoreV2` (:451). The trace is computed from `regions` per document; its result is never read by the compile |
| Class | from region ids the worker writes: `native-p…` → `native_text`; `ocr-p…` → `raster_text`; a page listed without a region → `no_text`; any other id → `unclassifiable` (recorded, never defaulted to a class) |
| Route | the §3 row the class falls under. Today every observable class maps to "incumbent stays" (RT-1 or RT-3); RT-2a/b can never be selected because their strata are not observable. The trace therefore agrees with the incumbent by construction — what it proves is the hook, storage, flag, separation and rollback, and what it measures is the production class mix |
| Flag and cohort | `TAVONEL_ROUTER_SHADOW_ENABLED=true` and `TAVONEL_ROUTER_SHADOW_COHORT=<founder workspace id>` (same shape as the remote-MCP cohort, `LEDGER.md:1581`). Unset, malformed or a list containing `*` → off. Off means zero writes, not a degraded trace |
| Stored | an internal PostgreSQL table, RLS enabled with no policy (service role only): workspace, compile run, document, page index, input sha256, reader revision and binding sha256 (v3), class, incumbent route, evidence row id, sha256 of the table version, agreement flag, cost estimate, outcome class + reason code, recognition-conflict count. **No text, no bbox, no region content.** Key = sha256(run, document, page, table version); insert-if-absent, so a redelivered compile writes nothing twice |
| Never stored or exposed | no public DTO, API route, client bundle or export carries a trace field; a test asserts it. The existing `learned_router_shadow` in `CollectionEstimateResponse` (`services/api/.../collection_schemas.py:423`) is not reused as a model for this |
| Cost estimate | only a figure a §3 receipt supplies for that row; RT-1/RT-3 have none → `null` with reason `COST_UNMEASURED`. Nothing is estimated by hand |
| Operational vs semantic | separate fields, never merged. Operational: the OCR body could not be read or bound (`OCR_BINDING_INVALID`, :256-257, :269), a worker or transport error, a timeout. Semantic: a readable body with a `no_text` raster page, a recognition conflict, a v1 body refused as `OCR_REGIONS_REQUIRED`. A Core compile failure is recorded at run level and never attributed to a page route |
| Shadow failure | a trace write that fails is counted and logged with a reason code (no page content) and does not fail or delay the compile — the shadow has zero authority, as PR #72's hook (engine.py lines 120-163 at `0b163d86`) |
| Sample | 100% of the pages of every compile in the cohort (the Phase 6 exit's "100% shadow"). Review once at least **100 compiles** are traced — the count the existing code already uses (`routing.py:233`, `estimation.py:592, 599`); a count, not a calibrated threshold or a statistical bound. The report states n per class |
| Rollback | unset `TAVONEL_ROUTER_SHADOW_ENABLED` and redeploy; rows stay (internal, append-only); dropping the table is a destructive action and needs a recorded backup first |
| Core release | **neither.** It is Foundation code. Decision E-16 keeps K1 = live source + WO-D22-3 only (`LEDGER.md:1502`); adding anything to K1 would break its manifest gate. If a later step moves the computation into Core, that is a new vendored package and its own release after K1 |

**Founder questions (not decided here; no price invented):**

- **F-1 Weight licences.** Production use of C3 (`mineru_vlm`) is not cleared — its weights
  repository has no LICENSE file, only card metadata `apache-2.0` (register :660-668, :691); if served
  through MinerU, MinerU's own licence governs the code axis (:654-659). C7 (`ovisocr3`) carries an
  Apache-2.0 LICENSE file but production use is listed `not_cleared` (:847). Code, weights, image and
  hosted-API terms are four separate licences.
- **F-2 Recurring GPU spend.** Serving the recipe means both readers on every page that would take it.
  Known: S4 derived cost 0.007837 (R) and 0.011035 (H) USD per accepted page, lower bounds from stated
  price × measured latency; C3 p50 latency 32.7 s (R) / 32.5 s (H) per page and C7 4.8 s / 5.0 s
  (`arith.out.json`); S4 billed USD 4.77 for three readers over 450 pages including pod overhead.
  Unknown: the production page volume and class mix (which the shadow measures), the serving shape and
  its price.

## 6. Work orders implied

| id | title | size | write scope | depends on | gate it climbs | owner |
|---|---|---|---|---|---|---|
| WO-RTR-1 | Evidence table as data + pure page classifier | S | Foundation: new `nextjs/lib/router-shadow-trace.ts`, its test, new `nextjs/lib/router-evidence-table.v1.json` | this ADR accepted | compatibility contract | lane |
| WO-RTR-2 | Shadow wiring: internal table, flag + cohort, hook | M | Foundation: one migration (slot from the lead), the hook lines in `collection-compile-run.ts`, a new store module, tests (flag off = zero writes and byte-identical output; unknown region id; write failure; redelivery; no trace field in any public DTO) | WO-RTR-1 | shadow (code) | lane |
| WO-RTR-3 | Shadow on in the founder's workspace | S | production env (two names) on the next production build; post-check; rollback drill | WO-RTR-2 merged after independent review | shadow (production) | lead under delegation; the cohort is the founder's workspace |
| WO-RTR-4 | Shadow report after ≥ 100 traced compiles | S | `receipts/WO-RTR-4/` (aggregates of the internal table only) | WO-RTR-3 | Phase 6 exit evidence; input to F-2 | lane |
| WO-RTR-5 | Core router lineage reconciliation | M | Core: decide PR #72 (merge or close, ROD-v1 into tracked evidence); the two ADR-007 files; the worker's `classify_page` without `unknown_metrics` (worker.py:2078); `learned_router_shadow` in a response DTO (collection_schemas.py:423); `_processing_mode` defaulting an unknown mode to `BALANCED` (`routing_runtime.py:106-111`) | none | compatibility contract | lane + lead |
| F-RTR-1 | Weight licences (F-1), recurring GPU spend (F-2) and the FTO-1A conformance check for any two-reader stage | — | — | ADR-011 outcome; WO-RTR-4 for the volume | precondition of WO-E-ARN-2…4 (benchmark on the product path, canary) | **founder** |

## Consequences

- The router stays at "not in production". After WO-RTR-3 it is in production as a shadow with zero
  authority; that is the Phase 6 exit's first half, not routing.
- No customer output, Core release, model, image or spend changes with this record.
- Two router lineages and two ADR-007 files remain until WO-RTR-5; until then "the router" means the
  base's `akc_router` and nothing on PR #72 is relied on except as a cited receipt.
