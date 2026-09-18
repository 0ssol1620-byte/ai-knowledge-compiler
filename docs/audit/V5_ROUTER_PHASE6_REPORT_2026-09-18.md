# V5 Router — Phase 6 report (Execution Planner + Shadow Router), 2026-09-18

Status vocabulary follows `docs/audit/V4_MIGRATION_MATRIX.md`. Nothing in this report is a
public claim, a champion promotion or a production activation. The router stays at
**R1 SHADOW (software complete) / R2 CALIBRATED SHADOW (inputs built, gates open)** on the
2026-09-12 blueprint's R0–R5 ladder. Production routing authority remains deterministic;
`V5_ROUTER_SHADOW` and `V5_ROUTER_CANARY` default to false.

## 1. What this phase landed on `agent/router-phase6-20260918`

Branch `agent/router-phase6-20260918` (cut from `main` bd0fb334). Commits: `56df59b` Router v2 lineage
(174 files), `f968e83` governed routing authority lineage (43 files), `c986475` `source_cursors` in the alembic
metadata on every dialect, `359688f` migration-head test no longer pins a revision name, plus this phase's
Router Oracle Dataset and documentation commit. Migration `0038_arena_persistence` was renumbered to
`0041_arena_persistence` (`down_revision = 0040_source_cursor_tenancy`); `tests/unit/test_migration_graph.py`
passes (single head). Excluded on purpose: `services/core-v3` (the service does not exist on `main`),
two research-branch e2e tests, `AGENTS.md`, and the `collection_retrieval_api.py` guard whose target `main`
already removed; `akc_cir.inspection.aggregate_evidence_risk` was not imported because it would modify a
protected core module (the replay feature inlines the equivalent noisy-or).

Verification (Python 3.13, repo `.venv`): targeted routing suites **664 passed**; full default suite
`main` 144 failed / 2,904 passed vs this branch 145 failed / 3,181 passed before `359688f`, with exactly
one branch-only failure, fixed in `359688f` — **zero regressions against `main`, +277 passing tests**.
`ruff check packages services workers benchmark infra` reports 91 findings and `mypy packages services`
64, all in files byte-identical to `main` and untouched here. The 144 shared failures are cross-test
pollution in `services/api/tests` and `services/scheduler/tests` (each module passes alone) and
pre-date this branch. ROD-v1: `research/router_oracle_dataset_20260918/tests` 5 passed; ruff clean.

Two lineages that had lived on unmerged branches since 2026-09-08..12 were brought onto one
branch cut from `main`, without the 161 unrelated research commits they used to sit on:

