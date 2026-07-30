# Immutable page attempts

Page rows are the logical analysis result. Once a page is terminal, compile,
provider, and user-retry work must not reopen or overwrite it. Every later run
uses a new `page_attempts` row and an append-only
`page_attempt_transition_events` stream.

## Invariants

- `Page.status` remains unchanged during compile and retry execution.
- Attempt numbers are monotonically increasing per page.
- At most one non-terminal attempt exists per page.
- Identity, route, policy, and terminal attempt fields are immutable.
- `transition_page_attempt` is the only production state mutator.
- A terminal-to-retry request creates a new `RETRY_SCHEDULED` attempt.
- Every job event for page work carries the attempt ID and attempt number.
- Credit reserve, consume, and release operations use stable idempotency keys.
- Quality vectors contain measured values only. Unavailable dimensions are
  `null`; numeric and table mismatches are critical review findings.

PostgreSQL migration `0013_page_attempts` enforces terminal and identity
immutability with a trigger, forces tenant RLS, and prevents update/delete
access to transition events. The partial unique active-attempt index is also
present in SQLite tests.

## Routing and providers

Analysis and compile load the project output profile, tenant policy, feature
flags, and exact enabled model-registry rows while holding database locks. A
registry row is ready only when its model revision, runtime image digest,
adapter version, endpoint, rollout, and route flag are valid.

The native output is evaluated by `akc_quality.evaluate_quality`; the result is
then passed to `akc_router.decide_escalation`. Numeric or table critical
findings go directly to review.

Visual routes enqueue a durable `gpu_provider_invocations` row and leave the
parent job in:

```json
{
  "stage": "visual_waiting",
  "state": "WAITING_PROVIDER"
}
```

A completed visual invocation is not success evidence by itself. The parent
dispatcher resumes and admits the output only after the stored object, exact
page raster, request/result hashes, provider/model/runtime/adapter/prompt
attestation, and strict `akc-visual-page-1.0.0` payload all match. Every block
must carry page-scoped provenance, calibrated block and token confidence, and
type-specific content. Tables use canonical cells, formulas use LaTeX, and
figures identify either an admitted image asset or an exact source-bbox crop.

The candidate stays outside persisted page blocks while security, quality, and
escalation run. Secret, PII, or prompt-injection signals park the job for review
without retaining candidate text. Only `ACCEPT` atomically replaces unlocked
machine blocks; user-locked blocks are preserved. `DISCARD_CHALLENGER`,
`RETRY`, and `ESCALATE` change zero blocks. Accepted visual blocks retain exact
model-run IDs and attestation for CIR/export reconstruction.

If persisted preflight evidence says `sensitive_data.has_secret=true`, compile
and retry remove `mistral_fallback` and force
`external_api_allowed=false`. Events may state that sensitive data was
detected, but must not copy raw values.

## Triage

1. Read the job snapshot and locate `page_attempt_id`,
   `page_attempt_number`, `invocation_id`, and `state`.
2. Read the ordered attempt transition events. Do not edit them.
3. If the job is `WAITING_PROVIDER`, inspect the content-free GPU invocation
   state and its attestation/error code.
4. If the provider is terminal but the job still waits, inspect the parent
   resume event and the first content-free admission/quality error code. Do not
   bypass attestation, security review, or escalation by manually marking the
   attempt complete.
5. For a retry conflict, check for an active attempt before treating it as an
   idempotency defect.
6. For credit discrepancies, reconcile ledger entries by job and operation
   key; never repair balances without an audited adjustment.

## Validation

```powershell
.venv\Scripts\alembic.exe heads
.venv\Scripts\pytest.exe -q tests/unit/test_page_attempt_runtime.py
.venv\Scripts\pytest.exe -q services/api/tests/test_api_integration.py
.venv\Scripts\mypy.exe packages services
```

For a migration rehearsal, use a disposable database and execute
`upgrade head`, `downgrade 0012_team_collaboration`, then `upgrade head`.
Production migration, RLS-role smoke, provider output admission, and benchmark
approval remain separate release evidence.
