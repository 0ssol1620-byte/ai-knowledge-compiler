# Native analysis worker runbook

## Boundary

`POST /v1/documents/{id}/analyze` is control-plane only. It atomically creates
one `analysis_tasks` row plus one `document.analysis.requested.v1` outbox event
and returns `202`. The API never imports a parser in its production import
graph and production settings reject the in-process development adapter.

Only `akc-analysis-worker` may claim analysis events. PostgreSQL claims use
`FOR UPDATE SKIP LOCKED`, a bounded lease, an attempt counter, deterministic
exponential backoff, and a per-task advisory lock. The restricted runtime login
may assume only the `akc_analysis_worker` role. Startup/readiness fails unless
the expected table/column grants, forced RLS, login shape, and bubblewrap
namespace self-test all pass.

The parser child receives no database, object-store, API-signing, or provider
credentials. In production it runs in a bubblewrap user/PID/network namespace
inside a gVisor pod with a read-only root, a single writable workspace, no
network, kernel resource limits, a parent-enforced wall timeout, and bounded
source/result/preview sizes.

## Capacity limits

- Product upload storage ceiling: plan dependent.
- Native analysis source ceiling: 256 MiB, rejected at upload initiation.
- Child address-space ceiling: 1.5 GiB.
- Child single-file ceiling: 512 MiB.
- Manifest ceiling: 128 MiB.
- Total preview workspace ceiling: 256 MiB.
- Pod memory/ephemeral ceilings: 3 GiB / 2 GiB.

The Team 1 GiB storage entitlement does not imply a 1 GiB native parser
entitlement. Raising the 256 MiB boundary requires a separately benchmarked
high-memory or streaming parser recipe, an adjusted pod limit, hostile-file
regression evidence, and a release review. Never raise only the API limit.

## Preview contract

PDF, supported image, and text sources can produce derived PNG preview and
thumbnail assets. They are stored under a task-and-lease-specific derived key,
hash/size checked before commit, referenced by `PageAsset`, and served only
through authenticated `GET /v1/pages/{page_id}/preview`. Office sources remain
explicitly `unsupported_document_preview`; extraction can complete without
inventing a visual rendering. The workspace overlays stored `bbox1000`
coordinates on the returned page image.

The UI preview is never a visual-model input. For each renderable page the
sandbox also creates immutable RGB PNG `inference_raster` assets at 200 and
300 DPI. Before commit the parent verifies the manifest filename, bytes,
SHA-256, dimensions, the 40-megapixel ceiling, the 32 MiB per-asset ceiling,
and the 1 GiB per-task total ceiling.
`PageAsset.metadata_json` records `content_type`, `size_bytes`, `width`,
`height`, `dpi`, `colorspace`, zero-based page index, source SHA-256, and
retention class. Normal OCR selects only the exact 180–220 DPI asset; precision,
small-text, table, and Paddle-VL routes select only the 250–300 DPI asset. A
missing or inconsistent inference raster fails closed; preview fallback is
prohibited.

## Triage

1. Check `akc_analysis_queue_depth{status=~"queued|running"}`,
   `akc_analysis_dead_letter_tasks`, attempt duration, and sandbox termination
   counters.
2. Run `python -m akc_worker_document --check` in the worker image. A failure
   means the database role or namespace launcher is unsafe; do not bypass it.
3. Inspect only bounded task fields (`status`, `attempt_count`,
   `last_error_code`, timestamps). Logs and metrics must not contain filenames,
   object keys, tenant IDs, extracted text, or document IDs.
4. Retryable codes (`PARSER_TIMEOUT`, `PARSER_PROCESS_CRASH`,
   `PARSER_INTERNAL_ERROR`) are requeued until `max_attempts`. Validation and
   integrity failures are terminal immediately. A terminal task marks the
   outbox event dead-lettered and the document `PARSE_FAILED`.
5. Before replaying a terminal task, establish whether the parser image,
   configuration, or source policy changed. Never mutate attempts or leases by
   hand while a worker is running.

Deletion requests are hard fences. The deletion worker clears any active lease,
and the analysis worker re-locks the task, project, and document before its
single atomic page/block/preflight commit. Any preview objects uploaded by a
losing lease are removed best-effort and are still covered by lifecycle policy.
