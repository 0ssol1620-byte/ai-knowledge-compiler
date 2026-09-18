# ADR-007: Router execution authority

Status: Accepted for implementation; production canary remains disabled.

## Context

The deterministic document router and the v6 adaptive router previously had no
single execution-authority boundary. The v6 scheduler called `AdaptiveRouter`
directly, so bootstrap quality estimates could select a dispatched provider
without a calibrated policy receipt. A `production_canary` request field also
affected speculation without proving that the policy, cohort, and rollback
evidence were authorized.

The v5 masterplan requires deterministic fallback, zero-authority shadow
evaluation, a low-risk canary backed by signed evidence, and an immediate
rollback pointer. A calculated route is evidence only; it is not execution
authority.

## Decision

`RoutingAuthorityRouter` is the sole scheduler routing authority. It always
computes the deterministic registry-order route first. Its mode has these
semantics:

- `deterministic`: dispatch the deterministic route. This is the default when
  both router flags are absent or false.
- `shadow`: persist the adaptive decision as a counterfactual and dispatch only
  the deterministic route.
- `canary`: dispatch the adaptive route only when the canary flag is enabled,
  the job is explicitly in the canary cohort, the request is low risk, and an
  injected authority evaluator authenticates a complete calibrated policy and
  its eligible, unexpired, signed canary receipt. Every missing, malformed,
  expired, mismatched, or rejected input resolves to deterministic mode.

The adaptive implementation must also declare the SHA-256 of the calibrated
policy it consumes. A valid receipt for some other policy cannot authorize the
bootstrap router or an unbound adaptive implementation. Production mode always
uses the repository authority evaluator and the concrete Ed25519 canary
verifier with explicitly pinned public keys; structural test doubles cannot
replace either trust boundary.

The durable `record_route` boundary receives an `AuthorizedRouteDecision`,
which contains the one executable decision, optional counterfactual, requested
and effective modes, reason codes, and policy/receipt SHA-256 identities. After
execution reaches a terminal result, the production adapter combines this
selection envelope with trust, latency, actual cost, permission, and route
receipt evidence and calls `record_production_route_outcome`. Arena cases and
production customer outcomes remain separate data domains.

`akc_scheduler.production_route_outcomes` is the reusable terminal adapter. It
binds the tenant, workspace, collection, processing job, shard, selected recipe,
worker, model revision, runtime image, and model registry identity before it
uses the API repository. The current tree has no concrete
`AutonomousV6RuntimePort`; a future provider runtime must call this adapter from
its terminal settlement or rejection transaction. The protocol declaration and
test runtime are not production integration.

`V5_ROUTER_SHADOW` and `V5_ROUTER_CANARY` both default to false. Production
provider submission requires `PersistedRouterRuntimeFlagResolver`, which reads
a fresh tenant-scoped database snapshot at every submit boundary. Missing or
untrusted live resolution resolves to deterministic mode. Turning off the
canary flag therefore changes the next primary, challenger, hedge, retry, or
recovery submission without changing provider configuration or model registry
state.

Each routed shard persists the SHA-256 of its full authority envelope. The
pre-dispatch check refreshes the durable route record when either selected IDs
or that authority digest changes, so an unchanged route cannot retain stale
canary or shadow authority. `submit_attempt` also receives the freshly checked
authority envelope and must bind it atomically to the provider submission
receipt, closing the await window between route recording and dispatch.

The separate `services/core-v3` reference compiler exposes a candidate-only
`receipt.routeOutcome` contract. With no trusted outcome provider it emits an
explicit unavailable receipt bound to the authenticated request and labels its
tenant, workspace, and collection values as caller references rather than API
UUIDs. An observed receipt requires exact API UUID identities, terminal
accounting, and evidence digests. HTTP responses from these v3 reference routes
also carry an optional domain-separated HMAC over the exact response bytes,
request id, and request input digest. Legacy callers may ignore the headers;
consumers must verify them before presenting an observed receipt as trusted.

This does not integrate the production Product Core v2 `/v2/compile` path. That
implementation is outside this checkout, uses a different envelope, and has no
verified mapping to the autonomous scheduler's UUID namespace. The v3 reference
server has no production caller or trusted route-outcome provider in this tree,
so its emitted receipt remains unavailable by default.

## Compatibility and rollback

Normal routing is native-tier first, then keeps configured registry order and health, identity,
capability, language, privacy, and provider-transfer filters. A deterministic
secondary candidate remains available for verified recovery and straggler
hedging, but is never dispatched speculatively by the routing authority.

Rollback consists of disabling both routing flags. No endpoint, secret, model
registry, or candidate promotion is changed by this decision. Persisted route
outcomes retain the prior authority evidence for audit.

## Evidence status

Unit and scheduler tests prove default-off behavior, shadow non-dispatch,
canary fail-closed behavior, low-risk scoping, outcome persistence, and flag
rollback. They do not prove calibration, canary safety, production deployment,
or improved quality/cost/latency. Those claims require the frozen Arena corpus,
family-disjoint splits, repeated measured runs, authenticated promotion receipt,
live canary receipts, and production rollback observations required by the v5
gates.
