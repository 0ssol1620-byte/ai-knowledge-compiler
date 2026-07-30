# Payment and credit integrity

This control plane records payment evidence and grants credits without calling
an external payment API. A provider connector may create or host checkout
sessions outside this process, but the only authority accepted by the credit
ledger is a verified, durable payment event.

## Safety boundary

- Production starts with `AKC_PAYMENTS_ENABLED=false` and
  `AKC_PAYMENT_PROVIDER=disabled`.
- `fake` is a no-network development/test adapter and is rejected when
  `AKC_ENV=production`.
- An enabled production `merchant` handoff requires
  `AKC_PAYMENT_MERCHANT_ID` and a dedicated
  `AKC_PAYMENT_WEBHOOK_SECRET` containing at least 32 bytes.
- The API never accepts price, currency, or credit quantity from a checkout
  caller. `pack_code` selects a server-owned catalogue entry.
- Monetary amounts are positive JSON integers in provider minor units. KRW and
  USD are the only currencies enabled by the initial catalogue. Floats,
  lowercase codes, unsupported currencies, and amount/currency mismatches are
  rejected before credit authority is granted.
- Webhook payloads use a closed schema. Card data, customer email, and arbitrary
  provider metadata are neither accepted nor persisted.

## Purchase sequence

1. A verified tenant owner, admin, or billing member sends
   `POST /v1/billing/checkouts` with an `Idempotency-Key` and a `pack_code`.
2. The API persists a tenant-scoped checkout with the server-side amount,
   currency, and credits. The fake adapter returns only a local URL; the
   merchant adapter leaves the checkout in `provider_pending`.
3. The provider sends a signed `payment.succeeded` event.
4. The event is inserted into `payment_events` before processing. The unique
   `(provider, provider_event_id)` key prevents replay, while the payload digest
   rejects event-ID collisions.
5. Exact amount and currency matching creates or confirms one canonical
   `payments` row.
6. A unique `credit_grants` row links that payment to one `credit_ledger`
   `grant` operation. Database uniqueness and the ledger operation key make
   repeated or differently identified success events harmless.

`credit_grants` and `credit_reversals` have database append-only guards in
PostgreSQL and SQLite migrations. Application code never updates or deletes
either evidence table.

## Webhook authentication and replay prevention

Providers send:

```text
X-Payment-Timestamp: <unix seconds>
X-Payment-Signature: v1=<lowercase HMAC-SHA256 hex>
```

The signed message is the ASCII timestamp, a period, and the exact request
body:

```text
HMAC-SHA256(secret, timestamp + "." + raw_body)
```

The API compares signatures in constant time, accepts timestamps only within
`AKC_PAYMENT_WEBHOOK_TOLERANCE_SECONDS`, caps the body at
`AKC_PAYMENT_WEBHOOK_MAX_BYTES`, rejects duplicate JSON keys, and persists a
SHA-256 payload digest. Do not transform or reserialize the body between
signing and delivery.

Example event:

```json
{
  "id": "evt_01",
  "type": "payment.succeeded",
  "created": 1785300000,
  "data": {
    "tenant_id": "00000000-0000-0000-0000-000000000001",
    "checkout_id": "00000000-0000-0000-0000-000000000002",
    "payment_id": "pay_01",
    "amount_minor": 4900,
    "currency": "KRW"
  }
}
```

Supported types are `checkout.expired`, `payment.succeeded`,
`payment.failed`, `payment.refunded`, `payment.dispute.opened`,
`payment.dispute.won`, and `payment.dispute.lost`. Unknown, structurally valid
types are retained as `ignored` without obtaining financial authority.

## Refund and dispute accounting

Refund credit calculations use cumulative provider minor units. Each partial
refund receives only the difference between the new cumulative target and
credits already assigned; a full refund receives the exact remaining credits.
The sum of successful refunds and lost disputes cannot exceed the original
payment amount.

Credits are fungible, but account invariants are not relaxed:

- a refund or chargeback never makes `credit_accounts.balance` negative;
- active job or dispute reservations remain protected;
- the immediately recoverable amount is appended to `credit_ledger` as an
  `adjust` entry;
- any unrecoverable amount is retained in an append-only `credit_reversals`
  row as `unrecovered_after`;
- later reconciliation can recover newly available credits with a separate
  `debt_recovery` row, preserving the complete adjustment history.

An opened dispute reserves only available credits. A won dispute releases that
hold. A lost dispute converts the held portion to an adjustment and attempts
to recover any uncovered remainder without consuming unrelated reservations.
Provider-created timestamps prevent an older `opened` event from regressing a
terminal dispute state.

## Reconciliation and DLQ

`POST /v1/billing/reconciliations` performs a bounded, tenant-scoped pass:

- retries due inbox events in provider-created order;
- moves permanent failures or exhausted retries to `dead_letter`;
- repairs a settled payment missing its unique credit grant when authoritative
  success evidence exists;
- reapplies pending out-of-order refunds and disputes;
- recovers outstanding refund or chargeback adjustments only from currently
  available credits;
- writes a `payment_reconciliations` result and an audit event.

Operators can inspect `GET /v1/billing/payment-events?status=dead_letter` and
explicitly retry a row with
`POST /v1/billing/payment-events/{event_id}/retry`. Retrying is itself
idempotent and audited. Never edit inbox payloads, grants, reversals, or ledger
rows to clear an incident.

Schedule the reconciliation endpoint at
`AKC_PAYMENT_RECONCILIATION_INTERVAL_SECONDS` using a narrowly scoped tenant
API key with the `billing` role. Use a fresh idempotency key per scheduled
window. Alert on:

- any `PAYMENT_WEBHOOK_EVENT_ID_COLLISION`;
- repeated signature/timestamp failures;
- `dead_letter` growth;
- nonzero reconciliation mismatches or outstanding credits;
- duplicate-payment volume.

## Deployment checklist

1. Apply migration `0009_payment_credit_purchase` after
   `0008_global_mutation_idempotency`.
2. Keep the base deployment disabled until the merchant connector is ready.
3. Inject merchant identity and webhook HMAC secret from the secret manager.
4. Register the exact HTTPS webhook route
   `/v1/payments/webhooks/merchant` with the provider connector.
5. Confirm the connector includes the local tenant and checkout IDs in its
   signed event metadata.
6. Run a non-production fake-provider purchase, duplicate event, out-of-order
   refund, dispute, and reconciliation drill.
7. Verify alerts, DLQ inspection, and audit retention before enabling
   production checkout creation.

No GitHub token, merchant credential, webhook secret, raw payment payload, or
customer identifier may be written to logs, metrics labels, documentation
examples, or idempotency keys.
