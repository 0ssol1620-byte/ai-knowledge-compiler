# Core immutable input reference verification — 2026-09-30

The Foundation publication adapter requires `candidate.validation.immutableInputsOnly`.
The Core candidate now includes the computed boolean; `validation/report.json` includes
the same result. It participates in candidate/package digests and durable replay.

The check validates both source and OCR references against the existing Foundation
layout `immutable/{tenant}/{workspace}/{uploadRevisionId}/{contentDigest}/{filename}`.
Both must have the same revision directory, the request tenant/workspace and source
SHA-256 component, safe nonempty components and distinct filenames. Mutable aliases,
cross-scope references, mismatched revision/digest directories and nested aliases
produce `false`, `IMMUTABLE_INPUT_BINDING_INVALID` and a `review_required` candidate.
The upload revision ID deliberately need not equal the stable logical `nativeId`:
Foundation maps successive upload UUIDs onto one logical source across revisions.

This verifies references supplied at the authenticated compiler boundary. It does
not certify backend write-once enforcement, validate unavailable source bytes,
attest OCR derivation, or replace Foundation intake/CDR and storage qualification.
Generic/legacy source paths still compile for review but cannot report this check
as passed. Existing source identity, page, path, operation and fragment validation
continue to reject invalid requests independently.

## Acceptance

- Fifteen new signed HTTP tests cover positive reference binding, separate logical
  and upload identities, mutable/cross-tenant/workspace/revision/digest references,
  nested paths and source/OCR aliasing.
- Actual Foundation `lib/core-runtime-v2.ts` dispatch and projection executed against
  the changed Core FastAPI application with a fresh synthetic SQLite journal.
  Five cross-repository tests passed: initial projection and actual package hashes,
  process restart replay, incremental projection/full rebuild equivalence, unsigned
  and wrong-HMAC refusal, and tampered response digest refusal.
- The Foundation harness was copied into disposable workspace qualification
  files; original Foundation files were not edited. Only three old missing-field/null
  assertions were changed to require the actual field and non-null projection.
- Compiler strict mypy and Ruff passed. Broad Product Core tests are recorded in the
  integration handoff alongside the exact local command and result.

A new release digest must be assigned when deploying this compiler change. Previously
stored receipts are immutable; Core will not rewrite an old receipt into a new verdict.
The journal already binds accepted work to its compiler release digest and refuses
cross-release idempotency collisions. No deployment, promotion or live storage action
was performed.
