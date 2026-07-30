# Free-tier abuse and email-verification controls

Public registration is an untrusted boundary. A newly created account has no
processing authority and receives no free credits until a single-use email
verification token is consumed successfully.

## Security invariants

- Verification token plaintext is never stored in a database column or written
  to logs. The token table stores only a purpose-bound HMAC-SHA-256 digest.
- Delivery payloads are held in a transactional outbox encrypted with Fernet.
  The recipient stored beside the payload is an HMAC pseudonym, not an email
  address.
- Development/test may use a bounded in-memory capture provider. Production
  public registration rejects capture or disabled delivery providers.
- A verification token has a short expiry and one terminal consumption time.
  Database row locking and the unique credit-ledger operation key make the free
  grant exactly once, including concurrent requests.
- Resend responses are identical whether the account is missing, verified, or
  pending. Verification failures do not distinguish malformed, expired,
  invalidated, or replayed tokens.
- Live browser tests may consume a capture token through
  `/__test__/verification-token` only when `AKC_ENV=test`, a dedicated support
  key is configured, and capture delivery is active. The route is excluded
  from OpenAPI and does not exist in development or production.
- Raw IP addresses and account identifiers are never rate-limit keys. Requests
  are reduced to purpose-bound HMAC pseudonyms first.
- Forwarding headers are ignored unless the direct peer belongs to an explicit
  trusted-proxy CIDR. A malformed trusted chain falls back to the direct peer.
- Redis is the sole production rate-limit authority. Redis errors fail closed;
  the bounded in-memory implementation is development/test only.
- Risk-triggered CAPTCHA has no success bypass. Missing, rejected, or
  unavailable provider verification blocks the risky request.
- Every free tenant has atomic UTC-daily file, page, and estimated GPU-cost
  reservations. Exact operation keys prevent retry double-counting.
- A source SHA-256 may claim free processing only once per tenant. Repeated
  documents are blocked before a second expensive processing run.
- Free compile jobs use the bounded low-priority queue class. Paid/default work
  retains the normal priority.

## Request controls

| Boundary     | Pseudonymous dimensions       | Enforcement                                                                 |
| ------------ | ----------------------------- | --------------------------------------------------------------------------- |
| Registration | client and normalized account | velocity limit, risk CAPTCHA                                                |
| Login        | client and normalized account | velocity limit, risk CAPTCHA                                                |
| Resend       | client and normalized account | enumeration-safe velocity limit, risk CAPTCHA                               |
| Verify       | client                        | velocity limit, opaque failure                                              |
| Upload       | tenant and account            | velocity limit, verified-email gate, daily file cap                         |
| Analyze      | tenant and account            | velocity limit, verified-email gate, tenant hash claim, daily page cap      |
| Compile      | tenant and account            | velocity limit, verified-email gate, daily GPU-cost cap, low queue priority |
| Export       | tenant and account            | velocity limit, verified-email gate                                         |

HTTP hard limits use status `429`, the normal API error envelope, and a
`Retry-After` response header. Backend-unavailable decisions never silently
fall back to an allow.

## Operational signals

`akc_abuse_control_decisions_total{control,result}` is deliberately
low-cardinality. Both labels use fixed allowlists. Tenant IDs, account
pseudonyms, IP pseudonyms, source hashes, email addresses, and tokens must not
be added as labels.

Authenticated denials also create audit events containing only the bounded
control, result, cap dimension, and relevant object identifier already visible
to that tenant. Audit metadata must not contain raw client addresses,
verification tokens, email delivery payloads, or CAPTCHA responses.

## Incident response

1. Treat a rate-limit backend outage as an availability incident; do not enable
   an in-memory production fallback.
2. Rotate the verification HMAC secret to invalidate all outstanding links.
   Rotate the delivery encryption key only with a migration/re-encryption plan,
   because pending outbox rows require the old key.
3. Rotate the identity HMAC secret only when the temporary loss of historical
   velocity correlation is acceptable.
4. If the email provider is unavailable, leave encrypted outbox items pending
   for bounded retry. Never mark them delivered optimistically.
5. Investigate abuse through bounded aggregate metrics and authorized audit
   records. Do not add raw identifiers to dashboards or logs.
