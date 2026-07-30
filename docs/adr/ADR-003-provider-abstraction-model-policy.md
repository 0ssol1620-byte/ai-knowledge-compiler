# ADR-003: Provider Abstraction and Model Policy

- Status: Accepted
- Date: 2026-07-29
- Owners: Model Platform, Routing, FinOps
- Policy version: router-1.0.0

## Context

Foundation models are replaceable providers. Product contracts are route
profiles, CIR, quality gates, provenance, and AKMP. A previous example enabled
external fallback by default and the Fast product profile was absent from the
recipe registry.

## Decision

### Provider boundary

Parser and knowledge workers receive object references or bounded inline test
payloads, never tenant-wide storage credentials. They return CIR-compatible
records, exact model revision, image digest, checksum, idempotency key, timing,
resource, retry, and cost metrics.

Browser clients never call GPU providers directly. Control-plane idempotency is
authoritative; provider handlers also return deterministic result IDs and
deduplicate within a warm worker.

### Route profiles

The registry MUST contain:

- `parse_fast_v1`: HPD shadow candidate, English/Chinese only, low-difficulty
  pages, disabled by default, always falls back to `parse_balanced_v1`.
- `parse_balanced_v1`: native/Paddle baseline.
- `parse_precision_v1`: selective second opinion for high-risk or failed pages.
- `parse_long_v1`: balanced result plus Unlimited-OCR continuity shadow.
- `parse_private_v1`: self-hosted providers only; external egress denied.
- `knowledge_standard_v1`: Qwen 3.5 4B baseline.
- `knowledge_precision_v1`: Qwen 3.5 9B with a newer-model shadow challenger.

Fast and Long never become default solely from upstream claims. Promotion
requires the internal corpus and staged canary gates.

### External processing

All external-processing feature flags default to false:

```text
external_mistral_fallback=false
external_precision_api=false
external_training_export=false
```

An external call additionally requires tenant opt-in, a per-job consent
record, displayed provider/region/retention/page count/credit estimate, and an
egress policy that permits the provider. Private mode forces every external
flag false and rejects attempts to override it.

### Model immutability

- Upstream repository and full commit/revision are mandatory.
- Floating tags such as `main`, `master`, `latest`, and empty revisions fail CI.
- Container image digest, runtime/framework/CUDA versions, quantization,
  decoding settings, and license snapshots are stored with the run.
- Model load and self-test happen once per worker process.
- Promotion and rollback are configuration changes, not application releases.

## Consequences

- `parse_fast_v1` is visible in the product contract without prematurely
  enabling HPD.
- A sample configuration cannot accidentally send customer data externally.
- Model/provider replacement does not change core schemas or UI state.

## Verification

- Registry CI validates revisions, licenses, recipes, fallbacks, and cycles.
- Private-mode tests deny external providers.
- Provider smoke verifies revision/checksum/cost cap.
- Canary progresses 1% → 5% → 20% only when quality and edit metrics hold.
