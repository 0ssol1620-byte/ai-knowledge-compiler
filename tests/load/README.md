# Opt-in load tests

These k6 tests never run against a remote target implicitly.

- `k6-health.js` is read-only and checks the real liveness/readiness endpoints.
- `k6-journey.js` exercises login, direct upload, security completion, analysis,
  estimate, compile, SSE, export, and deletion with generated text only.

The journey requires a dedicated nonproduction user and an existing disposable
project through `AKC_TEST_EMAIL`, `AKC_TEST_PASSWORD`, and
`AKC_TEST_PROJECT_ID`. It never registers users or creates projects, and it
deletes every generated document in a `finally` block. Do not use a customer
tenant.

Remote execution additionally requires:

```text
AKC_ALLOW_REMOTE_SYNTHETIC=true
AKC_SYNTHETIC_CONFIRM=NONPRODUCTION_SYNTHETIC_ONLY
AKC_ALLOWED_REMOTE_ORIGINS=https://staging-api.example.invalid
```

`AKC_ALLOWED_REMOTE_ORIGINS` is a comma-separated set of exact origins; prefix,
suffix, wildcard, and path matches are not accepted.

Start with one VU and one iteration. Increase only after validating credits,
cleanup receipts, observability, and staging capacity. Archive the k6 summary
with the application/configuration/model revisions; a local run is not release
or SLO evidence.
