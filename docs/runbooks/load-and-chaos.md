# Load and chaos drills

Use only dedicated nonproduction environments and synthetic data. The harnesses
under `tests/load` and `tests/chaos` contain explicit remote/target
confirmations, bounded concurrency/outage limits, and cleanup behavior.

For remote runs, use the protected `staging-drill` GitHub environment. Set its
`AKC_STAGING_DRILL_ALLOWED_ORIGINS` variable to a comma-separated list of exact
nonproduction HTTPS origins. The workflow requires an exact allowlist match,
the explicit confirmation string, and dedicated disposable credentials. It
records the operator-declared target revision separately from the harness
revision and marks that target revision as unverified; bind independent
deployment evidence before using the result at a gate.

## Load sequence

1. Run read-only health load and confirm zero dropped iterations.
2. Run one authenticated journey: upload -> security completion -> analysis ->
   estimate -> compile -> SSE -> export -> delete.
3. Increase VUs and iterations in steps while watching API latency/errors,
   database connections, queue age/fairness, first block/page time, SSE
   reconnect, credits, storage, CPU/GPU estimates, and deletion.
4. Test mixed small/large synthetic jobs so a large job cannot starve smaller
   jobs. Real large-document and GPU tests remain externally gated.

Archive k6 JSON, target revision/configuration, environment shape, data
manifest, thresholds, alerts, and cleanup receipts. A result without those
bindings is diagnostic, not release evidence.

### Dispatch fairness drill

Queue a sustained synthetic burst for tenant A and interleave bounded jobs for
tenant B. With at least two dispatch replicas, verify that:

- tenant A has at most one active compile attempt;
- tenant B starts before tenant A's backlog drains;
- A's deferred events do not increment `attempts` or enter the DLQ;
- `akc_dispatch_tenant_busy_deferrals_total` increases without tenant labels;
- oldest-job age returns to baseline after the burst.

Repeat with an adapter timeout, task cancellation, and disposable worker
termination. The replacement replica must acquire the released tenant
semaphore and complete the next event exactly once. Capture the configuration,
queue timestamps, terminal events, attempt counts, metric samples, and worker
session lifecycle. The repository's PostgreSQL CI gate proves the lock
primitive; staging load evidence is still required before a release claim.

## Chaos sequence

Start with the recoverable local Compose pause drill. Staging drills may cover
database failover/restart, queue restart, provider slowdown/outage, partial
upload, SSE disconnect/replay, OOM escalation, duplicate completion, clock
skew, and DLQ recovery only after an environment-specific reviewed plan exists.

Every injection needs:

- exact target and blast radius;
- abort condition and independent recovery control;
- maximum duration;
- expected health/alert/user behavior;
- idempotency, credit, event, provenance, and deletion reconciliation;
- cleanup and evidence owner.

Never inject failure into production under this repository's generic harness.
Unchanged state, missing telemetry, or an unobserved expected failure fails the
drill rather than being interpreted as resilience.
