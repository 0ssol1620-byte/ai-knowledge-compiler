# Compile dispatch fairness

The durable compile dispatcher enforces a cluster-wide binary semaphore for
each tenant on PostgreSQL. A burst from one tenant can occupy at most one
dispatch replica at a time, while replicas remain available to other tenants.
This is an admission-control invariant in addition to the existing
per-job exactly-once lock; it does not weaken outbox leases, attempt limits, or
dead-letter handling.

## Selection and lock lifecycle

Each poll ranks due internal dispatch events within their tenant and scans only
the oldest event per tenant. The scan is bounded by
`AKC_DISPATCH_FAIRNESS_SCAN_TENANTS` (64 by default), so a large backlog cannot
fill the entire candidate set with rows from one tenant.

For each candidate, the worker:

1. derives a signed 64-bit tenant key with the versioned
   `akc-dsp-lock-v1` BLAKE2 namespace;
2. calls PostgreSQL `pg_try_advisory_lock` for that tenant;
3. if admitted, acquires a separately namespaced per-job advisory lock;
4. commits the short outbox lease transaction and holds both session locks
   through the complete bounded compile attempt and outbox acknowledgement;
5. releases job then tenant in reverse order.

Tenant and job inputs use separate hash domains. A theoretical 64-bit collision
therefore fails conservatively as temporary contention; it cannot grant excess
capacity or cross tenant data boundaries.

If the tenant semaphore is already held, the event is moved forward by
`AKC_DISPATCH_TENANT_BUSY_DELAY_SECONDS` (one second by default), its attempt
counter is unchanged, and the worker continues scanning candidates from other
tenants. Fairness deferral alone can never exhaust retries or create a
dead-letter item.

All success, adapter error, timeout, and task-cancellation paths execute the
same release block. If explicit unlock fails or is itself cancelled, the
connection is invalidated; PostgreSQL then releases every session advisory lock
when the physical session closes. A worker must never return an ambiguous
connection to the pool.

SQLite remains a serialized, nonproduction test adapter. Production startup
already rejects SQLite, so cross-replica fairness is never claimed for it.

## Telemetry and alerts

`akc_dispatch_tenant_busy_deferrals_total` counts semaphore deferrals. It has no
labels: tenant IDs, job IDs, source names, and document metadata must never be
added to this metric.

Alert on a sustained increase together with queue age, not on an isolated
increment. A rising deferral rate with stable queue age means admission control
is working. Rising deferrals and rising oldest-job age require checking worker
capacity, attempt duration, stuck providers, and tenant burst shape.

Do not increase tenant concurrency by bypassing the advisory lock. If higher
per-tenant parallelism becomes a product requirement, add an explicitly
reviewed, plan-aware multi-slot semaphore and load evidence. The default binary
semaphore is the safe noisy-neighbor boundary.

## Verification

The PostgreSQL CI gate performs all of these checks on disposable PostgreSQL
17:

- the ranked `FOR UPDATE OF outbox_events SKIP LOCKED` claim executes;
- two runtime connections cannot acquire the same tenant semaphore;
- the second connection can acquire a different tenant simultaneously;
- tenant and job lock namespaces do not collide;
- explicit unlock makes capacity reusable;
- closing a worker connection releases a still-held tenant lock.

The scheduler regression suite also verifies one-candidate-per-tenant scans,
busy deferral without attempt consumption, next-tenant admission, unlabeled
metrics, and cancellation during unlock followed by successful admission of a
waiter.

