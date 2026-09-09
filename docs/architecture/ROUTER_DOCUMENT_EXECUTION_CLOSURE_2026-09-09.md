# Router document execution — approved implementation, 2026-09-09

Status: IMPLEMENTED_NOT_MERGED / opt-in candidate. Not a production-router promotion, end-to-end quality qualification or a claim of lossless documents.

## Implementation boundary

The existing Router v2 DocumentExecutionPlan now has an executable, bounded in-process composition in `akc_router.document_execution.execute_document_text_plan`.

The composition checks the plan's source version and the observed source/representation digests, exact region inventory, declared primary lane and portfolio revision, route qualification supplied by trusted application code, data policy, finite document budget and deadline, and dependency layering before starting provider work. Only explicitly permitted providers may run. An unresolved plan is not executable.

Each wave launches a bounded number of cooperative asynchronous workers. Per-provider queue limits are separate from the document parallelism limit. Queue waiting counts against deadlines. Primary attempts and recovery share a single Decimal reservation ledger; failed and timed-out work still consumes its reservation. These are internal reserved cost units, NOT measured USD or billed GPU usage.

A dependent unit is not executed when its upstream unit failed verification. Every declared region receives a result; missing or blocked work cannot disappear from the denominator. Quarantine stops later work and removes accepted text from the returned document result. Live application authorization is rechecked before attempts, after provider returns and before disclosure. Revocation also withholds previously accepted content.

Caller cancellation propagates through TaskGroup and waits for cooperative child tasks. Provider-boundary checks also refuse late results when a provider suppresses timeout cancellation or blocks the event loop, reject malformed response types without recording their bodies, and snapshot attempt/provider mappings before awaiting work. This is NOT proof that a non-cooperative remote GPU job or subprocess has stopped. The service provider adapter must implement sandbox, timeout, cancellation and durable ownership for those resources.

Successful disposition is deliberately `verified_text_scope`, with `verification_scope=declared_text_regions_only` and `production_promotion=False`. The code cannot publish a World, qualify a model or open customer-data access.

## Native projection repairs

A text block without a page assignment now refuses with `NATIVE_TEXT_PAGE_UNASSIGNED`; a text block with references to multiple pages refuses with `NATIVE_TEXT_PAGE_SPAN_UNRESOLVED`. Previously these shapes could respectively disappear from the page projection or copy the same whole text onto multiple pages. This adapter has no span-level evidence to repair either silently.

The final public Native integration accepts an explicit fresh scratch receipt directory, preserving historical observations instead of overwriting them during repeated tests.

## Validation

- Final hash-bound combined suite: 236 passed. This consists of 229 router unit tests plus seven tests for the separate offline selector protocol. All 42 bound source/test inputs remained unchanged during qualification.
- Changed implementation and test/research files: Ruff clean.
- `document_execution.py`, `evidence_execution.py`, `native_observation.py`: strict mypy clean.
- Five actual public filing integration tests passed with exact source hashes and the existing 290-page Apple corpus. They test Native observation/locator availability, not OCR accuracy, figure understanding or model selection superiority.

New regressions cover actual bounded parallel execution, provider-specific capacity, shared recovery budget, dependency ordering and refusal, cycles/unknown endpoints, duplicate and missing unit inventory, foreign source, changed portfolio, primary-lane mismatch, unqualified routes, external processing policy, revocation, callback exceptions, quarantine, caller cancellation and queued deadlines.

Intermediate failures are retained in scratch logs. A missing tracked schema was materialized with additive sparse checkout, not rewritten. A 10ms wall-clock test incorrectly required that work must have started even under host contention; it now injects the document clock to test the queue boundary deterministically. Runtime timeout values and security assertions were not weakened. Existing provider timeout tests remain.

## What is still not completed

This is not the entire Router v2 in the product. Remaining work includes live GPU/native provider adapters, actual runtime qualification and costs, multimodal table/formula/chart loss detectors, independent witness acquisition, robust partial-region merge, cross-document/tenant durable scheduling, source ACL lifecycle, real service telemetry, fresh sealed validation and bounded deployment/rollback.

`qualified_routes` and independent witnesses are trusted application inputs; their type or a producer label alone does not prove real runtime qualification or evidentiary independence. Untrusted source text must never supply either.

The older engine.py decision authority, champion matrix, operational services, customer-data gate, private Core defaults, and frozen historical evidence are unchanged. The parent planner PR must pass its own compatibility and release ladder before this candidate can become an operational caller.

## Evidence paths

All below are relative to the isolated worktree, not public marketing artifacts:

- `.chatgpt2codex/closure-lint.log`
- `.chatgpt2codex/closure-types.log`
- `.chatgpt2codex/closure-tests.log`
- `.chatgpt2codex/qualification-current.json` — final source-hash binding
- `.chatgpt2codex/bound-lint.log`, `bound-types.log`, `bound-tests.log` — final 236-test selection
- `.chatgpt2codex/closure-native-public.log`
- `.chatgpt2codex/native-public-final-20260909/`
- earlier failure and initial Native receipts remain beside these files

## Primary references reviewed

- Python structured concurrency and cancellation: https://docs.python.org/3/library/asyncio-task.html
- Original TAVONEL Router blueprint: early preflight → plan → dependent parallel execution → recovery → independent verification → exact evidence → World. This text-region composition closes only the bounded execution portion; it does not satisfy the full promotion checklist.
