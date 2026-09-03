# TAVONEL H1 current-repository reconciliation — 2026-08-16

Status: **G0A/G0B critical-path lock complete; implementation promotion remains gated.**

This note reconciles the RAGFlow hardening blueprint with the repository that
exists now. It does not authorize a merge, push, production migration, Canary B,
NOBYPASSRLS disarm, destructive cleanup, or paid infrastructure.

Machine-readable evidence:
`research/experiments/H1-G0-01/receipts/current-repo-reconciliation.json`.

## 1. Current critical-path lineage

The current trust/incremental hardening branch is
`agent/folynta-trust-integration-v1` at short HEAD `46edd908b83d`; it is dirty
and 39 commits ahead of its configured upstream. The relevant independent
worktrees are not interchangeable evidence sources:

| Capability | Worktree / branch | HEAD | Current ruling |
|---|---|---:|---|
| L1 live discovery | `ai-knowledge-compiler-l1` / `agent/tavonel-live-world-slice-l1` | `0d5fbc85645a` | dirty implementation on the old I3 base; verify/reconcile, do not treat as promoted |
| collection plane | `ai-knowledge-compiler-collection-plane-rehearsal` | `59c74e344b4f` | clean authoritative schema/migration reference |
| protected core | `ai-knowledge-compiler-protected-core-promotion` | `576ef4acf978` | clean promotion lineage |
| W1 impact | `ai-knowledge-compiler-w1` | `341eb24a7066` | clean activation plan, not live S4 proof |
| E0 ASK/evidence | `ai-knowledge-compiler-e0` | `3315f6ce4dbe` | clean architecture, not live S4 proof |
| I4 rehearsal | `ai-knowledge-compiler-integration-core` | `76f805d79352` | historical PASS commit identifiable, but worktree is currently dirty |

A historical statement that I4 was clean remains evidence about that historical
checkpoint. The current I4 worktree must not be presented as a clean baseline.

## 2. G0B migration-authority ruling

`migrations/versions/0023_v4_collections.py` is already the authoritative
collection-plane migration. It descends from `0023_trial_ingest` and creates the
collection tables from the complete SQLAlchemy collection model, after which
`0024_production_hybrid_retrieval.py` and the later collection-plane migrations
continue that chain.

The L1 worktree's unstaged `0024_collection_discovery_slice.py` also descends
from `0023_trial_ingest` and independently creates:

- `collections`
- `collection_source_roots`
- `collection_files`
- `collection_events`

This is a competing schema lineage, not an additive migration. The current
production `Collection` model contains lifecycle fields and invariants absent
from the L1 subset, including `status_reason`, `paused_from`, deletion/purge
state, and the full collection status machine. The authoritative
`CollectionEvent` also includes the existing job foreign key and retention/job
indexes. Promoting the L1 migration would therefore create duplicate migration
and table authority.

**Ruling: `BLOCK_L1_MIGRATION_PROMOTION`.**

The L1 behavior is still valuable. Preserve and verify the narrow API/SSE/UI
adapter work, but reapply it on top of the authoritative collection migration
and model. The duplicate L1 migration must be deleted or superseded inside the
L1 lineage before any promotion decision.

## 3. Selective recompilation claim correction

The blueprint's blanket `NOT YET DEMONSTRATED` status is now stale. The current
engineering receipt has 30 documents and 330 mutation cases with:

- 330/330 full-rebuild semantic equivalence;
- zero stale artifacts left behind;
- mean rebuild fraction `0.12626262626262624`;
- no external cost.

This supports **engineering invariant evidence**, not a generalized external
performance claim. The prior 1.0 rebuild fraction came from a different corpus
generation and is not a paired statistical comparison. Independent
preregistration, real revision-family holdout and paired statistical evidence
remain required before broad cost/performance or patent-paper empirical claims.

Use the status:

`ENGINEERING EVIDENCE PASS / EXTERNAL GENERALIZATION WITHHELD`.

## 4. Change-channel contract correction

The current `semantic_diff.py` model is more correct than the blueprint's
mutually-exclusive three-list example. Semantic, locator, visual, structural,
temporal, metadata and graph sensitivity are orthogonal. A logical unit can
change meaning and move evidence in the same revision.

Do not introduce a validator that forbids cross-channel overlap. Treat
`UNRESOLVED`/review requirement as a fail-closed resolution state rather than
forcing every change into exactly one semantic/evidence/unsettled bucket.

## 5. CompilationActionKey correction

A canonical action key must not be built from a sorted bag of input hashes.
Input role and repeated-input order are semantic. Component names must remain
bound to exact revisions; policy, recipe, prompt schema and permission scope are
also action identity.

The collision-safe contract is implemented independently in
`akc_cir.action_key` so it does not overwrite the concurrently edited
`derivation.py`. Persistent CAS integration should consume this contract after
its tests are green. The existing derivation/cache semantics remain intact.

## 6. Updated execution order

1. G0A/G0B — locked for the H1 critical path by this receipt.
2. Verify the new collision-safe CompilationActionKey contract.
3. Reconcile L1 API/SSE/frontend behavior onto the authoritative collection
   schema; do not promote its duplicate migration.
4. Re-run L1 backend, contract and browser E2E evidence on the reconciled
   lineage.
5. Close immutable runtime build → qualification → READY.
6. In parallel where ownership permits, run the independent selective-recompile
   holdout and the 100–300 hard-page runtime reality pilot.
7. Activate one persisted W1 change→impact vertical slice.
8. Implement one grounded ASK path plus normalized consumption lineage.
9. Promote persistent CAS reads only after invalid-hit/security tests.
10. Implement RAGFlow/read-only MCP as downstream projection, never canonical
    truth.

## 7. Holds preserved

- No broad `source.discovery.observed` durable event is added merely to match the
  blueprint wording. Existing collection events remain producer truth; a narrow
  normalization adapter is preferred.
- No generic ASK chatbot is added before active-world/evidence contracts are
  live.
- No RAGFlow adapter is added before a stable active-world export contract.
- Gate 1B remains real-workload evidence, not a code-complete label.
- Canary B remains blocked.
