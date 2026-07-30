# Security Threat Model

- Version: 1.0.0
- Review date: 2026-07-29
- Scope: web/control plane, object storage, queues, CPU/GPU workers, model
  supply chain, exports, analytics, and administrative operations
- Method: asset/trust-boundary review plus STRIDE

## Security objectives

1. A tenant can access only its authorized projects and objects.
2. Untrusted documents cannot execute code, reach internal networks, or control
   model/system behavior.
3. Customer content is private by default and never used for training without
   explicit consent.
4. Processing and billing remain idempotent under retry, duplication, and
   partial failure.
5. Every accepted block and generated claim has verifiable provenance.
6. Deletion, retention, model revision, and external transmission are auditable.

## Assets

- original and derived customer documents;
- account, membership, project, and billing records;
- credit ledger and payment references;
- source maps, review edits, and consent records;
- scoped storage grants, API keys, signing keys, and provider credentials;
- model weights, custom code, containers, manifests, and license snapshots;
- audit events, benchmark holdouts, and opt-in training pools.

## Trust boundaries

```text
Browser
  | public TLS/auth boundary
Control Plane API ── PostgreSQL/RLS
  | scoped object grants       | queue credentials
Quarantine/Object Storage      Redis/Queue
  | verified-object boundary   |
CPU Workers                    GPU Provider Boundary
  |                            |
Derived Storage <──── signed result manifest
  |
Export Download Boundary
```

Administrative access, CI/release, optional external Precision APIs, and
training-data export are separate privileged boundaries.

## Principal threats and controls

| Threat                  | Example                                              | Required controls                                                                                                                                                                             | Verification                                                  |
| ----------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Spoofing                | stolen session/API key                               | OIDC validation, MFA for Team/Enterprise, scoped keys, rotation, short sessions                                                                                                               | `test_oidc_mfa_auth.py`, auth contract, and key-scope tests   |
| Tenant confusion        | IDOR/BOLA or object-prefix swap                      | RLS, tenant in every key, server-side authorization, unguessable IDs, deny-by-default object policy                                                                                           | cross-tenant test suite                                       |
| Upload smuggling        | extension/MIME mismatch                              | allowlist, magic bytes, quarantine, ClamAV, archive limits                                                                                                                                    | hostile synthetic fixtures                                    |
| Parser escape           | malformed PDF/OOXML exploit                          | rootless isolated process, read-only FS, no network, seccomp/AppArmor, CPU/memory/time limits                                                                                                 | sandbox and timeout tests                                     |
| Archive bomb            | oversized expansion                                  | compressed/uncompressed/entry/depth/ratio caps                                                                                                                                                | synthetic bounded bomb fixture                                |
| SSRF                    | URL redirect or DNS rebinding to metadata/private IP | Feature flag, isolated least-privilege worker, public-443-only egress with private/link-local/metadata exclusions, DNS/IP validation and pinning on every hop, no ambient compute credentials | redirect/DNS-rebinding tests and deployment-policy validation |
| Presigned URL theft     | URL copied from logs                                 | short TTL, method/key/content constraints, HTTPS, redaction, one-job prefix                                                                                                                   | log scan and scope test                                       |
| Prompt injection        | document asks model to reveal data/use tools         | document content as untrusted data, no tools, fixed schema, output sanitizer, evidence validator                                                                                              | injection corpus                                              |
| Generated XSS           | script/link in Markdown/SVG                          | sanitizer, URL-scheme allowlist, CSP, download isolation                                                                                                                                      | browser security tests                                        |
| Queue tampering         | forged callback/result                               | signed job manifest, request hash, idempotency key, exact tenant/prefix, result checksum                                                                                                      | duplicate/forged completion tests                             |
| Replay/double charge    | duplicate submit/completion                          | append-only ledger, control-plane idempotency, request hash conflict, deterministic result ID                                                                                                 | property/chaos tests                                          |
| Supply-chain compromise | changed model revision or pickle                     | exact SHA, license snapshot, SBOM, network-denied import, pickle scan, signed image, self-test                                                                                                | model CI                                                      |
| Model exfiltration      | external fallback silently enabled                   | external flags false, per-job consent, egress allowlist, private-mode deny                                                                                                                    | policy tests                                                  |
| Data in logs            | source text or images in traces                      | structured allowlisted fields, content redaction, telemetry schema review                                                                                                                     | sampled log audit                                             |
| Admin abuse             | bulk export/delete                                   | least privilege, step-up auth, dual approval for mass actions, immutable audit                                                                                                                | admin-action audit                                            |
| Retention failure       | stale source/backups/training row                    | lifecycle jobs, deletion receipts, backup expiry, consent lineage                                                                                                                             | mass-delete and restore drills                                |
| Availability            | provider/Redis/DB outage                             | retry budgets, circuit breakers, DLQ, fair queue, PITR, provider fallback                                                                                                                     | chaos/load exercises                                          |
| Corpus leakage          | holdout included in training                         | separate buckets/roles, immutable dataset lineage, split hash checks                                                                                                                          | benchmark CI                                                  |

## GPU worker constraints

- No public ingress other than the provider job interface.
- No tenant-wide or permanent storage credential.
- Input/output are bounded, scoped object grants with allowlisted hosts.
- Scratch directories are per-job and destroyed after completion.
- Model loads once; exact revision and image digest appear in every result.
- Remote code is disabled unless reviewed, pinned, and isolated.
- Partial or timed-out output is never accepted as a complete result.
- HPD and Unlimited workers refuse work unless their experimental flag is
  explicitly enabled.

## Privacy and training

Operational storage, analytics, review data, benchmark corpora, and training
pools are separate purposes and stores. Moving data between them requires a
consent record, rights check, PII/secret rescan, de-identification, retention
deadline, and lineage record. Enterprise tenants are always excluded unless a
separate contract says otherwise.

## Residual risk and launch blockers

Release is blocked by any unresolved cross-tenant path, parser escape, unknown
model/license, silent external transmission, unaudited mass deletion, missing
restore evidence, or unsupported generated claim in an accepted export.

Risk acceptance requires owner, rationale, compensating control, expiry, and an
issue reference. Permanent risk waivers are not permitted.
