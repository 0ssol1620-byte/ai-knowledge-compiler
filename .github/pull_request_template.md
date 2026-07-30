## What changed

<!-- Describe the user-visible outcome and the narrow implementation scope. -->

## Evidence

- [ ] Relevant unit/contract/integration tests pass.
- [ ] Lint, type checks, repository policy, and dependency checks pass.
- [ ] New or changed API/events/schemas are backward-compatible or versioned.
- [ ] No customer content, credential, presigned URL, or production identifier
      appears in code, logs, fixtures, screenshots, or artifacts.
- [ ] Tenant isolation, deletion, credit idempotency, and provenance behavior
      were considered where relevant.
- [ ] External processing remains disabled by default; any new external transfer
      has explicit tenant consent and a reviewed provider boundary.
- [ ] Infrastructure changes were rendered/validated and still contain no
      plaintext Secret.
- [ ] User-facing behavior was tested in light/dark, keyboard, reduced-motion,
      and narrow viewport modes where relevant.

## Release impact

- Migration: <!-- none / backward-compatible expand / reviewed plan -->
- Rollback: <!-- exact revision/config/model rollback -->
- Observability: <!-- metrics, alerts, runbook -->
- External evidence still required: <!-- real corpus, GPU, cloud, legal, beta -->

## Risk and reviewers

<!-- Call out security/privacy/billing/model/license risk and required owners. -->
