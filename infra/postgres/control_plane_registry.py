"""The approved Control Plane Authorization Boundary.

A worker's queue poll has no tenant until a row is read, so the claim step is
cross-tenant by construction. Today the seven worker roles buy that reach with
``BYPASSRLS``, which is not a boundary — it is the absence of one, and it
applies to all 112 tables rather than to the handful the claim actually needs.

This file is the replacement: the explicit list of tables a control-plane role
may read across tenants, what it may do there, and why. It is not a security
exception. It is a named boundary with an owner, and CI fails when the live
catalog disagrees with it — which is what stops an eighth table from arriving
without anybody deciding to admit it.

**What may go in here.** Control-plane metadata only: job discovery, scheduling,
claiming, leasing, retention. Customer document bodies, compiled knowledge,
evidence payloads and secrets may not, and
``docs/audit/V5_CONTROL_PLANE_BOUNDARY.md`` records the column-by-column
examination behind each entry — including the three columns that are carried
under protest and the reason the grant has not yet been narrowed to exclude
them.

**Adding a table is a founder decision, not a migration detail.** Grant a
control-plane role a table that is not listed and the schema security gate
fails with the table's name.
"""

from __future__ import annotations

from typing import Final

#: The role whose cross-tenant reach this boundary describes — and the only one.
#:
#: **The other six worker roles have no bounded cross-tenant capability yet, and
#: therefore cannot poll their queues once ``BYPASSRLS`` is removed.** Measured:
#: an armed ``akc_url_fetcher`` reads zero rows from ``url_fetch_tasks`` with or
#: without a declaration, because the only permissive policy there requires a
#: tenant and a queue poll has none. That is fail-closed, and it is also a
#: prerequisite for step 8 rather than a finished state — see
#: ``docs/audit/V5_WORKER_AUTHZ_ARMING.md`` A-6.
#:
#: Admitting another role is a founder decision. The boundary the founder
#: approved is the scheduler's, and widening it here unilaterally is the exact
#: move this file exists to make impossible.
CONTROL_PLANE_ROLE: Final = "akc_scheduler"

#: Table -> why the scheduler must see it without a tenant.
#:
#: Derived from the live catalog at ``0033_backfill_checkpoint_tenant_rls`` — it
#: is exactly the set of tables ``akc_scheduler`` holds any grant on — and then
#: approved one by one. The derivation is repeated at run time rather than
#: trusted: a previous census of this schema was wrong by seven tables.
CONTROL_PLANE_TABLES: Final[dict[str, str]] = {
    "email_verification_deliveries": (
        "delivery outbox poll: due rows are selected by available_at across "
        "tenants, then retried or dead-lettered"
    ),
    "email_verification_tokens": (
        "retention: expired and consumed tokens are swept across tenants"
    ),
    "idempotency_records": (
        "retention: records past expires_at are swept across tenants"
    ),
    "job_events": (
        "retention: events past the event_retention_days cutoff are swept "
        "across tenants"
    ),
    "outbox_events": (
        "job discovery and dispatch claim: the queue ranks candidates across "
        "tenants and admits one; retention sweeps published and dead-lettered "
        "rows"
    ),
    "webhook_deliveries": (
        "delivery claim and fan-out: one batch of outbox events spans tenants, "
        "so the deliveries it produces do too; retention sweeps delivered and "
        "dead-lettered rows"
    ),
    "webhook_endpoints": (
        "fan-out target lookup: endpoints are read for the set of tenants "
        "present in the claimed batch"
    ),
}

#: The purposes a transaction may declare to obtain the cross-tenant view.
#: ``akc_security.tenant_context.CONTROL_PLANE_PURPOSES`` holds the same list on
#: the application side and the policies hold it in SQL; the three are asserted
#: equal by ``tests/security/test_control_plane_boundary.py``.
CONTROL_PLANE_PURPOSES: Final = frozenset(
    {"job_discovery", "scheduling", "claim", "lease", "retention"}
)

#: Tables carrying both ``lease_token`` and ``lease_expires_at`` — the rows a
#: worker claims and then acts on. Derived, not chosen: the claim-binding
#: policies are created for whatever the catalog says has a lease.
LEASE_TABLES: Final = frozenset(
    {
        "analysis_tasks",
        "deletion_requests",
        "gpu_provider_invocations",
        "url_fetch_tasks",
    }
)

#: The human authorization plane's runtime role. Policies target it directly.
#: Every runtime login role in this repository is ``NOINHERIT`` and reaches its
#: identity through ``SET ROLE``, and ``pg_policy.polroles`` does not reach a
#: ``NOINHERIT`` member of a group — measured in
#: ``docs/audit/V5_WORKER_AUTHZ_SPIKE.md`` (D). Group targeting would land a
#: policy that silently matches nobody.
HUMAN_PLANE_ROLE: Final = "akc_api_plane"

#: The login principal that assumes ``HUMAN_PLANE_ROLE``. Separate object, so
#: the credential that authenticates is not the identity that authorizes.
HUMAN_PLANE_LOGIN_ROLE: Final = "akc_api_runtime"

#: Columns inside the boundary that hold customer-controlled or secret material.
#: They are not tenant data-plane *content* — no document body, no compiled
#: knowledge, no evidence payload — but they are the closest thing to it inside
#: the boundary, and narrowing the grants to exclude them requires changing what
#: the scheduler selects. Recorded so the gate can assert the list has not grown
#: rather than leaving it in prose. See V5_CONTROL_PLANE_BOUNDARY.md section 3.
CONTROL_PLANE_SENSITIVE_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "email_verification_deliveries": ("encrypted_payload", "recipient_pseudonym"),
    "email_verification_tokens": ("token_hash",),
    "idempotency_records": ("response_body", "response_body_ciphertext"),
    "job_events": ("payload",),
    "outbox_events": ("payload",),
    "webhook_deliveries": ("payload",),
    "webhook_endpoints": ("encrypted_secret", "secret_hash", "url"),
}
