# Browser-direct multipart uploads

This runbook covers the production S3-compatible upload path. The local
filesystem adapter intentionally keeps the authenticated single `PUT` endpoint
so development remains runnable without emulating cloud credentials.

## Protocol

1. The browser computes SHA-256 incrementally and calls
   `POST /v1/uploads/initiate` with the immutable filename, byte size,
   content type, digest, and optional project ID.
2. Below `AKC_MULTIPART_UPLOAD_THRESHOLD_BYTES`, the API returns one short-lived
   signed `PUT`. Above it, the API creates an opaque provider multipart session
   and returns only part geometry and control-plane endpoint paths.
3. `POST /v1/uploads/{id}/parts/sign` signs a bounded batch of part numbers.
   The API never receives part bytes. Browser workers upload slices directly
   with server-bounded concurrency and retry limits.
4. `GET /v1/uploads/{id}/parts` lists already committed provider parts. The
   browser stores only the control-plane upload ID in local storage and resumes
   missing parts; signed URLs are never persisted.
5. `POST /v1/uploads/{id}/complete` requires every part exactly once in
   contiguous order. The API reconciles provider part number, sanitized ETag,
   and exact expected part size before asking the provider to assemble.
6. Finalization performs `HEAD`, downloads the quarantine object into a bounded
   spool, recomputes the full SHA-256, validates MIME magic and archive policy,
   and runs antivirus before promotion. A multipart ETag or provider composite
   checksum is never treated as the raw-object SHA-256.

Completion is safe to retry. If the provider committed the object but its ACK
was lost, the opaque multipart handle can disappear; the API recovers only when
the quarantine object exists at the fixed random key and passes full size,
digest, type, and antivirus validation. Abort is idempotent for already aborted,
expired, or provider-missing sessions. A completed upload cannot be aborted.

## Configuration

| Variable                               | Purpose                                            | Default |
| -------------------------------------- | -------------------------------------------------- | ------: |
| `AKC_MAX_UPLOAD_BYTES`                 | Product-wide hard ceiling, further reduced by plan |   1 GiB |
| `AKC_MULTIPART_UPLOAD_THRESHOLD_BYTES` | Switch from single PUT to multipart                |  50 MiB |
| `AKC_MULTIPART_PART_SIZE_BYTES`        | Fixed non-final part size; minimum 5 MiB           |   8 MiB |
| `AKC_MULTIPART_MAX_PARTS`              | Product and provider part-count ceiling            |  10,000 |
| `AKC_MULTIPART_PRESIGN_BATCH_SIZE`     | Maximum URLs signed per API request                |      20 |
| `AKC_MULTIPART_CLIENT_CONCURRENCY`     | Browser part workers, server-bounded               |       4 |
| `AKC_MULTIPART_CLIENT_MAX_RETRIES`     | Transient retries per part                         |       3 |
| `AKC_PRESIGNED_UPLOAD_TTL_SECONDS`     | Individual signed URL upper TTL                    |   600 s |
| `AKC_MULTIPART_SESSION_TTL_SECONDS`    | Resumable multipart session lifetime               |    24 h |

Startup fails when part geometry cannot cover the configured product limit.
Production also fails closed unless PostgreSQL, S3-compatible private storage,
HTTPS object endpoints, durable scheduling, antivirus, metrics, and tracing are
configured.

## Bucket and IAM requirements

- Keep the quarantine bucket private, encrypted, and lifecycle-managed.
- Allow the API workload identity to create, list, complete, and abort
  multipart uploads only under the quarantine prefix.
- Permit browser origins by exact HTTPS origin. Allow `PUT`, expose `ETag`, and
  allow only the headers included in signatures. Never use wildcard origins
  with credentials.
- Abort incomplete multipart uploads through bucket lifecycle as a backstop.
  The Terraform scaffold uses a one-day cleanup rule.
- Treat every signed URL as a bearer credential. Do not log URLs, query
  strings, provider upload IDs, credentials, customer filenames, or digests.

The Terraform CORS and lifecycle resources are executable AWS evidence. R2 uses
the same S3-compatible API path, but endpoint, CORS, IAM token scope, and
browser reachability must still be validated in the actual deployment before a
production gate can pass.

## Incident checks

- `UPLOAD_EXPIRED`: start a new session; the old provider upload was aborted.
- `MULTIPART_PARTS_INCOMPLETE`: resume from the provider part list.
- `MULTIPART_ETAG_MISMATCH`: re-upload that part; do not override validation.
- `UPLOAD_ASSEMBLY_NOT_FOUND`: provider state and the quarantine object are
  both absent; start over.
- `CHECKSUM_MISMATCH`, `CONTENT_TYPE_MISMATCH`, or `MALWARE_DETECTED`: the
  quarantine object is rejected and deleted. Never promote it manually.
