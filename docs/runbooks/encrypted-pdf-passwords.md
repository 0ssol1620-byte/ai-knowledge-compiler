# Encrypted PDF Password Handling

## Contract

An encrypted PDF password is transient processing input, never document data.
It must not be written to PostgreSQL, an object, a log, a trace, a command-line
argument, an environment variable, or a parser request file.

The API accepts the password as a redacted `SecretStr`, binds it to the exact
tenant, document, and immutable source SHA-256, and stores it for at most 15
minutes. The default is five minutes and three parser attempts. A successful
parse destroys the secret immediately. Exhaustion, deletion, replacement,
expiry, and application shutdown also destroy it.

## Runtime paths

- Development/test: `InMemoryPdfSecretStore` keeps a bounded `bytearray` and
  actively overwrites it on destruction.
- Distributed/production: `RedisPdfSecretStore` stores only Fernet-authenticated
  ciphertext under an HMAC-derived opaque key. Redis enforces TTL and performs
  the attempt increment/delete decision atomically with Lua.
- Parser sandbox: the worker acquires a short lease and sends a length-prefixed
  password through the child process stdin pipe. `request.json`, argv, and the
  sanitized child environment contain no password. The child zeroes its
  mutable buffer in `finally`.

Python and the Redis client may create short-lived immutable copies internally;
the process boundary, short TTL, no-core-dump/container policy, and immediate
reference release bound that exposure. No decrypted PDF copy is persisted.

## Required production configuration

```text
AKC_REDIS_URL=rediss://...
AKC_PDF_PASSWORD_ENCRYPTION_KEY=<Fernet key from KMS-backed secret manager>
AKC_PDF_PASSWORD_HMAC_SECRET=<independent random value, at least 32 bytes>
AKC_PDF_PASSWORD_TTL_SECONDS=300
AKC_PDF_PASSWORD_MAX_ATTEMPTS=3
```

The API and analysis worker must receive the same two PDF-secret keys through
their separate workload identities. They must not receive each other's
database credentials. Production startup fails when Redis TLS or either key is
missing.

## Operator response

| Error | Meaning | Action |
|---|---|---|
| `ENCRYPTED_PDF` | No usable password was available | Prompt the authorized editor |
| `PDF_PASSWORD_INVALID` | Parser rejected one submitted password | Let the user retry within the remaining limit |
| `PDF_PASSWORD_EXPIRED` | Secret TTL elapsed | Submit a new password |
| `PDF_PASSWORD_ATTEMPTS_EXHAUSTED` | Atomic attempt ceiling reached | Require a new submission after abuse controls |
| `PDF_SECRET_STORE_UNAVAILABLE` | Redis could not prove the secret contract | Retry; never fall back to DB/plaintext |
| `PDF_PASSWORD_CHANNEL_INVALID` | Child pipe frame was malformed | Treat as worker security failure |

Never include the submitted password in an incident ticket. Use request ID,
tenant ID, document ID, source SHA-256, task ID, error code, and attempt number.

## Verification

```powershell
.\.venv\Scripts\pytest.exe tests/unit/test_encrypted_pdf.py packages/security/tests/test_pdf_secrets.py -q
.\.venv\Scripts\ruff.exe check packages/security/src/akc_security/pdf_secrets.py services/api/src/akc_api/pdf_passwords.py workers/cpu-document/src/akc_worker_document
```

The focused suite proves correct/wrong/missing passwords, malformed stdin
frames, binding isolation, encrypted Redis state, TTL, attempt limiting,
success deletion, and active lease destruction. A production release must
also prove Redis failover behavior and secret-manager rotation in staging.
