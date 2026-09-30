# Synthetic journal storage qualification

Base: `20a6ae06c7221f88a9a033b9f5923464516ef280`, isolated
`codex/core-replay-integrity`. No live state, credentials or deployment changes.

Implemented explicit Python maintenance APIs in `journal_maintenance.py`:

- `compact_completed`: deterministic batches of 1-1000 jobs; validate all selected
  accepted-work/candidate bindings before atomically deleting redundant completed
  fragments. Retain accepted requests, immutable conflict bindings and replay
  candidates. Never select pending jobs. Repeated cleanup is idempotent.
- `reset_pending_fragments`: require exact tenant/workspace/idempotency, work
  digest and release, validate accepted request, refuse completed candidates.
  Delete derived fragments only so the normal compiler recomputes them from the
  original accepted request. Corrupt accepted work is never reset.
- `copy_verified_journal`: SQLite consistent online backup or offline restore to
  an exclusively created NEW path. Validate database integrity, foreign keys,
  accepted request/scope, fragment bindings/content and candidate receipts.
  Existing destinations are never overwritten; failed copies are removed. A
  bounded copy deadline defaults to 30 seconds. No unverified copy is accepted.
- Runtime connections use SQLite `mode=rw`; loss of an open service's journal
  returns 503 without silently recreating the database and forgetting replay.
  Initial service construction remains the explicit creation boundary.

13 maintenance tests and 17 prior journal tests passed (30 total). Tests cover
bounded deterministic cleanup, incomplete-state preservation, batch rollback on
corruption, backup/restore of completed and pending jobs, existing-path refusal,
orphan/corrupt snapshot rejection, explicit fragment repair, corrupt accepted-work
refusal, lost live-file refusal and copy timeout cleanup. Synthetic temporary
SQLite files only. Ruff and strict mypy check the new maintenance code.

These helpers are not exposed through an HTTP/admin endpoint or automatically
scheduled. Fragment deletion is logical space reclamation, not secure erasure or
physical VACUUM. Whole-request TTL and tenant deletion need an approved retention
contract with tombstone/replay-expiry semantics; deleting an idempotency row would
silently permit key reuse, so this slice deliberately preserves it. No encryption
keys were introduced. A restore cannot recover acknowledged work newer than its
snapshot: deployment must be quiesced and that recovery-point gap reconciled by
the owning control plane before activation. No live restore was performed.

## Distributed fencing assessment

The actual adapters are `infra/product-core/Dockerfile` (Cloud Run container) and
`infra/product-core/vercel` (serverless fallback). Both expose candidate-only
compilation; neither defines shared durable storage or owns Foundation's ACTIVE
pointer. SQLite locks operate within one shared local file; independent replicas
or ephemeral instances cannot coordinate through them. Existing Core scheduler
models have lease tokens/expiry for other task families, but those leases are not
authority over this Product-Core journal or Foundation promotion.

The next distributed slice must first choose one shared transactional journal
backend and its deployment owner. Acquisition must increment a persisted fencing
generation on the immutable scoped job; every fragment and candidate commit must
compare owner, generation and unexpired lease atomically. An expired worker must
fail to publish after takeover, even if its extraction later finishes. Foundation
must independently enforce its promotion lease/CAS and ACL checks. Backup restore
must invalidate old generations and reconcile post-snapshot acknowledged work.
Do not route a distributed backend through local SQLite or add a token check that
cannot protect the shared commit. No speculative lease library or distributed
claim was added without that storage/ownership decision.
