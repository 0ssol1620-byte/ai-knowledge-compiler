# OIDC and MFA security contract

This repository contains a local, testable implementation of the masterplan
21.10 authentication controls. It does not claim that a production identity
provider, redirect domain, or tenant policy has been verified.

## OIDC contract

- Authorization Code flow always uses S256 PKCE, opaque state, and nonce.
- State is stored only as a keyed digest. The PKCE verifier and nonce are
  encrypted at rest in a single-use transaction with a bounded expiry.
- A separate HttpOnly, SameSite browser-binding cookie must match the
  transaction. A valid state copied into another browser is rejected.
- Discovery must return the exact configured issuer. Discovery, authorization,
  token, and JWKS URLs must use HTTPS, contain no credentials, and use an
  allowlisted host.
- Only explicitly configured asymmetric ID-token algorithms are accepted.
  `kid`, signature, issuer, audience, expiry, issued-at, nonce, verified email,
  multi-audience `azp`, and optional `at_hash` are validated.
- JWKS documents and key counts are bounded. An unknown key triggers one
  forced refresh; ambiguous keys fail closed.
- The immutable account key is `(issuer, sub)`, never email. If an existing
  local email has no binding, OIDC login fails with
  `OIDC_ACCOUNT_BINDING_REQUIRED`. The user must begin a binding transaction
  from an authenticated, verified local session.
- Completing primary OIDC authentication rotates into a fresh session or a
  pending MFA challenge. Authorization codes, tokens, state, nonce, PKCE
  verifier, and provider secrets are never written to audit metadata.

## Team and Enterprise MFA contract

- New password, OIDC, and invitation-acceptance sessions for Team or Enterprise
  tenants cannot receive an application session until MFA succeeds.
- TOTP uses the interoperable 30-second, six-digit SHA-1 profile. Seeds are
  Fernet-encrypted at rest. The last accepted time step prevents replay.
- Enrollment is confirmed with a valid TOTP before activation.
- Ten random recovery codes are shown once. Only domain-separated HMAC
  digests are stored, and each accepted recovery code is removed atomically.
- Pending enrollment/challenge tokens are short-lived signed JWTs backed by a
  durable, single-use hashed challenge. Five failures consume the challenge.
- Recovery-code regeneration requires a fresh, non-replayed TOTP.
- Audit records contain factor method, result, IDs, counts, and issuer, but no
  factor seed, code, recovery value, OIDC token, or document content.

Existing sessions expire on the configured short session lifetime. A product
plan-change workflow must revoke or rotate pre-upgrade sessions when a tenant
is moved into a mandatory-MFA plan.

## External release gate

Before enabling `AKC_OIDC_ENABLED` in production, verify the exact IdP tenant,
issuer, confidential client, callback domain, key-rotation behavior, claims,
logout/incident process, MFA policy ownership, and recovery support with the
real provider. Record that evidence separately from the deterministic local
tests. Local mocked discovery/JWKS and locally signed JWTs prove the adapter
contract only.
