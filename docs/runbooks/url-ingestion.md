# URL ingestion worker

## Contract

URL ingestion is disabled by default. When `AKC_URL_INGESTION_ENABLED=true`,
`POST /v1/documents` accepts `source_url` and atomically creates a
`URL_FETCH_QUEUED` document plus one durable `url_fetch_tasks` row. The API
returns `202` with `/v1/url-fetch-tasks/{task_id}`. The status resource exposes
only a query-free canonical URL and an HMAC-SHA256 query correlation value.

The full URL, including its query, is normalized and Fernet-encrypted before it
is written. It must never appear in task status, audit metadata, metrics, or
logs. `AKC_URL_ENCRYPTION_KEY` and `AKC_URL_QUERY_HMAC_SECRET` are independent
keys and must be rotated together on the API and URL worker.

## Execution and safety

The worker claims one due task in a short transaction with `FOR UPDATE SKIP
LOCKED`, a lease token, and a session advisory lock. HTTP and object-store
traffic happen only after that transaction commits. A final transaction checks
the same task, tenant, document, project, lease token, lease deadline, and
deletion tombstones before publishing the result.

`SecureUrlFetcher` enforces HTTPS on public port 443, rejects credentials and
fragments, resolves and pins every redirect hop, rejects every non-global or
metadata address, bounds redirects/time/bytes, rejects compressed bodies, and
checks declared MIME against file magic. Kubernetes adds a default-deny egress
boundary: DNS, the restricted database, object storage, ClamAV, and public TCP
443 are the only destinations. Private, loopback, carrier-grade NAT,
link-local, metadata, multicast, reserved, and documentation ranges are
excluded from public egress.

Every response is written to quarantine, downloaded back, re-hashed, and sent
to ClamAV. Scanner unavailability is retryable and fail-closed. Confirmed
malware is a permanent failure. Only a clean object is promoted to the
immutable source prefix and linked through `UploadSession`, `SourceFile`,
`Document`, and `DocumentVersion` in one fenced transaction.

Source keys contain the task ID and content SHA-256. A transaction advisory
lock serializes project/content deduplication. Repeating an attempt overwrites
only the same deterministic object; a stale lease, cancellation, tombstone, or
failed database commit deletes that attempt's quarantine and promoted source
objects. A completed task is never claimed again.

## States and recovery

The active states are `queued`, `retry`, and `running`. Retryable failures use
bounded exponential backoff with deterministic jitter. Exhausted retryable
failures become `dead_letter`; permanent validation or malware failures become
`failed`. A user cancellation or project/document deletion becomes
`cancelled`, clears the lease, and fences an in-flight worker.

Investigate:

1. `akc_url_fetch_queue_depth{status=~"queued|retry|running"}` and
   `akc_url_fetch_dead_letter_tasks`.
2. `last_error_code` from the tenant-scoped status endpoint. Do not decrypt the
   URL for routine triage.
3. ClamAV readiness, object-store health, DNS, and public-443 network policy.
4. Worker database startup verification. Production readiness fails unless the
   login is `NOINHERIT`, owns no table, has no direct ACL, and assumes only the
   `akc_url_fetcher` `NOLOGIN BYPASSRLS` role.

Do not manually change a task to `queued` while another lease or advisory lock
is active. After correcting an external dependency, an operator may requeue a
dead-letter task only through a separately reviewed admin mutation; no direct
database update is part of this runbook.

## Verification

Run:

```powershell
python -m pytest services/url-fetcher/tests -q
python infra/security/validate_deployment.py
python -m alembic upgrade head
python -m alembic downgrade 0009_payment_credit_purchase
python -m alembic upgrade head
```

Internet calls in tests are forbidden. Fetcher, DNS, scanner, and object-store
failure paths use deterministic fakes; the production adapter is exercised
only in an isolated environment with explicit egress controls.
