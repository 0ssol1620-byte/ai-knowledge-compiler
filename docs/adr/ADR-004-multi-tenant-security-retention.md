# ADR-004: Multi-tenant Security and Retention

- Status: Accepted
- Date: 2026-07-29
- Owners: Security, Platform, Privacy

## Context

Uploaded documents are untrusted. The progress UI included a security-scan
stage while the state machine allowed uploaded files to proceed directly to
preflight. URL ingestion was described without a canonical launch default.

## Decision

### Quarantine state machine

The server-enforced page/file intake path is:

```text
UPLOADED
  → SECURITY_SCANNING
  → SECURITY_VERIFIED
  → PREFLIGHTING
  → PREFLIGHTED
  → NATIVE_EXTRACTING | OCR_QUEUED
```

Security scanning may terminate in `SECURITY_REJECTED` or `FAILED`. No parser,
preview generator, knowledge worker, or exporter may read a quarantined object.
Promotion from quarantine to verified storage requires:

- allowlisted MIME and extension agreement;
- magic-byte validation;
- bounded archive expansion and relationship inspection;
- malware scan;
- encrypted/password-file policy;
- size/page/pixel/decompression limits;
- immutable scan result and scanner signature version.

Objects use UUID-based tenant/project prefixes. Authorization requires both
database policy and object-prefix verification. Public buckets and tenant-wide
worker credentials are prohibited.

### URL ingestion

`url_ingest_enabled=false` is an independent feature flag. When enabled for an
approved tenant, fetches use a dedicated egress proxy with:

- HTTP/HTTPS only;
- DNS resolution and private/link-local/metadata IP denial on every redirect;
- redirect and byte limits;
- outbound domain policy;
- content-type and magic-byte validation;
- no ambient cloud credentials;
- the same quarantine scan as direct uploads.

External model fallback and URL ingestion are separate permissions.

### Retention and deletion

- Source and derived objects have explicit lifecycle states and scheduled purge
  timestamps.
- Delete requests create an auditable deletion job and receipt.
- Backups follow documented expiry; legal hold is enterprise-only and explicit.
- Training pools are separate stores populated only by consent and honor future
  opt-out/deletion.
- Logs contain identifiers, hashes, state, and metrics, never document content.

## Consequences

- The UI reflects a real security stage.
- An uploaded object cannot bypass quarantine.
- URL fetch functionality cannot silently expand the MVP attack surface.

## Verification

- State-transition tests reject `UPLOADED → PREFLIGHTING`.
- Synthetic malicious fixtures exercise scan rejection safely.
- Cross-tenant object-access and mass-deletion tests run before launch.
- Restore, secret-rotation, and breach-notification drills are release gates.
