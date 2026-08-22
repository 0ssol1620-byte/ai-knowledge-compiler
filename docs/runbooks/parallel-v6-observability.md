# Parallel v6 observability runbook

## Scope and invariants

This runbook covers the v6 parallel shard, provider-attempt, L0-L6 validation,
dual worker-health, selective recovery, continuity merge, acceptance, and
exactly-once billing signals.

Prometheus is an operational projection, not durable evidence. Database rows,
append-only collection events, provider receipts, and credit-ledger entries are
authoritative. Metrics are emitted only after the corresponding transaction
commits. A rollback or idempotent replay must not increment an outcome counter.

Every label is a closed, low-cardinality enum. Never add tenant, collection,
document, job, shard, attempt, worker, model revision, runtime digest, artifact,
hash, URI, filename, reason detail, or document content as a label. Use the
tenant-scoped admin APIs and durable event ledger for individual investigation.

## Signal map

| Concern | Series | Bounded labels |
| --- | --- | --- |
| Shard terminal outcome | `akc_parallel_shards_terminal_total` | `status` |
| Attempt terminal outcome | `akc_parallel_attempts_terminal_total` | `status` |
| Validator outcome | `akc_parallel_validations_total` | `level`, `outcome` |
| Independent worker health | `akc_parallel_worker_health_transitions_total` | `projection`, `previous`, `current` |
| Selective recovery | `akc_parallel_recovery_terminal_total` | `level`, `outcome` |
| Continuity merge | `akc_parallel_continuity_outcomes_total` | `outcome` |
| Accepted projection | `akc_parallel_accepted_blocks_total` | `final_state`, `billing` |
| Explicitly unbillable work | `akc_parallel_nonbillable_attempts_total` | `disposition` |
| Duplicate charge prevention | `akc_parallel_duplicate_credit_suppressions_total` | `reason` |
| Receipt completeness | `akc_parallel_provider_observations_total` | `provider`, `measurement` |
| Queue delay | `akc_parallel_provider_queue_delay_seconds` | `provider` |
| Execution duration | `akc_parallel_provider_execution_duration_seconds` | `provider` |
| Per-invocation cost | `akc_parallel_provider_job_cost_usd` | `provider` |
| Aggregate cost | `akc_parallel_provider_cost_usd_total` | `provider` |
| GPU time | `akc_parallel_provider_gpu_seconds_total` | `provider` |

Provider cost and timing values must be copied from a validated provider
receipt. They are never reconstructed from user credits. Zero is a valid
provider observation; negative, non-finite, or malformed measurements are
discarded.

## Triage order

1. Confirm `/metrics` is scraped and `AKCRequiredTelemetryContractMissing` is
   not firing. Missing telemetry is an instrumentation incident, not evidence
   that the runtime is healthy.
2. Check whether the alert is isolated to one bounded provider or affects all
   providers. Do not introduce a worker or tenant label to refine the query.
3. Query the tenant-scoped admin runtime view for affected durable states, then
   follow collection-event hashes to the attempt, validation, recovery, or
   continuity receipts.
4. Compare provider invocation receipts with the immutable attempt output and
   billing disposition. HTTP success alone is not acceptance.
5. Verify accepted blocks have a matching consume-ledger settlement and that
   retry, hedge, straggler, shadow, unresolved, and quarantined attempts remain
   unbillable. For post-accept semantic impact, require an append-only
   invalidation, one content-bound refund, and a recovery task before treating
   the block as inactive.
6. Drain or quarantine a worker pool only from independent infrastructure and
   semantic-health evidence. A healthy heartbeat does not override semantic
   failure.
7. Preserve the evidence chain and record incident, mitigation, and restoration
   timestamps before clearing the alert.

## Alert-specific response

- **Attempt or validation failure burst:** stop promotion for the affected pool,
  inspect the latest immutable validator revisions, and distinguish provider
  transport failure from semantic failure. Do not retry a terminal attempt in
  place; create a new lineage-bound attempt.
- **Semantic health failure:** quarantine or drain through the normal worker
  state machine, run the pinned canary, and replay impact analysis for attempts
  accepted since the last healthy observation. Confirm the server-discovered
  impact set rather than trusting caller-supplied block IDs, then reconcile
  invalidation/refund/recovery receipts. If the document was already finalized,
  confirm the document and processing job became non-terminal, the terminal
  scheduler checkpoint was removed, and a digest-bound recovery epoch was
  created. Infrastructure health cannot clear this alert.
- **Recovery or continuity unresolved:** retain the affected scope as
  unresolved or quarantined. Never concatenate shard outputs or widen recovery
  scope without the deterministic planner and evidence-bound merge policy.
- **Duplicate credit suppressed:** confirm only one consume ledger row owns the
  settlement key. Suppression means the guard worked, but repeated events can
  indicate a replay storm or competing winners and require investigation.
- **Provider queue or execution latency:** verify provider status and bounded
  pool capacity, then apply existing backpressure, hedge, or straggler policy.
  Do not bypass validation to recover throughput.
- **Provider cost:** reconcile the provider receipts and billing history. Lower
  concurrency or drain safely if spend is runaway; never reduce the exact-three
  public benchmark repeat count or relabel incomplete evidence as a completed
  run.

## Deployment verification

Before enabling v6 traffic:

1. render `/metrics` and confirm every series in the signal map exists;
2. verify a committed fixture increments each expected counter exactly once;
3. verify a rolled-back fixture and an idempotent replay do not increment it;
4. submit malformed label candidates and confirm only the `other` label appears;
5. submit negative and non-finite provider measurements and confirm histogram
   counts and cost totals do not change;
6. load the Prometheus rules with `promtool check rules` in the deployment
   environment;
7. exercise alert delivery in staging and attach the Alertmanager receipt to
   release evidence.

Initial thresholds in `infra/monitoring/prometheus-rules.yaml` are operational
defaults. Version environment-specific thresholds only after route-specific
baselines exist; do not present them as contractual SLOs.
