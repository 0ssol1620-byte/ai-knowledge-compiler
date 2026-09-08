# Router v2 contracts (WP-R2) and planner (WP-R3/R5/R6)

Status: **PROPOSED** contracts, `IMPLEMENTED_NOT_PROVEN` code
(`docs/audit/V4_MIGRATION_MATRIX.md` vocabulary). Nothing here is promoted, and
nothing here is calibrated: `CalibrationTable.calibrated` is `False` across the
repository, every threshold and cost in the planner is an author's prediction,
and the code says so at runtime rather than only in this document.

Source: `TAVONEL_FINAL_RESEARCH_ADAPTIVE_ROUTER_INFORMATION_LOSS_MASTER_BLUEPRINT_2026-09-08.md`
§16, §18, §20–§24, §27, §55, §63, §65 WP-R2, §66, Appendix D/G.

WP-R2 added **contracts only**. WP-R3, WP-R5 and WP-R6 added code that uses
them: preflight estimation, a portfolio, a planner, a dependency builder, an
in-process scheduler and an observability record. `akc_cir.*` is still
untouched, and **the live first-route and escalation policy is still
`engine.py`** — the planner runs only behind `ROUTER_V2_SHADOW=1` with zero
decision authority. Nothing here is evidence that any route, model or latency
figure is achievable; the numbers a plan carries are *predictions written by
whoever built the planner*, not measurements.

## What was added

| Contract | Schema | Python |
|---|---|---|
| RiskVector (§16) | `packages/contracts/schemas/risk-vector.schema.json` | `akc_router.risk` |
| DocumentExecutionPlan (§18) | `document-execution-plan.schema.json` | `akc_router.execution_plan` |
| PageExecutionPlan (§18) | `page-execution-plan.schema.json` | `akc_router.execution_plan` |
| RegionExecutionPlan (§18) | `region-execution-plan.schema.json` | `akc_router.execution_plan` |
| RouterReplayRecord (Appendix D) | `router-replay-record.schema.json` | `akc_router.execution_plan` |
| §21 speculation table | — | `akc_router.speculation` |
| §27 candidate-set filter | — | `akc_router.data_policy` |

Schemas follow the repository's static-schema convention
(`$id: https://schemas.aiknowledgecompiler.dev/<name>/1.0.0`, draft 2020-12,
`additionalProperties: false`, camelCase wire names). Python models are
`akc_cir.ContractModel` (frozen, `extra="forbid"`, camelCase aliases) like the
existing `RouteDecision`, so the same dump-and-validate test shape applies.

## Invariants the types enforce

- **An unknown signal can never be read as confidence 1.0 (§11).** `RiskSignal`
  refuses a value or confidence when `unknown` is set, refuses any source but
  `unavailable`, and refuses to be marked calibrated. The only supported reader,
  `RiskVector.confidence()`, returns `0.0` for unknown, unstated and absent
  signals alike. Every unknown signal must also appear in `unknown_features`.
- **A plan's route set is closed.** The primary route must be one of the
  candidate routes, speculative routes must be a subset of them, and a terminal
  isolation state (`unresolved`, `quarantine`) is never an executable route.
- **Fail closed.** `DocumentExecutionPlan.is_executable` is false when any
  `unresolved_constraints` entry exists or no wave was produced. Predicted p95
  cannot fall below p50, and predicted verified cost cannot exceed the budget.
- **Operational and semantic failure stay apart (§24).** `OperationalFailure`
  and `SemanticFailure` are separate enum families; `DynamicReplanEvent` accepts
  exactly one of them, and the §24 trigger→action table decides which responses
  are legal — an infrastructure timeout cannot justify a semantic recovery.
- **The replay record cannot admit hidden truth.**
  `hidden_evaluation_visible_to_runtime` is `Literal[False]` in Python and a
  `const: false` in the schema, so a leaking replay is unrepresentable.
- **Data policy filters candidates before planning (§27).**
  `filter_candidate_routes` removes `EXTERNAL_ROUTES` under private mode,
  private processing, absent external-API consent, or a detected secret, and
  reports the reason codes. An empty permitted set is a fail-closed condition
  for the caller, not a licence to relax the policy.
- **The public projection carries no internal field (§55).**
  `INTERNAL_ONLY_PLAN_FIELDS` names the wire fields that must never reach a
  public DTO (risk vector, candidate/primary/speculative routes, verification
  and escalation policy, budgets, predicted verified cost, revisions, digests,
  batch group, priority). `PublicRouterStatus` is a separate type — not the plan
  with a filter — carrying only an Appendix G state, its exact customer copy,
  and unit counts.

## §21 speculation policy

`akc_router.speculation` holds the §21 table **as data and nothing else**. There
is no learned policy: §20 puts learned speculation behind shadow mode and §64
behind promotion evidence that does not exist. `speculate()` returns the row for
a named class and raises `UnknownSpeculationClassError` for anything the table
does not name — it never guesses a default.

Lanes are symbolic and there are now ten of them (§25 / program §6): `native`,
`authority`, `fast_visual`, `peer_visual`, `table_specialist`,
`formula_specialist`, `chart_specialist`, `degraded_scan_specialist`,
`external_adjudicator`, `human_review`. The single `specialist_vlm` is gone; the
§21 rows that named it now name the chart or degraded-scan specialist, and no
other row changed. No row names a model or a route, because §21 requires the
concrete primary to be bound from the tenant's current ready routes. Nothing in
the table asserts that a given model is qualified for a lane.

