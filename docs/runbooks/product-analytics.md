# Product analytics contract and operations

This runbook implements masterplan section 28 as a tenant-local measurement
contract. It does not assert that the product has users, conversion, margin, or
support outcomes. Repository tests use synthetic rows only.

## Reader and ingestion APIs

- `GET /v1/analytics?window=7d|30d|90d` returns schema
  `2026-07-30`.
- Every window uses UTC with a start-inclusive, end-exclusive boundary.
- Every ratio returns `numerator`, `denominator`, `value`, and `status`.
- A zero denominator returns `value: null` and
  `status: empty_denominator`; it never returns a misleading zero rate.
- `POST /v1/analytics/events` accepts only the six allowlisted event types
  below. It is tenant-authenticated and supports the standard
  `Idempotency-Key` contract.

Allowlisted optional events:

| Event | Required target/data | Purpose |
|---|---|---|
| `estimate_viewed` | one tenant-owned `document_id` | activation |
| `result_first_viewed` | one tenant-owned `job_id` | activation |
| `project_revisited` | one tenant-owned `project_id` | reuse |
| `source_merged` | one tenant-owned `project_id` | reuse |
| `support_session_closed` | integer `duration_seconds`, 1–86,400 | instrumented support effort |
| `user_reported_error` | project plus a bounded category enum | recorded error rate |

The event contract rejects unknown fields. It has no free-text, filename, URL,
email, contact, document-content, or arbitrary metadata field. Server receipt
time is authoritative. For document/job events, model and policy revisions are
joined from the server-owned immutable document version; clients cannot claim
their own revision.

## Privacy states

`product_analytics_enabled` is exposed through `GET /v1/settings` and can be
changed by an owner/admin through `PATCH /v1/settings` or `PATCH /v1/privacy`.
The setting uses the existing tenant-scoped feature-flag table, so no new
customer-content store or migration is needed.

| State | Snapshot | Optional events | External export |
|---|---|---|---|
| opted out | definitions only, all metrics `disabled` | discarded | never |
| private mode | local operational aggregates | discarded | never |
| enabled, non-private | local operational plus recorded events | allowlisted fields only | never |

Operational records such as jobs, pages, reviews, exports, credits, and
payments remain necessary service records. Private mode permits their local
aggregate but does not store optional page-view/support behavior. The API
response contains no tenant, user, project, document, job, filename, content,
or contact identifiers.

## Metric definitions

### North star

`weekly_verified_exported_or_reused_projects` is always a trailing-seven-day
count, independent of the reader-selected 7/30/90-day window. A project counts
once when:

1. a processing job had completed before the activity;
2. every review item that existed by that activity was resolved by then; and
3. a completed export, second document, recorded revisit, or recorded source
   merge occurred in the trailing seven days.

This is a count, not a rate. Upload and page volume alone do not qualify.

### Activation

The signup cohort has the selected window length but ends seven days before
the snapshot. Every member therefore has the same complete seven-day
observation. Stages are sequential: signup, first upload, estimate view,
processing start, first result view, review cleared, completed export, then
revisit/new-source merge. A downstream stage counts only after the preceding
stage. Review clearance is either resolution of all review items or task
completion when the document had no review item.

Private mode marks optional behavior stages `not_instrumented`; it does not
interpret missing events as zero behavior.

### Product

- first visible block and first usable page: nearest-rank p50/p95 from
  `analysis_tasks.started_at` to the first matching persisted block/completed
  page, using non-negative pairs only;
- job completion: jobs created in the window currently completed / jobs
  created in the window;
- export rate: projects with both a completed job and export in the window /
  projects with a completed job in the window;
- export split: completed exports grouped by the bounded export profile;
- review items per page: review items created / pages created in the window;
- edits per block: revisions in the window / active-document blocks existing
  at the window end;
- 7/30-day second job: first-completion project cohorts shifted back by the
  full horizon, avoiding right-censoring;
- existing-project merge: non-first documents created in the window /
  documents created in the window.

### Quality

- accepted without review: completed pages created in the window with no
  page review / completed pages created in the window;
- fallback: the explicit `mistral_fallback` route / pages with a route;
  manual review is not relabeled as fallback;
- source coverage: blocks with non-empty `source_text` / blocks created in the
  window. Text is inspected only for emptiness and is never returned;
- unsupported claim: AI/derived notes with no evidence block ID / AI/derived
  notes;
- numeric mismatch: review items containing
  `numeric.token_mismatch` / review items;
- table correction: resolved reviews that replace a table block / resolved
  reviews;
- user-reported error: recorded allowlisted error events / completed jobs.

### Economics

- credit cost per page uses only completed jobs with both a valid,
  non-negative `cost_actual.credits` and positive `progress.total`;
- credit evidence coverage discloses the attributable-job subset;
- credit cost per exported project is withheld unless every exported project
  has same-window attributable completed-job evidence;
- paid conversion is a period cohort: members joining in the selected window
  who paid after joining and before window end / members joining in the
  window. The response calls out right-censoring;
- support minutes use only recorded bounded support-session durations;
- refund rate is a successful-payment cohort paid in the window with a
  successful refund observed by window end / successful payments in the
  cohort;
- refund amounts remain integer minor units grouped by currency. Different
  currencies are never summed.

Gross margin is `insufficient_evidence` until provider invoices and
currency-normalized revenue are connected. Credit consumption is never called
money. Paid-credit breakage is also withheld because expired ledger entries
cannot yet be attributed to a payment grant without inventing a FIFO/LIFO
policy.

## Monitoring and incident response

The API emits only fixed-cardinality series:

- `akc_product_analytics_snapshots_total{result=enabled|disabled|failed}`
- `akc_product_analytics_events_total{event_type,result}`

There are no tenant, user, object, email, window, or content labels.
`AKCRequiredTelemetryContractMissing` checks that both series exist.
`AKCProductAnalyticsSnapshotFailureRateHigh` fires when at least five snapshots
occur in ten minutes and failures exceed five percent for ten minutes.

When the alert fires:

1. inspect API errors for the `/v1/analytics` route template, never concrete
   paths or request bodies;
2. verify the current database migration and RLS policy gates;
3. reproduce with a synthetic tenant and the focused test below;
4. do not turn unavailable currency/unit-economics evidence into zero;
5. roll back the analytics reader if necessary. Event ingestion is optional
   and must never block processing or exports.

Validation:

```powershell
.\.venv\Scripts\pytest.exe -q services/api/tests/test_product_analytics.py
.\.venv\Scripts\pytest.exe -q tests/unit/test_telemetry.py -k product_analytics
.\.venv\Scripts\ruff.exe check services/api/src/akc_api/product_analytics.py
pnpm --filter @akc/web typecheck
pnpm --filter @akc/web test
```

Production evidence still required: consented real-user cohorts, event
instrumentation start dates, real support workflow coverage, provider invoices,
currency-normalized recognized revenue, refund maturity, alert delivery, and
product-owner approval of definitions and targets.
