# Core replay and integrity qualification, 2026-09-30

## Isolation and base

Independent `git clone --no-hardlinks` at
`C:\Users\yspow\Documents\Codex\2026-09-30\task-3\core-work`.
Branch: `codex/core-replay-integrity`.
Fetched local-reference base: `57e55037872d6df30857c83714452b23783b8dab`.
Its parent is `f2fc5d856f7efb09221aede309e1e6f2e07671a9`, the supplied
productization lineage. This work is not based on `main`.

GitHub clone attempts stalled and were cancelled. The base was acquired from a
read-only local reference clone at exactly the requested checkpoint, rather than
claimed as a fresh GitHub remote fetch. The reference clone's tracked files and
dirty original repository were not modified. No credentials, visibility, billing,
production flags, customer data, push, merge, deployment or publication changed.

## Implemented scope

1. Reject duplicate effective region anchors (`native_object_id or region_id`),
   including collisions between explicit native and fallback region identifiers.
   Previously the anchor lookup could overwrite text/citation binding silently.
2. Fix unchanged incremental compilation incorrectly failing byte-level full
   equivalence: rebuild four collection aggregates whose bytes contain attempt
   provenance. Per-unit artifacts still use selective dependency planning and
   the existing missed-dependency oracle remains fail-closed. No byte hashes or
   equivalence comparisons are weakened.
3. Add opt-in single-host SQLite candidate compilation journal. Bind immutable
   work, tenant/workspace/idempotency key and release before extraction; commit
   each document fragment independently; persist the final candidate and receipt
   before returning success. A killed/in-flight fragment rolls back; previously
   committed fragments resume without extraction. Reduction commits atomically.
4. Preserve the original accepted request provenance through interrupted retries,
   including changed request IDs/timestamps/deadlines. Rebind only the outgoing
   authenticated receipt. Validate JSON schemas, stored digests, accepted-work
   binding, fragment content digest, response output digest and receipt binding.
   Conflicts persist across restart; corruption/storage errors return retryable
   503. HMAC and privacy checks still run before replay.

No Foundation wire fields changed. The only interface additions are an optional
Python `journal_path` argument and opt-in `TAVONEL_CORE_JOURNAL_PATH` environment
setting. Foundation requires no changes to submit/retry existing v2 requests.
The existing deployment documentation describes its limits; no runtime setting
was activated here.

## Acceptance evidence

Focused Product-Core suite: **54 passed**, one pre-existing FastAPI/Starlette
TestClient deprecation warning, about 3.4 seconds. The suite includes:

- A real child process exits abruptly during its second fragment; SQLite retains
  exactly one committed fragment and no candidate, and restart extracts only two.
- Exception interruption in extraction/reduction; changed-attempt resume matches
  the original uninterrupted candidate and candidate output digest.
- Four competing service instances: exactly three document extractions and one
  reducer invocation, with identical final responses.
- Completed restart replay with extraction prohibited; changed bytes, collection
  and release conflict; workspace namespace isolation; corrupt fragment, response,
  accepted request and receipt; storage failure; HMAC/customer policy precedence.
- Incremental addition/removal resume preserves parent and full equivalence;
  unchanged revisions with fresh request ID and timestamp now pass equivalence;
  injected missed dependencies still reject; 13-document shard invariance remains.
- Duplicate anchor rejection and valid text/page/source-reference binding.

The command selects all `test_product_core_*.py` unit modules and
`packages/product-core/tests` under the existing Python 3.12.6 interpreter. An
explicit workspace `--basetemp` avoids the pre-existing inaccessible shared
pytest temporary directory. Ruff check passes for Product-Core source and new
tests; `git diff --check` passes. Tooling is read from the existing local cache;
no interpreter, credential or original checkout installation was changed.
Strict mypy passes on the four changed source modules (journal, API, compiler,
contracts), using the existing Pydantic environment and cached PyYAML stubs.
UI/browser/build/Lighthouse gates were not run for this Python-only compiler
change; no production, distributed load or customer-data acceptance is implied.

## Remaining qualification

This is not distributed orchestration, production readiness or masterplan
completion. The journal is a local SQLite file, stores synthetic request and
candidate contents in plaintext, serializes writers during extraction/reduction,
and uses a 30-second lock timeout. A permanent filesystem with proper locks is
required; ephemeral serverless disk and network shares are not qualified.
Distributed leases/fencing, scheduler integration, retention/tenant deletion,
encryption, database restore, disk-loss recovery, bounded backlog/scale and
concurrent Foundation publication/ACL/revocation remain open. Customer paths,
paid-model comparison and release ownership still need external inputs. Hosted
CI remains subject to the integration task's known billing/access blocker.

Planning estimates only, assuming access to synthetic local infrastructure:
single-host storage/restore/retention qualification 2-4 engineering days;
distributed backend/lease/fencing plus fault qualification 1-2 weeks;
Foundation-to-Core concurrent publication qualification 2-5 days after both sides
are integrated. These are low-confidence scoped estimates, not a promise to
complete the full remaining masterplan or external release gates.