| lineage | content | origin |
|---|---|---|
| Router v2 (`0b00117`, PRs #56 #58 #59 #62 #63) | contracts (5 JSON schemas), RiskVector preflight with `UNKNOWN`-never-zero visual signals (production defect C-09 fixed), ten execution lanes, planner (Expected Verified Cost, trust floor, zero authority), dependency DAG and in-process scheduler, `ROUTER_V2_SHADOW` zero-authority hook in `akc_router.engine`, WP-R10 offline replay harness and results, Phase A oracle ceiling, grouped-selector and Native-arm negative results, mixed-source holdout pre-registration (unopened) | `agent/router-v2-*`, `feat/router-evidence-execution-20260909`, `codex/router-native-replay-20260910` |
| Governed routing authority (`8c9ee85`) | `RoutingAuthorityRouter` (deterministic / shadow / canary, fail-closed), `CalibratedPolicyArtifact` with family-disjoint split binding and three-repeat receipts, Ed25519 canary receipts, `evaluation.py` (Document Performance Map, allowed oracle, oracle regret, recovery utility), frozen policy loader, `ProductionRouteOutcome` persistence (migration `0038_arena_persistence`), authenticated route-outcome read API, ADR-007 | `codex/router-arena-master-20260912` (local only) |
| Router Oracle Dataset v1 (this phase) | `research/router_oracle_dataset_20260918/`: family-level 60/20/20 split of the spent OmniDocBench surface, bootstrap policy fitted on TRAIN, trust floor selected on CALIBRATION, every arm scored once on HOLDOUT with the §10.3 metrics | new |

## 2. Evidence produced this phase (ROD-v1, $0, no inference)

Source: `research/router_oracle_dataset_20260918/REPORT.md`, `RESULTS.json`, `SPLIT_MANIFEST.json`,
`POLICY_FREEZE.json` (thresholds written before any score was read). Corpus: OmniDocBench pages
from campaign `TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1`; 1,557 of 1,651 pages carry text ground
truth scored by all nine open-source paths; 1,340 document families; split 920 / 320 / 317 pages
(792 / 277 / 271 families). Page-class features are ground-truth attributes, i.e. a **perfect
page classifier**, so every routed arm is an upper bound.

Holdout, 317 pages, permitted set = production-bound routes (`paddleocr_vl_1_6`, `hpd_parsing`):

| arm | mean quality (1 − text edit) | trusted (edit ≤ 0.05) | catastrophic (edit ≥ 0.5) | GPU $/1k pages | p50 s |
|---|---:|---:|---:|---:|---:|
| ORACLE_DIAGNOSTIC (reads truth) | 0.9749 | 0.855 | 0.000 | 1.51 | 4.0 |
| BOOTSTRAP_MCTO (class-conditional, trust floor 0.80) | 0.9630 | 0.792 | 0.003 | 1.74 | 4.0 |
| ALWAYS `hpd_parsing` | 0.9619 | 0.785 | 0.003 | 3.65 | 3.0 |
| ALWAYS `paddleocr_vl_1_6` (current production primary) | 0.9611 | 0.792 | 0.003 | 1.21 | 5.0 |

BOOTSTRAP_MCTO vs best single: +0.0011 quality, 95% cluster-bootstrap CI −0.0069 to +0.0093.
Cost vs always-Paddle: +0.52 $/1k (CI +0.32 to +0.78), 1.43×.

Holdout, permitted set = all nine open-source paths:

| arm | mean quality | trusted | catastrophic | GPU $/1k pages | p50 s |
|---|---:|---:|---:|---:|---:|
| ORACLE_DIAGNOSTIC | 0.9835 | 0.909 | 0.000 | 0.80 | 4.0 |
| ALWAYS `ovisocr2` | 0.9706 | 0.858 | 0.000 | 1.11 | 4.0 |
| BOOTSTRAP_MCTO (trust floor 0.95) | 0.9684 | 0.861 | 0.003 | 1.11 | 4.0 |
| ALWAYS `paddleocr_vl_1_6` | 0.9611 | 0.792 | 0.003 | 1.21 | 5.0 |
| ALWAYS `mineru_vlm` (cheapest) | 0.9551 | 0.779 | 0.016 | 0.74 | 5.0 |

BOOTSTRAP_MCTO vs always-`ovisocr2`: −0.0022 quality, CI −0.0093 to +0.0023; oracle capture ratio −0.17.
Oracle headroom over the best single path is 0.013 quality on both permitted sets.

**Reading.** Even with a perfect page classifier, choosing a model per page class does not beat
the best single model on this corpus. The oracle headroom exists but is spread across paths in a
way the page class does not predict. This agrees with the 2026-09-08 replay (no runtime-visible
arm captured any oracle headroom; PR #58) and the 2026-09-09 grouped-selector result (26 improved,
34 harmed). Masterplan v5 §8.3 applies: *Oracle gain 작음 → Router complexity 재검토*. The router's
value on this evidence is (a) promoting a better champion once it is licensed and qualified,
(b) failure classification and recovery, (c) cost — not per-page model selection.

Cost figures are raw campaign GPU cost (RTX 4090 $0.74/h, A40 $0.49/h, H100 $3.49/h for
`hpd_parsing`) and never sit beside a retail price. `olmocr2` and `unlimited_ocr` have no per-page
OmniDoc rows in the campaign; `opus5_subscription` has an unmeasured cost and is not an egress-permitted
default path; `infinity_parser2_pro` is founder-excluded. All four are recorded, not dropped.

## 3. Router Definition of Done (blueprint 2026-09-12 §13) — status

| # | item | status | evidence / what is missing |
|---|---|---|---|
| 1 | current model portfolio pin | PARTIAL | 12 models pinned by `runtime.json` + `inference_config_sha256`; `container_digest` null for all 13; 0/12 QUALIFIED, 11 CANDIDATE |
| 2 | public benchmark exact-version rerun | NOT_STARTED | requires ARENA PUBLIC V1 (pre-registration, pinned versions, all-page accounting, ≥3 repeats) — paid |
| 3 | private hard-doc holdout | PREREGISTERED_UNOPENED | `research/router_mixed_source_holdout_20260910` (96 units, pre-open preflight passed, unopened) — paid run |
| 4 | native baseline | PARTIAL | Native arm captured on olmOCR (1,178/1,403 observed); no OmniDoc native arm; production routes 84% of pages to NATIVE and that route is unmeasured on the Arena |
| 5 | single-model baselines | DONE (spent corpus) | ROD-v1 ALWAYS-X arms; replay §39 baselines |
| 6 | deterministic router | DONE | `akc_router.engine` (production) + `DeterministicRouter` (scheduler authority) |
| 7 | oracle upper bound | DONE (diagnostic) | ROD-v1 ORACLE_DIAGNOSTIC; Phase A oracle ceiling |
| 8 | shadow decision logging | SOFTWARE_DONE / NOT_RUNNING | `ROUTER_V2_SHADOW` hook (akc_router) and `RoutingAuthorityRouter` shadow mode + `ProductionRouteOutcome` table exist; no production host installs a sink because the live product (Core v2 on Vercel) has no model choice to shadow |
| 9 | calibration | INPUTS_BUILT / NOT_CALIBRATED | ROD-v1 split + trust floor selected on CALIBRATION; `CalibratedPolicyArtifact` cannot be created: it requires three reproducibility runs and a family-disjoint prompt-calibration corpus, neither of which the campaign has |
| 10 | three repeated promotion runs | NOT_STARTED | paid; forecast below |
| 11 | cost/page | DONE (campaign ledger) | per-job seconds × listed pod rate; not a price |
| 12 | p50/p95 latency | DONE (campaign ledger, per job) | queue wait and cold start excluded |
| 13 | route regret | DONE (spent holdout) | ROD-v1 mean regret per arm; replay regret column |
| 14 | escalation recall | NOT_MEASURABLE | the Arena stores whole-page single-model outputs; no escalation arm exists |
| 15 | false escalation | NOT_MEASURABLE | same |
| 16 | downstream AI benchmark | NOT_STARTED | Layer D; founder scope |
| 17 | production canary | NOT_STARTED | blocked on 9, 10, signed canary receipt |
| 18 | rollback | SOFTWARE_DONE | disabling both flags reroutes before the next dispatch (scheduler tests); untested in production |
| 19 | continuous evaluation | NOT_STARTED | |

## 4. What blocks R2 → R3 and what it costs (founder decisions)

Only the founder decides spend, corpus publication and claims. From the campaign ledger
(`research/model_arena_20260903/cost/campaign-cost.json`: $591.02 for 61,839 attempted pages,
54,445 successful, useful-inference share 0.288, idle overhead 0.662):

| gate | what | forecast (FORECAST, from ledger rates) |
|---|---|---|
| R-1 fresh holdout (WP-R11) | open the pre-registered 96-unit mixed-source holdout (`MIXED_SOURCE_HOLDOUT_PROTOCOL.json`) | protocol ceiling `maximum_new_gpu_spend_usd: 20`; pod minimums dominate |
| three repeated runs (DoD 10) | 3 × 5,132 pages × 9 paths | 138,564 pages → ≈ $430 at the useful-inference rate, ≈ $1,505 at the campaign's all-in rate |
| R-2 native arm + per-page latency instrumentation | next campaign design | no GPU cost; engineering |
| prompt-calibration corpus | 100 pages, family-disjoint (V5_ARENA_CORPUS.md §"Prompt calibration") | sourcing decision |
| licence approvals | `ovisocr2` (Apache-2.0, best single on OmniDoc) is not a production route; MinerU is under its own licence | founder / counsel |
| R-3 competitor blind test (WP-R12) | before any "beats X" wording | founder scope |

## 5. Publication rules this phase confirms

- No number above is publishable. The corpus is spent, the features are ground-truth classes,
  and the results are negative for per-class routing.
- When a routed result becomes publishable (fresh holdout, ≥3 repeats, receipts), the public row
  is labelled **TAVONEL** — the routed pipeline's own measured result — with the exact
  configuration disclosed in the methodology. A third-party single model's score is never
  relabelled as TAVONEL. Vendor rows stay `quoted`, never "beaten".
- `$/1k` above is raw GPU cost and never sits beside a retail price.

## 6. Migration-matrix and registry updates in this phase

- `V4_MIGRATION_MATRIX.md` row 8: PARTIAL → SHADOW_SOFTWARE_COMPLETE / NOT_CALIBRATED (see §3).
- `V5_MIGRATION_MATRIX.md`: Document Performance Map and Router Oracle Dataset MISSING → BUILT (spent corpus, v1).
- `docs/ip/V4_DISCLOSURE_REGISTRY.yaml`: Adaptive Economic Router implementation note updated; the
  Router Outcome Dataset rows stay git-ignored (`router_oracle_dataset.jsonl`, sha256 in
  `SPLIT_MANIFEST.json`).
