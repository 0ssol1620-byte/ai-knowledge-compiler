# Mutation idempotency

Authenticated tenant mutation routes accept an optional `Idempotency-Key`
header. Keys are printable ASCII, non-empty, and at most 200 characters. The
scope is tenant, HTTP method, route template, and key. The canonical request
hash also covers the concrete path, sorted query parameters, media type, and
canonical JSON body (or the raw-body digest).

- A completed request with the same key and request hash returns the original
  status code and JSON body without executing the mutation again.
- Reusing the key for a different concrete target, query, or body returns
  `409 IDEMPOTENCY_CONFLICT`.
- An unexpired incomplete legacy record returns
  `409 IDEMPOTENCY_INCOMPLETE`; expired records may be safely replaced.
- PostgreSQL serializes contenders with a transaction-scoped advisory lock.
  SQLite uses a deterministic in-process lock for the development/test
  adapter. The response record and database mutation commit atomically.
- Responses are encrypted at rest because API-key and webhook creation return
  a secret exactly once. Production requires
  `AKC_IDEMPOTENCY_RESPONSE_ENCRYPTION_KEY`.
- Records expire after 30 days by default (never less than one day), and the
  scheduler deletes expired rows in bounded, skip-locked batches.

Compile dispatch copies the incoming idempotency key into both job options and
the durable dispatch event. When no client key exists, it uses the stable
`job:<job-id>` key, so every downstream GPU attempt keeps one identity.

## Pre-tenant authentication contract

`/auth/register`, `/auth/verify-email`, `/auth/resend-verification`, and public
`/team/invitations/accept` are deliberately outside tenant-scoped idempotency:

- registration is serialized by normalized-email uniqueness and returns the
  existing-account conflict without creating a second tenant;
- verification consumes one token digest transactionally and cannot verify a
  second account;
- resend invalidates prior live token digests before enqueuing one delivery,
  while the delivery table uniquely keys the token digest;
- invitation acceptance locks and atomically consumes one tenant-hinted HMAC
  token, so it cannot create a second membership or accept twice.

Those routes use a separate, identity/rate-limit namespace because a tenant ID
does not exist at request admission. Login/logout are session operations and
do not create tenant domain resources.
