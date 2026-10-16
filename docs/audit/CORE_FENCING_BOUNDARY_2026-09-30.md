# Product-Core shared-journal fencing boundary

This disabled internal Python protocol changes no HTTP, Foundation, scheduler or
SQLite contract. Eleven synthetic state-machine tests qualify intended semantics,
not distributed execution. No shared backend is implemented or activated.

Architecture evidence: `infra/product-core/README.md` and the Cloud Run/Vercel
adapters own candidate compilation only. `journal.py` persists accepted immutable
work, per-document fragments and the reduced candidate in local SQLite transactions.
`services/api/src/akc_api/models.py` and `services/scheduler/src/akc_scheduler/database.py`
contain leases for other task families. Those rows cannot authorize Product-Core
checkpoint writes. Masterplan v4 QUE-03 requires older fencing writes to reject;
its named acceptance test is `test_stale_fencing_token_cannot_commit`.

`fencing.py` proposes the smallest backend boundary: acquire immutable scoped
work/release ownership, renew it, and atomically commit a fragment or candidate
under owner, epoch, generation and unexpired authoritative-store time. Acquire
increments a durable generation even when the same owner name returns. Restore
must rotate a never-reused epoch: a snapshot can rewind a generation, so generation
alone cannot reject a pre-restore worker. Retention must keep binding/generation
tombstones. Candidate completeness, fragment integrity and receipt binding remain
required in the backend transaction; the reference model intentionally tests only
fencing and immutable checkpoint semantics.

Tests cover takeover; exact expiry; renewal refusal after expiry; live-owner
exclusion; immutable work/release; tenant/workspace/owner/generation tampering;
restore generation reuse; idempotent checkpoints and conflict rejection; bounded
lease duration. The fake uses manually advanced authority time and is neither
thread-safe nor persistent. It is confined to tests.

Activation gate: choose the shared transactional storage and its deployment owner,
then implement this protocol with atomic guard plus write (no separate preflight
check), identity/authentication, commit-time expiry, and the existing integrity
checks. PostgreSQL already exists in the control plane but the Product-Core
adapters have no shared-journal connection/configuration. Adding a speculative
database connection would introduce unapproved deployment coupling. A future
backend conformance suite must run two real clients, pause an expired worker across
takeover, restore snapshots, interrupt transactions and prove rejected writes leave
no fragments/candidates. Foundation independently retains promotion lease/CAS and
ACL authority. No local test establishes that distributed gate.
