"""Shadow validation for the dual-plane authorization boundary (0034).

**Why a separate harness.** The policies added by
``0034_dual_plane_authorization`` cannot be observed through the roles that will
eventually run under them. A ``BYPASSRLS`` role sees every row by definition, so
asking it what a policy does returns the same answer whether the policy is
correct, wrong, or absent. That is why the boundary work shipped inert and why
proving it needs two passes rather than one:

* **inert** — as the real worker roles, with ``BYPASSRLS`` exactly as it ships,
  the visible row set is unchanged. This is the claim that matters for landing:
  nothing that runs today behaves differently.
* **armed** — the same roles with ``BYPASSRLS`` removed *in a throwaway
  cluster*, which is the only way the policies become observable at all. The
  repository ships no change that removes the attribute; this harness flips it,
  measures, and flips it back, and refuses to run against anything but a
  loopback database it was pointed at deliberately.

The human plane needs no shadow: ``akc_api_plane`` is ``NOBYPASSRLS`` from
birth, so what this measures for it is the real thing.

    AKC_CI_ADMIN_DATABASE_URL=postgresql://... python \\
        infra/postgres/shadow_validate_dual_plane.py

Exits non-zero and names the case when an expectation does not hold.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import asyncpg  # type: ignore[import-untyped]

WORKER_ROLES = (
    "akc_analysis_worker",
    "akc_deletion_worker",
    "akc_dispatch_worker",
    "akc_gpu_worker",
    "akc_payment_worker",
    "akc_scheduler",
    "akc_url_fetcher",
)
HUMAN_PLANE_ROLE = "akc_api_plane"
HUMAN_PLANE_LOGIN_ROLE = "akc_api_runtime"


class ShadowFailure(AssertionError):
    """A shadow expectation did not hold."""


@dataclass
class Report:
    passed: list[str] = field(default_factory=list)

    def ok(self, case: str, detail: str) -> None:
        self.passed.append(case)
        print(f"  [{case}] {detail}")

    def require(self, case: str, condition: bool, detail: str) -> None:
        if not condition:
            raise ShadowFailure(f"[{case}] {detail}")
        self.ok(case, detail)


def _admin_url() -> str:
    value = os.environ.get("AKC_CI_ADMIN_DATABASE_URL", "")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.path.strip("/")
    ):
        raise RuntimeError("shadow validation requires an explicit loopback URL")
    return value


def _parts(url: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 5432,
        "database": parsed.path.strip("/"),
    }


@dataclass(frozen=True)
class Fixture:
    tenant: uuid.UUID
    user: uuid.UUID
    project: uuid.UUID
    document: uuid.UUID
    stale_document: uuid.UUID
    job: uuid.UUID
    task: uuid.UUID
    stale_task: uuid.UUID
    lease: uuid.UUID
    stale_lease: uuid.UUID
    outbox: uuid.UUID
    collection: uuid.UUID


async def _seed(admin: asyncpg.Connection[asyncpg.Record], label: str) -> Fixture:
    now = datetime.now(UTC)
    ids = {name: uuid.uuid4() for name in Fixture.__dataclass_fields__}
    fixture = Fixture(**ids)  # type: ignore[arg-type]
    await admin.execute(
        """
        INSERT INTO tenants (
            id, slug, name, plan_code, region, data_retention_days, private_mode,
            external_transfer_allowed, training_opt_in, preview_pii_masking,
            created_at, updated_at
        ) VALUES ($1, $2, $3, 'free', 'ap-northeast', 7, true, false, false, true, $4, $4)
        """,
        fixture.tenant, f"shadow-{label}-{fixture.tenant.hex}", f"shadow {label}", now,
    )
    await admin.execute(
        """
        INSERT INTO users (id, email, password_hash, display_name, is_active, created_at)
        VALUES ($1, $2, 'x', $3, true, $4)
        """,
        fixture.user, f"{fixture.user.hex}@shadow.invalid", f"shadow {label}", now,
    )
    await admin.execute(
        "INSERT INTO memberships (tenant_id, user_id, role, created_at) "
        "VALUES ($1, $2, 'owner', $3)",
        fixture.tenant, fixture.user, now,
    )
    await admin.execute(
        """
        INSERT INTO projects (
            id, tenant_id, name, output_profile, classification, created_by,
            created_at, updated_at
        ) VALUES ($1, $2, $3, '{}', 'internal', $4, $5, $5)
        """,
        fixture.project, fixture.tenant, f"shadow {label}", fixture.user, now,
    )
    await admin.execute(
        """
        INSERT INTO project_memberships (
            tenant_id, project_id, user_id, role, granted_by, created_at, updated_at
        ) VALUES ($1, $2, $3, 'editor', $3, $4, $4)
        """,
        fixture.tenant, fixture.project, fixture.user, now,
    )
    for document in (fixture.document, fixture.stale_document):
        await admin.execute(
            """
            INSERT INTO documents (
                id, tenant_id, project_id, title, document_type, language_codes,
                active_version, cir_schema_version, status, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'report', '[]', 1, '1.0', 'ready', $5, $5)
            """,
            document, fixture.tenant, fixture.project, f"shadow {label}", now,
        )
    await admin.execute(
        """
        INSERT INTO processing_jobs (
            id, tenant_id, project_id, job_type, status, priority,
            requested_options, progress, cost_estimate, cost_actual,
            event_sequence, created_at
        ) VALUES ($1, $2, $3, 'compile', 'queued', 5, '{}', '{}', '{}', '{}', 0, $4)
        """,
        fixture.job, fixture.tenant, fixture.project, now,
    )
    await admin.execute(
        """
        INSERT INTO job_events (
            id, tenant_id, job_id, sequence, event_type, schema_version,
            payload, occurred_at
        ) VALUES ($1, $2, $3, 1, 'job.queued.v1', '1.0', '{}', $4)
        """,
        uuid.uuid4(), fixture.tenant, fixture.job, now,
    )
    for task_id, document, lease, expiry in (
        (fixture.task, fixture.document, fixture.lease, now + timedelta(hours=1)),
        (
            fixture.stale_task,
            fixture.stale_document,
            fixture.stale_lease,
            now - timedelta(hours=1),
        ),
    ):
        await admin.execute(
            """
            INSERT INTO url_fetch_tasks (
                id, tenant_id, project_id, document_id, requested_by,
                encrypted_url, canonical_url, status, attempt_count, max_attempts,
                available_at, lease_token, lease_expires_at, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, '\\x00', 'https://shadow.invalid/', 'running',
                1, 3, $6, $7, $8, $6, $6
            )
            """,
            task_id, fixture.tenant, fixture.project, document,
            fixture.user, now, lease, expiry,
        )
    await admin.execute(
        """
        INSERT INTO outbox_events (
            id, tenant_id, aggregate_type, aggregate_id, event_type, payload,
            available_at, attempts, created_at
        ) VALUES ($1, $2, 'job', $3, 'job.dispatch.requested.v1', $4, $5, 0, $5)
        """,
        fixture.outbox, fixture.tenant, fixture.job,
        json.dumps({"job_id": str(fixture.job)}), now,
    )
    await admin.execute(
        """
        INSERT INTO collections (
            id, tenant_id, project_id, name, status, profile, manifest_revision,
            event_sequence, created_by, created_at, updated_at
        ) VALUES ($1, $2, $3, $4, 'CREATED', '{}', 1, 0, $5, $6, $6)
        """,
        fixture.collection, fixture.tenant, fixture.project, f"shadow {label}",
        fixture.user, now,
    )
    return fixture


async def _purge(admin: asyncpg.Connection[asyncpg.Record], fixture: Fixture) -> None:
    for statement in (
        "DELETE FROM collections WHERE tenant_id = $1",
        "DELETE FROM outbox_events WHERE tenant_id = $1",
        "DELETE FROM url_fetch_tasks WHERE tenant_id = $1",
        "DELETE FROM job_events WHERE tenant_id = $1",
        "DELETE FROM processing_jobs WHERE tenant_id = $1",
        "DELETE FROM documents WHERE tenant_id = $1",
        "DELETE FROM project_memberships WHERE tenant_id = $1",
        "DELETE FROM projects WHERE tenant_id = $1",
        "DELETE FROM memberships WHERE tenant_id = $1",
        "DELETE FROM tenants WHERE id = $1",
    ):
        await admin.execute(statement, fixture.tenant)
    await admin.execute("DELETE FROM users WHERE id = $1", fixture.user)


async def _visible(
    connection: asyncpg.Connection[asyncpg.Record],
    query: str,
    settings: dict[str, str],
    *parameters: Any,
) -> Any:
    async with connection.transaction():
        for name, value in settings.items():
            await connection.execute("SELECT set_config($1, $2, true)", name, value)
        return await connection.fetchval(query, *parameters)


async def _denied(
    connection: asyncpg.Connection[asyncpg.Record],
    query: str,
    settings: dict[str, str],
    *parameters: Any,
) -> str | None:
    """Run a statement expected to be refused; return the error class name."""

    try:
        await _visible(connection, query, settings, *parameters)
    except asyncpg.PostgresError as error:
        return type(error).__name__
    return None


async def _inert_pass(
    admin: asyncpg.Connection[asyncpg.Record],
    alpha: Fixture,
    beta: Fixture,
    report: Report,
) -> None:
    """As the real worker roles, exactly as they ship. Nothing may have moved."""

    print("\ninert — BYPASSRLS as shipped")
    for role in ("akc_url_fetcher", "akc_scheduler", "akc_dispatch_worker"):
        async with admin.transaction():
            await admin.execute(f"SET LOCAL ROLE {role}")
            if role == "akc_url_fetcher":
                seen = await admin.fetchval(
                    "SELECT count(*) FROM url_fetch_tasks WHERE tenant_id = ANY($1::uuid[])",
                    [alpha.tenant, beta.tenant],
                )
                expected, table = 4, "url_fetch_tasks"
            else:
                seen = await admin.fetchval(
                    "SELECT count(*) FROM outbox_events WHERE tenant_id = ANY($1::uuid[])",
                    [alpha.tenant, beta.tenant],
                )
                expected, table = 2, "outbox_events"
        report.require(
            f"inert:{role}",
            int(seen) == expected,
            f"{role} still sees all {expected} seeded {table} rows across both tenants",
        )
    bypass = await admin.fetchval(
        "SELECT count(*) FROM pg_roles WHERE rolname = ANY($1::text[]) AND rolbypassrls",
        list(WORKER_ROLES),
    )
    report.require(
        "inert:bypassrls-intact",
        int(bypass) == len(WORKER_ROLES),
        f"all {len(WORKER_ROLES)} worker roles still hold BYPASSRLS after 0034",
    )


async def _human_plane_pass(
    admin: asyncpg.Connection[asyncpg.Record],
    parts: dict[str, Any],
    alpha: Fixture,
    beta: Fixture,
    report: Report,
) -> None:
    print("\nhuman plane — akc_api_runtime -> SET ROLE akc_api_plane")
    password = secrets.token_urlsafe(32)
    await admin.execute(
        f"ALTER ROLE {HUMAN_PLANE_LOGIN_ROLE} LOGIN PASSWORD '{password}'"
    )
    plane: asyncpg.Connection[asyncpg.Record] | None = None
    try:
        plane = await asyncpg.connect(
            user=HUMAN_PLANE_LOGIN_ROLE, password=password, **parts
        )
        login_role = await plane.fetchval("SELECT current_user")
        await plane.execute(f"SET ROLE {HUMAN_PLANE_ROLE}")
        effective = await plane.fetchval("SELECT current_user")
        session = await plane.fetchval("SELECT session_user")
        report.require(
            "human:role-separation",
            login_role == HUMAN_PLANE_LOGIN_ROLE
            and effective == HUMAN_PLANE_ROLE
            and session == HUMAN_PLANE_LOGIN_ROLE,
            f"login principal {session} authorizes as {effective}",
        )

        member = {"app.tenant_id": str(alpha.tenant), "app.user_id": str(alpha.user)}
        seen = await _visible(
            plane, "SELECT count(*) FROM documents", member
        )
        report.require(
            "human:member-sees-own-tenant",
            int(seen) == 2,
            "a member with tenant and user context sees both of its own documents",
        )

        seen = await _visible(
            plane, "SELECT count(*) FROM documents", {"app.tenant_id": str(alpha.tenant)}
        )
        report.require(
            "human:no-user-no-rows",
            int(seen) == 0,
            "tenant context without a user sees nothing — the plane is "
            "membership-gated, not merely tenant-gated",
        )

        seen = await _visible(
            plane,
            "SELECT count(*) FROM documents",
            {"app.tenant_id": str(beta.tenant), "app.user_id": str(alpha.user)},
        )
        report.require(
            "human:forged-tenant",
            int(seen) == 0,
            "tenant B with tenant A's user sees nothing",
        )

        seen = await _visible(plane, "SELECT count(*) FROM collections", member)
        report.require(
            "human:default-deny-backfill",
            int(seen) == 1,
            "collections carries only restrictive policies; the permissive "
            "backfill is what makes it visible at all",
        )

        seen = await _visible(plane, "SELECT count(*) FROM job_events", member)
        report.require(
            "human:retargeted-policy-still-binds",
            int(seen) == 1,
            "job_events' membership policy now targets the plane and still admits it",
        )
        seen = await _visible(
            plane, "SELECT count(*) FROM job_events", {"app.tenant_id": str(alpha.tenant)}
        )
        report.require(
            "human:retargeted-policy-denies",
            int(seen) == 0,
            "the same policy denies the same plane with no user claimed",
        )

        for target in (WORKER_ROLES[0], "akc_scheduler", "pgowner"):
            failure = await _denied(plane, f"SET ROLE {target}", {})
            report.require(
                f"human:no-escalation-to-{target}",
                failure is not None,
                f"SET ROLE {target} refused ({failure})",
            )

        failure = await _denied(
            plane, "ALTER POLICY documents_project_select ON documents TO PUBLIC", {}
        )
        report.require(
            "human:cannot-retarget-policy",
            failure is not None,
            f"the plane cannot move a policy back to PUBLIC ({failure})",
        )
        failure = await _denied(plane, "ALTER TABLE documents OWNER TO CURRENT_USER", {})
        report.require(
            "human:cannot-take-ownership",
            failure is not None,
            f"the plane cannot take table ownership ({failure})",
        )
        failure = await _denied(
            plane,
            "CREATE POLICY shadow_escape ON documents AS PERMISSIVE FOR SELECT "
            "TO PUBLIC USING (true)",
            {},
        )
        report.require(
            "human:cannot-create-policy",
            failure is not None,
            f"the plane cannot add a policy of its own ({failure})",
        )

        await admin.execute(
            "DELETE FROM project_memberships WHERE tenant_id = $1", alpha.tenant
        )
        await admin.execute("DELETE FROM memberships WHERE tenant_id = $1", alpha.tenant)
        seen = await _visible(plane, "SELECT count(*) FROM documents", member)
        report.require(
            "human:revoke-is-immediate",
            int(seen) == 0,
            "revoking the membership row removes the person's access in the "
            "same breath, with no reindex",
        )
    finally:
        if plane is not None:
            await plane.close()
        await admin.execute(f"ALTER ROLE {HUMAN_PLANE_LOGIN_ROLE} NOLOGIN PASSWORD NULL")


async def _armed_pass(
    admin: asyncpg.Connection[asyncpg.Record],
    parts: dict[str, Any],
    alpha: Fixture,
    beta: Fixture,
    report: Report,
) -> None:
    """The shadow: BYPASSRLS off in this throwaway cluster only."""

    print("\narmed — BYPASSRLS removed in the throwaway cluster (restored after)")
    # The real login principals, one per worker role, because that is what makes
    # the lateral-move test mean anything: `SET ROLE` is checked against the
    # *session* user's memberships, so a harness that logged in once and assumed
    # both identities would prove the opposite of what it claimed.
    logins = {
        "akc_scheduler": ("akc_scheduler_runtime", secrets.token_urlsafe(32)),
        "akc_url_fetcher": ("akc_url_fetcher_runtime", secrets.token_urlsafe(32)),
    }
    for role, (login, password) in logins.items():
        await admin.execute(f"ALTER ROLE {login} PASSWORD '{password}'")
        await admin.execute(f"ALTER ROLE {role} NOBYPASSRLS")
    scheduler: asyncpg.Connection[asyncpg.Record] | None = None
    worker: asyncpg.Connection[asyncpg.Record] | None = None
    try:
        login, password = logins["akc_scheduler"]
        scheduler = await asyncpg.connect(user=login, password=password, **parts)
        login, password = logins["akc_url_fetcher"]
        worker = await asyncpg.connect(user=login, password=password, **parts)

        # --- control plane -------------------------------------------------
        await scheduler.execute("SET ROLE akc_scheduler")
        seen = await _visible(scheduler, "SELECT count(*) FROM outbox_events", {})
        report.require(
            "control:undeclared-sees-nothing",
            int(seen) == 0,
            "a scheduler transaction that declares no purpose sees no queue rows",
        )
        seen = await _visible(
            scheduler,
            "SELECT count(*) FROM outbox_events WHERE tenant_id = ANY($1::uuid[])",
            {"app.control_plane": "job_discovery"},
            [alpha.tenant, beta.tenant],
        )
        report.require(
            "control:declared-discovers-across-tenants",
            int(seen) == 2,
            "declaring job_discovery opens the cross-tenant queue view",
        )
        seen = await _visible(
            scheduler,
            "SELECT count(*) FROM outbox_events",
            {"app.control_plane": "exfiltrate"},
        )
        report.require(
            "control:unapproved-purpose-denied",
            int(seen) == 0,
            "a purpose outside the approved list opens nothing",
        )
        seen = await _visible(
            scheduler,
            "SELECT count(*) FROM outbox_events WHERE tenant_id = ANY($1::uuid[])",
            {"app.control_plane": "job_discovery", "app.tenant_id": str(alpha.tenant)},
            [alpha.tenant, beta.tenant],
        )
        report.require(
            "control:tenant-binding-closes-the-view",
            int(seen) == 1,
            "binding a tenant collapses the cross-tenant view to that tenant",
        )
        seen = await _visible(
            scheduler,
            "SELECT count(*) FROM job_events WHERE tenant_id = ANY($1::uuid[])",
            {"app.control_plane": "retention"},
            [alpha.tenant, beta.tenant],
        )
        report.require(
            "control:retarget-removed-the-acl-check",
            int(seen) == 2,
            "job_events' retention sweep runs without a grant on memberships — "
            "the blocker V5_WORKER_PRIVILEGE_BOUNDARY recorded",
        )
        for table in ("documents", "url_fetch_tasks", "collections"):
            failure = await _denied(
                scheduler,
                f"SELECT count(*) FROM {table}",  # noqa: S608 - fixed table names
                {"app.control_plane": "job_discovery"},
            )
            report.require(
                f"control:outside-boundary-{table}",
                failure == "InsufficientPrivilegeError",
                f"{table} is outside the control-plane boundary ({failure})",
            )

        # --- worker plane claim binding ------------------------------------
        await worker.execute("SET ROLE akc_url_fetcher")
        bound = {
            "app.tenant_id": str(alpha.tenant),
            "app.project_id": str(alpha.project),
            "app.claim_id": str(alpha.task),
            "app.lease_token": str(alpha.lease),
        }
        seen = await _visible(worker, "SELECT count(*) FROM url_fetch_tasks", bound)
        report.require(
            "claim:bound-sees-its-own-row",
            int(seen) == 1,
            "a worker holding the live lease sees exactly the claimed row",
        )
        for case, override in (
            ("forged-tenant", {"app.tenant_id": str(beta.tenant)}),
            ("forged-project", {"app.project_id": str(beta.project)}),
            ("forged-claim", {"app.claim_id": str(beta.task)}),
            ("reused-lease", {"app.lease_token": str(beta.lease)}),
            (
                "expired-lease",
                {
                    "app.claim_id": str(alpha.stale_task),
                    "app.lease_token": str(alpha.stale_lease),
                },
            ),
            ("missing-lease", {"app.lease_token": ""}),
            ("missing-claim", {"app.claim_id": ""}),
        ):
            seen = await _visible(
                worker, "SELECT count(*) FROM url_fetch_tasks", {**bound, **override}
            )
            report.require(
                f"claim:{case}",
                int(seen) == 0,
                f"{case} yields no rows",
            )
        # This one records a limitation rather than a protection. The claim
        # binding permits an unbound transaction, but the only *permissive*
        # policy on url_fetch_tasks requires a tenant — so an armed url fetcher
        # cannot poll its own queue. Fail-closed, and a prerequisite for step 8:
        # docs/audit/V5_WORKER_AUTHZ_ARMING.md A-6. Measured here so the gap is
        # evidence rather than a claim in prose.
        for label, settings in (
            ("unbound", {}),
            ("declared", {"app.control_plane": "claim"}),
            ("discovery", {"app.control_plane": "job_discovery"}),
        ):
            seen = await _visible(
                worker,
                "SELECT count(*) FROM url_fetch_tasks WHERE tenant_id = ANY($1::uuid[])",
                settings,
                [alpha.tenant, beta.tenant],
            )
            report.require(
                f"claim:queue-poll-blocked-{label}",
                int(seen) == 0,
                f"an armed url fetcher polling {label} reads nothing — no worker "
                "role holds a cross-tenant discovery policy on its own queue yet",
            )
        for table in ("gpu_provider_invocations", "webhook_deliveries", "payments"):
            failure = await _denied(
                worker,
                f"SELECT count(*) FROM {table}",  # noqa: S608 - fixed table names
                bound,
            )
            report.require(
                f"claim:other-queue-{table}",
                failure == "InsufficientPrivilegeError",
                f"the url fetcher cannot reach {table} ({failure})",
            )
        failure = await _denied(worker, "SET ROLE akc_scheduler", {})
        report.require(
            "claim:no-lateral-set-role",
            failure is not None,
            f"the url fetcher cannot become the scheduler ({failure})",
        )
        failure = await _denied(
            worker,
            'DROP POLICY "url_fetch_tasks_claim_binding" ON url_fetch_tasks',
            {},
        )
        report.require(
            "claim:cannot-drop-its-own-binding",
            failure is not None,
            f"the bound worker cannot drop the policy binding it ({failure})",
        )
    finally:
        for connection in (scheduler, worker):
            if connection is not None:
                await connection.close()
        for role, (login, _) in logins.items():
            await admin.execute(f"ALTER ROLE {role} BYPASSRLS")
            await admin.execute(f"ALTER ROLE {login} PASSWORD NULL")


async def run(url: str) -> Report:
    report = Report()
    admin = await asyncpg.connect(url)
    alpha: Fixture | None = None
    beta: Fixture | None = None
    try:
        alpha = await _seed(admin, "alpha")
        beta = await _seed(admin, "beta")
        await _inert_pass(admin, alpha, beta, report)
        await _armed_pass(admin, _parts(url), alpha, beta, report)
        # Last: it revokes alpha's membership to prove revocation is immediate.
        await _human_plane_pass(admin, _parts(url), alpha, beta, report)
    finally:
        for fixture in (alpha, beta):
            if fixture is not None:
                await _purge(admin, fixture)
        restored = await admin.fetchval(
            "SELECT count(*) FROM pg_roles WHERE rolname = ANY($1::text[]) AND rolbypassrls",
            list(WORKER_ROLES),
        )
        await admin.close()
        if int(restored) != len(WORKER_ROLES):
            raise ShadowFailure(
                f"BYPASSRLS was not restored on every worker role ({restored}/7)"
            )
    return report


def main() -> int:
    # The case descriptions are prose and the default console encoding on a
    # Korean Windows install is cp949, which cannot encode them. Failing a
    # security validation on a print() is the wrong way to fail.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    report = asyncio.run(run(_admin_url()))
    print(f"\nshadow validation passed: {len(report.passed)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
