# Collection metadata encryption migration and key rotation

This runbook moves `collection_source_roots.display_name`,
`collection_files.relative_path`, and `collection_files.display_name` from legacy
plaintext columns to tenant/collection/row-bound AES-256-GCM ciphertext. Relative
path uniqueness uses a separate HMAC-SHA-256 blind-index key scoped by tenant,
collection, and source root.

The operation is deliberately two phase. Revision `0026` is a reversible schema
bridge. The application-owned command performs and verifies encryption. Revision
`0027` refuses to remove plaintext columns until every row in every tenant is
complete. Do not run `alembic upgrade head` over a populated pre-0026 database in
one unattended step.

## Preconditions and hard stops

1. Verify a restorable database backup and PostgreSQL PITR/WAL recovery point.
   Record that evidence outside this repository. A successful local test is not
   production backup evidence.
2. Disable every collection source/file metadata mutation and drain in-flight
   collection intake. The backfill's PostgreSQL advisory lock serializes backfill
   operators; it does not fence API writers. SQLite must be offline for apply and
   finalization.
3. Make the release image and its backfill command available to operators, but
   do not route collection traffic to the new ciphertext-only application yet.
   Keep retrieval/finalizer flags disabled and the old application's collection
   writes fenced. Do not enable a mixed plaintext/ciphertext production writer.
4. Provide these values through the external Secret provider, never CLI flags,
   shell history, logs, ConfigMaps, or committed `.env` content:

   - `AKC_COLLECTION_METADATA_ENCRYPTION_ENABLED=true`
   - `AKC_COLLECTION_METADATA_ACTIVE_KEY_ID=<bounded-key-id>`
   - `AKC_COLLECTION_METADATA_KEYRING=<JSON object of base64: AES-256 keys>`
   - `AKC_COLLECTION_METADATA_BLIND_INDEX_KEY_ID=<bounded-key-id>`
   - `AKC_COLLECTION_METADATA_BLIND_INDEX_KEY=<independent 32+ byte secret>`

5. Confirm the decrypt keyring contains the active key and every historical key
   still present in `metadata_key_id`. The blind-index secret is independent of
   every AEAD key.
6. Run the command with the approved migration/backfill database role. Confirm
   the serving application role has no `INSERT`, `UPDATE`, or `DELETE` grant on
   `collection_metadata_backfill_checkpoints`; revision 0026 revokes all PUBLIC
   access. A serving role must not be able to forge finalization evidence.

Stop if a command reports an authenticated-decryption mismatch, an unrecoverable
row, or a normalized blind-index collision. The command never prints a source
name, filename, relative path, ciphertext, or key material; do not add SQL or
debug logging that does.

## Phase 1: bridge, dry-run, apply, verify

Upgrade only to the bridge revision:

```powershell
.\.venv\Scripts\alembic.exe upgrade 0026_collection_metadata_encryption_bridge
```

Enumerate tenant UUIDs from the authoritative tenant registry. Process one tenant
at a time; never remove `--tenant-id`. A dry-run reads in bounded pages, verifies
existing ciphertext where present, computes all normalized path indexes in
memory, and fails before writes on a collision:

```powershell
.\.venv\Scripts\python.exe scripts\backfill_collection_metadata.py `
  --tenant-id 00000000-0000-0000-0000-000000000000 `
  --batch-size 200 `
  --dry-run
```

`finalization_ready=false` is expected for a tenant that still has plaintext-only
rows. Review only the count fields and key IDs in the JSON result. Then apply:

```powershell
.\.venv\Scripts\python.exe scripts\backfill_collection_metadata.py `
  --tenant-id 00000000-0000-0000-0000-000000000000 `
  --batch-size 200 `
  --apply
```

Each batch updates ciphertext/index fields and its cursor in the same transaction.
`collection_metadata_backfill_checkpoints` stores only tenant/key IDs, UUID
cursors, counts, status, and timestamps. If the process stops, rerun the exact
apply command with the same key IDs; status `applying` resumes after the last
committed root/file cursor. A changed active or blind-index key resets the tenant
scan intentionally. A completed same-key apply is idempotent and reports zero
rewritten rows.

