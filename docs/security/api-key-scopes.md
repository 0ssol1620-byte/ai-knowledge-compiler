# API key scopes

API keys inherit the creating member's current tenant role, but a role never
widens the key's explicit scope. Removing or disabling that member invalidates
the key.

| Scope          | Allowed requests                                                       |
| -------------- | ---------------------------------------------------------------------- |
| `api:read`     | Any authenticated `GET`, `HEAD`, or `OPTIONS` API request              |
| `api:write`    | Authenticated mutation requests, still subject to RBAC and idempotency |
| `events:read`  | Only `/v1/jobs/{job_id}/events` and `/events/replay`                   |
| `exports:read` | Only `/v1/exports/{export_id}` and `/download`                         |

An empty scope list is invalid. Specialized read scopes do not grant project,
document, settings, credit, analytics, or other tenant reads. `api:write` does
not implicitly grant reads. Every request is also narrowed by the tenant hint
embedded in the key and authenticated by the digest of the complete
high-entropy token; the hint is never accepted as proof of identity.

Keys are shown once at creation. Store them in a secret manager, rotate them,
and revoke them when their automation is retired. Never place keys in URLs,
logs, repository files, document content, or browser storage.
