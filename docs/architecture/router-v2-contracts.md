# Router v2 contracts (WP-R2)

Status: **PROPOSED** contracts, `IMPLEMENTED_NOT_PROVEN` code
(`docs/audit/V4_MIGRATION_MATRIX.md` vocabulary).

Source: `TAVONEL_FINAL_RESEARCH_ADAPTIVE_ROUTER_INFORMATION_LOSS_MASTER_BLUEPRINT_2026-09-08.md`
§16, §18, §20–§24, §27, §55, §63, §65 WP-R2, §66, Appendix D/G.

This work package adds **contracts only**. It plans nothing, schedules nothing,
executes nothing, and measures nothing. `engine.py` and `akc_cir.*` are
untouched; the live first-route and escalation policy is still `engine.py`.
Nothing here is evidence that any route, model or latency figure is achievable —
the numbers a plan carries are *predictions written by whoever builds the
planner* (WP-R6), not measurements.

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

Lanes are symbolic (`native`, `authority`, `fast_visual`, `peer_visual`,
`specialist_vlm`, `human_review`). No row names a model or a route, because §21
requires the concrete primary to be bound from the tenant's current ready
routes. Nothing in the table asserts that a given model is qualified for a lane.

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

## Not done here

Planner (WP-R6), early preflight lanes (WP-R3, §17), portfolio routes (WP-R5),
loss detector (WP-R7), scheduler queues and fairness (§22, §67), replay harness
(WP-R10), and the observability record of §63 beyond the Appendix D shape. No
schema here is wired into an API surface or a migration yet.