Run an explicit authenticated verification after every tenant:

```powershell
.\.venv\Scripts\python.exe scripts\backfill_collection_metadata.py `
  --tenant-id 00000000-0000-0000-0000-000000000000 `
  --batch-size 200 `
  --verify
```

The verifier requires:

- every AEAD field to decrypt under its exact tenant/collection/root/file AAD;
- decrypted data to equal legacy plaintext while the bridge columns exist;
- every encryption key ID to equal the configured active key;
- every blind index and blind-index key ID to equal the configured current value;
- zero normalized path collisions within each tenant/collection/source-root scope.

Repeat dry-run/apply/verify for every tenant. Do not infer global readiness from a
sample or from checkpoint rows alone.

## Phase 2: fail-closed plaintext removal

With the write fence still active, take a second backup/recovery point. Apply the
final revision:

```powershell
.\.venv\Scripts\alembic.exe upgrade 0027_finalize_collection_metadata_encryption
```

Revision 0027 performs a global coverage assertion before any destructive DDL.
It then removes the three legacy plaintext columns, makes the encrypted fields
non-null, and installs key/index checks. If any tenant was missed, it stops before
column removal. Resolve the missed tenant at revision 0026 and rerun the gate.

Verify the deployed schema has no legacy columns and that the application API can
round-trip authorized source/file responses. Confirm events, analytics, logs,
traces, metrics, and idempotency storage contain no plaintext metadata. Only after
that evidence is recorded may the metadata encryption flag be enabled in the
production workload. Semantic retrieval and the collection finalizer must be
enabled atomically only after metadata encryption is enabled.

After this metadata-specific gate passes, apply any reviewed later migration
revisions (currently 0028 and beyond) in their documented order before opening
traffic; do not collapse the populated-database 0026/backfill/0027 boundary into
an unattended `upgrade head`.

Backups, replicas, WAL archives, snapshots, and exported diagnostics created
before 0027 may still contain legacy plaintext. Expiration or cryptographic erase
of those copies is a separate, externally evidenced retention operation.

## Encryption-key rotation

1. Keep the old key in the decrypt keyring, add the new 32-byte AES key, and set
   only the new key ID active.
2. Fence collection metadata writes.
3. Run `--dry-run`, `--apply`, and `--verify` for every tenant. Apply decrypts old
   ciphertext and re-encrypts with randomized AES-GCM under the new active key.
4. Query only aggregate key-ID counts and require zero rows using the old key.
5. Take and verify a recovery point, deploy the reduced keyring, then remove the
   old external Secret version according to the approved retention policy.

Never remove an old decrypt key before all tenant verifiers pass.

## Blind-index-key rotation

A blind-index key change is a full reindex, not a rolling dual-index operation.
Keep the collection write fence for the entire multi-tenant run. Configure the new
blind-index key ID/secret, keep all AEAD decrypt keys, and run dry-run/apply/verify
for every tenant. The unique index remains tenant/collection/source-root scoped;
any NFC/case-fold collision stops before updates. Enable writers only after every
tenant reports `finalization_ready=true` with the new blind-index key ID.

## Rollback boundaries

- Before apply, 0026 may be downgraded only when no encrypted or
  ciphertext-only rows exist.
- After apply, do not use 0026 downgrade. Restore the verified pre-migration
  backup if the encrypted application cannot be deployed.
- A 0027 downgrade recreates nullable bridge plaintext columns but deliberately
  does not decrypt data back into them. The application remains ciphertext-only.
- Never copy decrypted metadata into SQL, logs, incident tickets, or migration
  output as a rollback technique.

Production completion remains blocked until managed PostgreSQL execution, Secret
provider injection, backup/PITR proof, per-tenant reports, post-deploy canary, and
rollback rehearsal are captured as external evidence.
