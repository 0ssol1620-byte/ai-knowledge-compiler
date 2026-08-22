# R2 Storage Provisioning — `tavonel-dev-storage`

- **Date:** 2026-08-23 (KST)
- **Scope:** Cloudflare R2 bucket provisioned and verified for the tavonel dev
  environment (frontend asset / storage backend).
- **Method:** S3-compatible API via `boto3` (run with `uv run --with boto3`).
- **Provenance:** credentials were read from the local secrets file at runtime
  and consumed **as environment variables only**. No secret value appears in
  this document, in command output, or in git history.

## Bucket

| Field | Value |
| --- | --- |
| Bucket name | `tavonel-dev-storage` |
| Pre-existence | Did **not** exist (account listed 4 buckets: `structara-prod-audit`, `structara-prod-derived`, `structara-prod-originals`, `structara-prod-working`) |
| Action | `create_bucket` → `head_bucket` returned 200 |

## Endpoint form

Per the credential source's jurisdiction guidance, S3 clients must target the
account-scoped endpoint:

```
https://<ACCOUNT_ID>.r2.cloudflarestorage.com
```

Client requirements (verified working):

- `endpoint_url` = the account-scoped URL above
- `region_name` = `auto`
- signature version `s3v4`
- path-style addressing (`Config(s3={"addressing_style": "path"})`)

## Credential handling

All four values (Account ID, API Token, Access Key ID, Secret Access Key) are
parsed from the local secrets file and exported to environment variables
(`R2_ACCOUNT_ID`, `R2_API_TOKEN`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`)
before the boto3 client is constructed. Values are never printed, logged, or
committed. The Access Key pair used is the **Account API Token** set (not the
User API Token set).

## CORS configuration

Applied with `put_bucket_cors` and re-read with `get_bucket_cors`:

```json
[
  {
    "AllowedOrigins": [
      "http://localhost:3000",
      "http://localhost:3010",
      "https://*.vercel.app"
    ],
    "AllowedMethods": ["GET"],
    "AllowedHeaders": ["*"],
    "MaxAgeSeconds": 3600
  }
]
```

Read-only `GET` only; write paths must go through the server-side API.

## Verification results

1. **Bucket list** — `list_buckets` succeeded; `tavonel-dev-storage` absent
   before, present after creation.
2. **1 KiB round-trip** — 1024 random bytes uploaded to
   `_probe/r2-roundtrip-1787432485.bin`, then downloaded:

   | Check | Result |
   | --- | --- |
   | Uploaded size | 1024 bytes |
   | Downloaded size | 1024 bytes |
   | SHA-256 (source) | `5922daf808821dcb114b410cda54ac3d27b42f1a6498c3ce978d4d7924395fe2` |
   | SHA-256 (fetched) | `5922daf808821dcb114b410cda54ac3d27b42f1a6498c3ce978d4d7924395fe2` |
   | Match | **true** |

3. **Cleanup** — `delete_object` succeeded; follow-up `head_object` returned
   `404` (probe object removed).
4. **CORS** — `put_bucket_cors` succeeded; `get_bucket_cors` returned the rule
   set shown above verbatim.

## Reproduction

```bash
uv run --with boto3 python <script>.py
# script: parse secrets file -> os.environ -> boto3 client (endpoint above)
#         -> list_buckets / create_bucket / put+get+delete_object / put+get_bucket_cors
```

Secrets must continue to be injected from the local secrets file into the
process environment; they must not be embedded in scripts, CI files, or docs.