**Peers are not all optional.** When a row's verification is `AUTHORITY_MATCH`
or `HUMAN_REVIEW` the peer *is* the verification mechanism, and the planner will
not drop it for cost. A `PEER_AGREEMENT` peer is also reachable by escalation,
so pre-launching it is the optional spend §9 governs.

## C-09 — unmeasured visual signals (PRODUCTION_BEHAVIOUR_CHANGE)

`PageMetrics.handwriting_probability`, `rotation_degrees`, `skew_degrees`,
`blur_score`, `contrast_score` and `small_text_score` are now `float | None`
(required, nullable). `None` means **no estimator ran**.

**The defect.** The CPU worker had no visual estimator and persisted `0.5` as a
"neutral" sentinel. `classify_page` returns `HANDWRITTEN` at `>= 0.50`, so every
natively parsed page in production carried `technical_class = handwritten`, and
`select_first_route`'s HPD gate (`handwriting_probability < 0.2`) could never
open. The threshold was never wrong; the sentinel was a fabricated observation.

**What changed.**

- `classify_page` and `preflight_difficulty` branch on `None`: an unmeasured
  term is *absent from the sum*, not scored zero. `unmeasured_visual_signals()`
  names which ones, so "difficulty 0.24" and "difficulty 0.24 with four
  unknowns" stay distinguishable.
- The HPD gate now requires an *observed* handwriting value. Unknown does not
  open the cheap lane — fail closed (§11).
- The worker writes `null` and keeps the field in `unknown_visual_metrics`. It
  no longer drops `contrast_score` from that list when a preprocessing transform
  exists: the transform manifest records whether bounded autocontrast was
  *applied*, which is not a contrast score.

**Compatibility.** `technical_class` is persisted into the page `analysis`
payload with `router_metrics` beside it. No consumer in this repository reads
either back — searched across Python, TypeScript, SQL and the JSON schemas;
there is no `page-metrics` schema, and `PageMetrics` is constructed in exactly
one place. So no migration is required, but two facts hold:

1. **Historical rows are wrong and stay wrong.** Every page analysed before this
   change carries `technical_class = handwritten` and four `0.5` metrics. They
   are not rewritten — evidence is never overwritten — so any comparison across
   the change must partition on it.
2. **This is a production behaviour change and takes the compatibility ladder.**
   Shadow first: run the new classification beside the old and compare the class
   distribution before it becomes authoritative. The TypeScript `PageMetrics`
   interface now types the six fields `| null`, so a consumer added later cannot
   quietly ignore the state.

## Units and naming

- `predicted_p50` / `predicted_p95` are predicted wall-clock **milliseconds**.
- `cost_budget` and `predicted_verified_cost` are expected verified cost (§42),
  not raw inference cost, in the same credit unit as `RouteDecision`.
- `feature_manifest_sha256` uses the repo's `sha256:<64 hex>` form.
- Region `crop_geometry` is page-space pixels; nothing here fabricates a bbox.

## Tests

`tests/unit/test_router_v2_contracts.py` — round trip through each schema
(with and without `exclude_none`), plus the failure paths: bad manifest digest,
negative or zero budget, p95 below p50, cost above budget, primary route outside
the candidate set, terminal route as primary, unknown speculation class, an
external route under private policy and after secret detection, an unknown
signal declared confident, an undeclared unknown signal, both or neither replan
trigger family, an operational trigger routed to a semantic action, and a public
projection that would leak an internal field.

## The §57 chain — what executes, what is contract only

`source -> early preflight -> RiskVector -> policy-filtered candidates ->
adaptive plan -> dependency DAG -> queue/batch -> selective speculation ->
inference -> loss detection -> selective recovery -> independent verification ->
verified merge/refuse -> exact evidence`.

| Stage | State | Where |
|---|---|---|
| source intake | executes (production) | `workers/cpu-document` |
| early preflight — native lane | executes | `source_preflight.inspect_pdf_native`; Office families are a capability table, not a reader call |
| early preflight — visual lane | executes | `source_preflight.estimate_page_visual` (Pillow only); **not wired into the worker** |
| RiskVector | executes | `risk_adapter.page_metrics_to_risk_vector`, all 22 signals, 8 page-local blind spots unknown by construction |
| policy-filtered candidates | executes | `data_policy.filter_candidate_routes`, called by the planner before any scoring |
| adaptive plan | executes (shadow only) | `planner.plan_document` |
| dependency DAG | executes | `dependency.build_dependency_edges`; inputs are a contract, no reader populates them yet |
| queue / batch | executes (in-process) | `scheduler.Scheduler`; not wired to a worker pool |
| selective speculation | executes | `planner._speculative_routes` over the §21 table |
| inference | executes (production, legacy route) | existing worker + providers |
| loss detection | contract only | `akc_cir.critical_tokens` exists; WP-R7 wiring is lane A3's |
| selective recovery | contract only | `EscalationPolicy.REGION_RECOVERY` is emitted; WP-R8 is not built |
| independent verification | contract only | `VerificationPolicy` is emitted and never enforced; WP-R9 is not built |
| verified merge / refuse | partial | the planner refuses (returns no plan) but nothing merges yet |
| exact evidence | contract only | `observability.RouterExecutionRecord` exists; nothing writes it |
| offline evidence / fresh holdout / shadow / canary / rollback | shadow hook only | `engine.set_router_v2_shadow_sink`; replay is lane A2 |

## Not done here

Loss detector (WP-R7), selective recovery (WP-R8), independent verifier (WP-R9),
the replay harness itself (WP-R10, lane A2), and wiring the lane-B visual
estimator into the CPU worker — that is a second production behaviour change and
needs its own shadow. No schema here is wired into an API surface or a migration,
and no threshold in the planner has been calibrated against any corpus.
