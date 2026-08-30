# source-adapters (`akc_source_adapters`)

Source connectors for the knowledge compiler: each adapter turns one upstream
system into an ordered stream of deterministic, hashable `ChangeEvent`
envelopes that can be resumed from a persisted cursor.

## Surface

| Object | Role |
| --- | --- |
| `SourceAdapter` | Protocol: `discover()` / `fetch_changes(cursor)` / `checkpoint()` |
| `ChangeEvent` | Envelope — `source_id`, `provider`, `kind`, `revision`, `observed_at`, `payload`; canonical serialization + `event_hash` |
| `Cursor` / `FetchResult` | Opaque resume token (base64 canonical JSON) and poll output |
| `GitAdapter` | `git log` via subprocess; revision = commit sha; incremental = `<sha>..HEAD` |
| `ObsidianVaultAdapter` | Polling; detection = content sha256 with `mtime_ns` recorded; title = frontmatter → H1 → stem |
| `FileServerAdapter` | Mounted SMB/NFS/SFTP/cloud-sync directory; content SHA-256, add/change/delete tombstones, OS-managed credentials |
| `S3Adapter` | AWS S3/R2/MinIO metadata polling through a boto3-compatible read-only client; ETag/version revisions, no object bytes |
| `Freshness` | Tiers F0–F3, SLO constants, `evaluate_freshness` / `classify_lag` |

## Design decisions

* **Determinism over convenience.** Payloads are normalized (sorted keys, UTC
  ISO-8601 timestamps, sets sorted) before hashing. Two adapters observing the
  same change produce byte-identical envelopes, which is what makes
  deduplication and provenance chains trustworthy.
* **Cursors are opaque and portable.** A cursor encodes to one string so a
  scheduler can store it between runs — migration `0033_source_adapter_cursors`
  is where they persist. Adapters reject cursors from another provider/source.
* **Broken history fails loudly.** If git's cursor sha is no longer in the
  repository, `fetch_changes` raises `GitCursorInvalid` instead of silently
  re-syncing or silently skipping.
* **Obsidian deletion needs no filesystem events.** The cursor carries the full
  previous snapshot, so a plain poll reports adds, edits *and* deletions.
* **File-server credentials do not enter TAVONEL.** SMB/NFS/SFTP authentication
  belongs to the operating-system mount. Symlinks are not followed, source
  files are never modified, and scan/file-size limits fail closed.
* **S3 is metadata-first and provider-neutral.** The adapter accepts a
  boto3-compatible client created by the operator's secret store and requests
  `ListBucket` only. AWS S3, Cloudflare R2 and MinIO use the same contract;
  customer object bytes are fetched only by a separately authorized intake
  stage.

## Freshness tiers

| Tier | Meaning | SLO |
| --- | --- | --- |
| F0 | realtime | ≤ 60 s lag |
| F1 | hourly | ≤ 3 600 s |
| F2 | daily | ≤ 86 400 s |
| F3 | archive | ≤ 604 800 s |

Provider defaults: `git` → F2; `obsidian`, `file_server`, and `s3` → F1
(operator-overridable per source).
