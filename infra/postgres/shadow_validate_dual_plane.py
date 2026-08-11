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


async def _seed_claimable(
    admin: asyncpg.Connection[asyncpg.Record], fixture: Fixture, count: int
) -> list[uuid.UUID]:
    """Extra url_fetch_tasks a broker may claim, for the concurrency proof.

    ``url_fetch_tasks`` is unique on (tenant, document), so each needs its own
    document row.
    """

    now = datetime.now(UTC)
    tasks: list[uuid.UUID] = []
    for index in range(count):
        document = uuid.uuid4()
        task = uuid.uuid4()
        await admin.execute(
            """
            INSERT INTO documents (
                id, tenant_id, project_id, title, document_type, language_codes,
                active_version, cir_schema_version, status, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'report', '[]', 1, '1.0', 'ready', $5, $5)
            """,
            document, fixture.tenant, fixture.project, f"claimable {index}", now,
        )
        await admin.execute(
            """
            INSERT INTO url_fetch_tasks (
                id, tenant_id, project_id, document_id, requested_by,
                encrypted_url, canonical_url, status, attempt_count, max_attempts,
                available_at, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, '\\x00', 'https://shadow.invalid/', 'queued',
                0, 3, $6, $6, $6
            )
            """,
            task, fixture.tenant, fixture.project, document, fixture.user, now,
        )
        tasks.append(task)
    return tasks


async def _purge(admin: asyncpg.Connection[asyncpg.Record], fixture: Fixture) -> None:
    for statement in (
        # audit_events holds a RESTRICT foreign key to tenants, so the broker's
        # claim receipts have to go before the tenant does.
        "DELETE FROM audit_events WHERE tenant_id = $1",
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
        # By id, not by count: other passes seed rows into these tenants, and an
        # assertion that drifts with the fixture is an assertion nobody trusts.
        fixture_documents = [alpha.document, alpha.stale_document]
        seen = await _visible(
            plane,
            "SELECT count(*) FROM documents WHERE id = ANY($1::uuid[])",
            member,
            fixture_documents,
        )
        report.require(
            "human:member-sees-own-tenant",
            int(seen) == 2,
            "a member with tenant and user context sees both of its own documents",
        )

        seen = await _visible(
            plane,
            "SELECT count(*) FROM documents WHERE id = ANY($1::uuid[])",
            {"app.tenant_id": str(alpha.tenant)},
            fixture_documents,
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


BROKER = "akc_claim_url_fetch_task"
BROKER_ROLE = "akc_claim_broker"
BROKER_RETURN_COLUMNS = (
    "claim_id",
    "tenant_id",
    "project_id",
    "lease_token",
    "lease_expires_at",
)


async def _claim_repeatedly(
    connection: asyncpg.Connection[asyncpg.Record], times: int
) -> list[asyncpg.Record]:
    """One caller's claims, in sequence.

    The concurrency is *between* connections — a single asyncpg connection
    refuses overlapping operations, and a harness that ran them on one would be
    measuring nothing.
    """

    granted: list[asyncpg.Record] = []
    for _ in range(times):
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.control_plane', 'claim', true)"
            )
            row = await connection.fetchrow(f"SELECT * FROM {BROKER}(300)")  # noqa: S608 - module constant
        if row is not None:
            granted.append(row)
    return granted


async def _broker_pass(
    admin: asyncpg.Connection[asyncpg.Record],
    parts: dict[str, Any],
    alpha: Fixture,
    beta: Fixture,
    report: Report,
) -> None:
    """The seven proofs founder decision F-1 attached to Option B, plus escalation.

    Until every one of these passes the broker is a design, not a mechanism.
    """

    print("\nclaim broker — F-1 Option B")
    password = secrets.token_urlsafe(32)
    login = "akc_url_fetcher_runtime"
    await admin.execute(f"ALTER ROLE {login} PASSWORD '{password}'")
    await admin.execute("ALTER ROLE akc_url_fetcher NOBYPASSRLS")
    seeded = [
        *await _seed_claimable(admin, alpha, 4),
        *await _seed_claimable(admin, beta, 4),
    ]
    callers: list[asyncpg.Connection[asyncpg.Record]] = []
    try:
        for _ in range(4):
            connection = await asyncpg.connect(user=login, password=password, **parts)
            await connection.execute("SET ROLE akc_url_fetcher")
            callers.append(connection)
        caller = callers[0]

        # 7 — the catalog, before anything is called.
        config = await admin.fetchval(
            "SELECT array_to_string(p.proconfig, ',') FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND p.proname = $1",
            BROKER,
        )
        report.require(
            "broker:search-path-is-pinned",
            str(config) == "search_path=pg_catalog, public",
            f"the catalog reports {config!r}, so a caller cannot shadow a function name",
        )
        owner, secdef = await admin.fetchrow(  # type: ignore[misc]
            "SELECT pg_get_userbyid(p.proowner) AS owner, p.prosecdef AS secdef "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public' AND p.proname = $1",
            BROKER,
        )
        broker_bypass = await admin.fetchval(
            "SELECT rolbypassrls OR rolcanlogin FROM pg_roles WHERE rolname = $1",
            BROKER_ROLE,
        )
        report.require(
            "broker:definer-owner-is-not-privileged",
            str(owner) == BROKER_ROLE and bool(secdef) and not bool(broker_bypass),
            f"owned by {owner}, SECURITY DEFINER, and that role holds neither "
            "BYPASSRLS nor LOGIN",
        )

        # 5 — refusal before anything else, so a later pass cannot be a leftover.
        for label, settings in (
            ("undeclared", {}),
            ("unapproved", {"app.control_plane": "exfiltrate"}),
        ):
            async with caller.transaction():
                for name, value in settings.items():
                    await caller.execute("SELECT set_config($1, $2, true)", name, value)
                row = await caller.fetchrow(f"SELECT * FROM {BROKER}(300)")  # noqa: S608 - module constant
            report.require(
                f"broker:refuses-an-undeclared-purpose-{label}",
                row is None,
                f"a {label} purpose claims nothing",
            )
        async with caller.transaction():
            await caller.execute(
                "SELECT set_config('app.control_plane', 'claim', true)"
            )
            await caller.execute(
                "SELECT set_config('app.tenant_id', $1, true)", str(alpha.tenant)
            )
            row = await caller.fetchrow(f"SELECT * FROM {BROKER}(300)")  # noqa: S608 - module constant
        report.require(
            "broker:refuses-when-a-tenant-is-bound",
            row is None,
            "a transaction already doing one tenant's work cannot claim across tenants",
        )

        # 1 — atomicity. The case flagged as "looks obviously correct and is not".
        batches = await asyncio.gather(
            *(_claim_repeatedly(connection, 4) for connection in callers)
        )
        granted = [row for batch in batches for row in batch]
        claim_ids = [row["claim_id"] for row in granted]
        claimable = await admin.fetchval(
            "SELECT count(*) FROM url_fetch_tasks WHERE tenant_id = ANY($1::uuid[]) "
            "  AND status IN ('queued','retry','running') AND available_at <= now() "
            "  AND (lease_expires_at IS NULL OR lease_expires_at <= now())",
            [alpha.tenant, beta.tenant],
        )
        report.require(
            "broker:claims-one-row-atomically",
            len(set(claim_ids)) == len(granted) and len(granted) == len(seeded) + 2,
            f"{len(callers)} concurrent callers x 4 attempts granted {len(granted)} "
            f"claims over {len(set(claim_ids))} distinct rows "
            f"({len(seeded)} seeded here plus 2 expired-lease rows from the "
            f"fixture); {claimable} remain claimable",
        )
        mismatched = await admin.fetchval(
            "SELECT count(*) FROM url_fetch_tasks t "
            "JOIN unnest($1::uuid[], $2::uuid[]) AS g(claim_id, lease_token) "
            "  ON g.claim_id = t.id "
            "WHERE t.lease_token IS DISTINCT FROM g.lease_token",
            claim_ids,
            [row["lease_token"] for row in granted],
        )
        report.require(
            "broker:returned-token-is-the-row-token",
            int(mismatched) == 0,
            "every returned lease token is the token now on its row — the claim "
            "and the receipt cannot diverge",
        )

        # 2 — the return surface.
        sample = granted[0]
        report.require(
            "broker:returns-identifiers-only",
            tuple(sample.keys()) == BROKER_RETURN_COLUMNS,
            f"the result is exactly {', '.join(BROKER_RETURN_COLUMNS)} — no URL, "
            "parameter or manifest column is reachable through it",
        )

        # 3 — the grant added a claim path, not a read path.
        for label, settings in (
            ("undeclared", {}),
            ("declared", {"app.control_plane": "claim"}),
        ):
            seen = await _visible(
                caller,
                "SELECT count(*) FROM url_fetch_tasks WHERE tenant_id = ANY($1::uuid[])",
                settings,
                [alpha.tenant, beta.tenant],
            )
            report.require(
                f"broker:no-cross-tenant-select-remains-{label}",
                int(seen) == 0,
                f"holding EXECUTE, a {label} direct SELECT still reads nothing",
            )

        # 4 — the lease the broker stamped is one the caller can bind.
        bound = {
            "app.tenant_id": str(sample["tenant_id"]),
            "app.project_id": str(sample["project_id"]),
            "app.claim_id": str(sample["claim_id"]),
            "app.lease_token": str(sample["lease_token"]),
        }
        seen = await _visible(caller, "SELECT count(*) FROM url_fetch_tasks", bound)
        report.require(
            "broker:stamps-a-lease-the-caller-can-bind",
            int(seen) == 1,
            "binding the returned identifiers makes exactly the claimed row visible",
        )
        seen = await _visible(
            caller,
            "SELECT count(*) FROM url_fetch_tasks",
            {**bound, "app.lease_token": str(uuid.uuid4())},
        )
        report.require(
            "broker:a-forged-token-still-binds-nothing",
            int(seen) == 0,
            "the claim binding is not satisfied by holding the claim id alone",
        )

        # 6 — the caller cannot redefine or take the thing that grants it access.
        for label, statement in (
            ("replace", f"CREATE OR REPLACE FUNCTION public.{BROKER}(integer) "
                        "RETURNS TABLE (claim_id uuid, tenant_id uuid, project_id uuid, "
                        "lease_token uuid, lease_expires_at timestamptz) LANGUAGE sql "
                        "AS $$ SELECT NULL::uuid, NULL::uuid, NULL::uuid, NULL::uuid, "
                        "NULL::timestamptz $$"),
            ("own", f"ALTER FUNCTION public.{BROKER}(integer) OWNER TO CURRENT_USER"),
            ("drop", f"DROP FUNCTION public.{BROKER}(integer)"),
            ("unpin", f"ALTER FUNCTION public.{BROKER}(integer) RESET search_path"),
            ("become", f"SET ROLE {BROKER_ROLE}"),
        ):
            failure = await _denied(caller, statement, {})
            report.require(
                f"broker:cannot-{label}",
                failure is not None,
                f"the caller cannot {label} the broker ({failure})",
            )
        failure = await _denied(caller, "SELECT * FROM akc_claim_gpu_invocation(300)", {})
        report.require(
            "broker:cannot-execute-another-queues-broker",
            failure == "InsufficientPrivilegeError",
            f"holding one queue's broker grants nothing on another's ({failure})",
        )

        # Escalation: a role with no grant. akc_scheduler has its own boundary
        # and must not inherit this one.
        scheduler_login = "akc_scheduler_runtime"
        scheduler_password = secrets.token_urlsafe(32)
        await admin.execute(
            f"ALTER ROLE {scheduler_login} PASSWORD '{scheduler_password}'"
        )
        other = await asyncpg.connect(
            user=scheduler_login, password=scheduler_password, **parts
        )
        try:
            await other.execute("SET ROLE akc_scheduler")
            failure = await _denied(
                other,
                f"SELECT * FROM {BROKER}(300)",  # noqa: S608 - module constant
                {},
            )
            report.require(
                "broker:execute-is-not-public",
                failure == "InsufficientPrivilegeError",
                f"a role outside the grant cannot call the broker ({failure}) — "
                "PostgreSQL grants EXECUTE to PUBLIC by default and this proves "
                "the revoke held",
            )
        finally:
            await other.close()
            await admin.execute(f"ALTER ROLE {scheduler_login} PASSWORD NULL")

        # The lease clamp. Needs a claimable row of its own — the concurrency
        # proof above drains the queue, and a clamp case that finds nothing
        # passes without measuring anything.
        await _seed_claimable(admin, alpha, 1)
        async with caller.transaction():
            await caller.execute(
                "SELECT set_config('app.control_plane', 'claim', true)"
            )
            clamped = await caller.fetchrow(
                f"SELECT *, (lease_expires_at - now()) AS window FROM {BROKER}(100000000)"  # noqa: S608
            )
        report.require(
            "broker:lease-is-clamped",
            clamped is not None and clamped["window"] <= timedelta(seconds=3600),
            "a 100,000,000-second lease request came back as "
            f"{None if clamped is None else clamped['window']} — clamped to the "
            "ceiling rather than parking a row indefinitely",
        )
        audited = await admin.fetchval(
            "SELECT count(*) FROM audit_events "
            "WHERE action = 'worker.claim.granted' AND target_type = 'url_fetch_tasks' "
            "  AND target_id = ANY($1::text[])",
            [str(value) for value in claim_ids],
        )
        principal = await admin.fetchval(
            "SELECT metadata::jsonb ->> 'principal' FROM audit_events "
            "WHERE action = 'worker.claim.granted' AND target_id = $1",
            str(sample["claim_id"]),
        )
        report.require(
            "broker:every-grant-is-audited",
            int(audited) == len(granted) and str(principal) == login,
            f"{audited} audit rows for {len(granted)} grants, naming the session "
            f"principal ({principal})",
        )

        # Gate 1 substrate: the starvation signature, at the database. Backlog has
        # to actually exist or this measures an idle queue and calls it a proof.
        await _seed_claimable(admin, alpha, 3)
        async with caller.transaction():
            await caller.execute(
                "SELECT set_config('app.control_plane', 'claim', true)"
            )
            backlog = await caller.fetchval(f"SELECT {BROKER}_backlog()")
            claimable = await caller.fetchval(f"SELECT {BROKER}_depth()")
        report.require(
            "broker:backlog-exceeds-claimable-when-rows-are-leased",
            int(backlog) > int(claimable) >= 3,
            f"backlog {backlog} against claimable {claimable} — the difference is "
            "the rows other callers still hold, and it is the distinction one "
            "probe cannot make: a fully leased queue and a queue this worker "
            "cannot see both report zero claimable",
        )
        async with caller.transaction():
            await caller.execute(
                "SELECT set_config('app.control_plane', 'claim', true)"
            )
            depth = await caller.fetchval(f"SELECT {BROKER}_depth()")
            visible = await caller.fetchval("SELECT count(*) FROM url_fetch_tasks")
        report.require(
            "broker:depth-probe-sees-what-the-worker-cannot",
            int(depth) >= 3 and int(visible) == 0,
            f"claimable depth {depth} while the worker's own read sees {visible} — "
            "backlog with no visibility is the starvation signature, and it is "
            "what tells RLS starvation from an idle queue",
        )
        async with caller.transaction():
            await caller.execute(
                "SELECT set_config('app.control_plane', 'claim', true)"
            )
            await caller.execute(
                "SELECT set_config('app.tenant_id', $1, true)", str(alpha.tenant)
            )
            bound_depth = await caller.fetchval(f"SELECT {BROKER}_depth()")
        report.require(
            "broker:depth-probe-is-purpose-gated-too",
            int(bound_depth) == 0,
            "the depth probe is not a back door: with a tenant bound it reports 0, "
            "the same gate the broker itself uses",
        )
    finally:
        for connection in callers:
            await connection.close()
        await admin.execute("ALTER ROLE akc_url_fetcher BYPASSRLS")
        await admin.execute(f"ALTER ROLE {login} PASSWORD NULL")
        await admin.execute(
            "DELETE FROM audit_events WHERE tenant_id = ANY($1::uuid[])",
            [alpha.tenant, beta.tenant],
        )


GPU_BROKER = "akc_claim_gpu_invocation"

# The ORM predicate from GpuInvocationWorker._claim, written as SQL. This is the
# BEFORE side of the comparative evidence: if it and the broker disagree about
# which rows are claimable, or in what order, then the adaptation is not
# behaviour preserving and the disagreement is the finding.
_BEFORE_ELIGIBLE = """
SELECT id FROM gpu_provider_invocations
WHERE tenant_id = ANY($1::uuid[])
  AND status IN ('queued', 'submitting', 'submitted', 'running', 'retry',
                 'cancel_requested', 'cancelling')
  AND available_at <= now()
  AND (lease_expires_at IS NULL OR lease_expires_at <= now())
ORDER BY available_at, created_at, id
"""


async def _seed_invocations(
    admin: asyncpg.Connection[asyncpg.Record],
    fixture: Fixture,
    rows: list[dict[str, Any]],
) -> list[uuid.UUID]:
    """Seed gpu_provider_invocations with an explicitly shaped population."""

    now = datetime.now(UTC)
    created: list[uuid.UUID] = []
    for index, row in enumerate(rows):
        invocation = uuid.uuid4()
        await admin.execute(
            """
            INSERT INTO gpu_provider_invocations (
                id, tenant_id, job_id, project_id, document_id,
                document_version_id, provider, provider_key, endpoint_id,
                idempotency_key, request_manifest_sha256, status, input_bucket,
                input_object_key, input_sha256, output_object_key, options,
                model_revision, runtime_image_digest, adapter_version,
                transition_policy, transition_attempt, attempt_count,
                cancel_attempt_count, max_attempts, available_at,
                lease_expires_at, lease_token, event_sequence, created_at,
                updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, 'v1', 'runpod', 'parser', 'ep-1',
                $6, repeat('a', 64), $7, 'source', 'in/key', repeat('b', 64),
                -- model_revision is length-checked 40..64 and
                -- runtime_image_digest exactly 71, so both are built rather
                -- than written as short placeholders.
                'out/key', '{}', repeat('d', 48),
                'sha256:' || repeat('c', 64), 'ad-1',
                '{}', 0, 0, 0, 3, $8, $9, $10, 0, $11, $11
            )
            """,
            invocation, fixture.tenant, fixture.job, fixture.project,
            fixture.document, "idem-" + invocation.hex, row["status"],
            row["available_at"], row.get("lease_expires_at"),
            row.get("lease_token"),
            now - timedelta(seconds=100 - index),
        )
        created.append(invocation)
    return created


async def _drain_broker(
    connection: asyncpg.Connection[asyncpg.Record], limit: int = 40
) -> list[uuid.UUID]:
    """Claim until the broker has nothing left, preserving grant order."""

    granted: list[uuid.UUID] = []
    for _ in range(limit):
        async with connection.transaction():
            await connection.execute(
                "SELECT set_config('app.control_plane', 'claim', true)"
            )
            row = await connection.fetchrow(
                f"SELECT * FROM {GPU_BROKER}(300)"  # noqa: S608 - module constant
            )
        if row is None:
            return granted
        granted.append(row["claim_id"])
    raise ShadowFailure("broker did not drain; the claimable set is not shrinking")


async def _equivalence_pass(
    admin: asyncpg.Connection[asyncpg.Record],
    parts: dict[str, Any],
    alpha: Fixture,
    beta: Fixture,
    report: Report,
) -> None:
    """COMPARATIVE evidence: BEFORE against the broker over one population.

    The four dimensions that stay genuinely comparative — eligibility, ordering,
    concurrency and lease expiry. The other two categories are structural and
    are asserted in services/scheduler/tests/test_claim_equivalence.py.

    Draining the broker proves eligibility and ordering together: each claim
    removes exactly one row from the claimable set, so the grant *sequence*
    equals the BEFORE-ordered eligible list only if both agree on both.
    """

    print("\nGPU claim equivalence - BEFORE vs broker")
    now = datetime.now(UTC)
    tenants = [alpha.tenant, beta.tenant]
    password = secrets.token_urlsafe(32)
    login = "akc_scheduler_runtime"
    await admin.execute("ALTER ROLE " + login + " PASSWORD '" + password + "'")
    await admin.execute("GRANT akc_gpu_worker TO " + login)
    callers: list[asyncpg.Connection[asyncpg.Record]] = []
    try:
        for _ in range(4):
            connection = await asyncpg.connect(user=login, password=password, **parts)
            await connection.execute("SET ROLE akc_gpu_worker")
            callers.append(connection)
        caller = callers[0]

        future = now + timedelta(hours=1)
        past = now - timedelta(hours=1)
        # Every reason a row is or is not claimable, in one population.
        population = [
            {"status": "queued", "available_at": now - timedelta(minutes=5)},
            {"status": "running", "available_at": now - timedelta(minutes=4)},
            {"status": "retry", "available_at": now - timedelta(minutes=3),
             "lease_expires_at": past, "lease_token": uuid.uuid4()},
            {"status": "cancelling", "available_at": now - timedelta(minutes=2)},
            {"status": "completed", "available_at": past},
            {"status": "dead_letter", "available_at": past},
            {"status": "queued", "available_at": future},
            {"status": "running", "available_at": past,
             "lease_expires_at": future, "lease_token": uuid.uuid4()},
        ]
        await _seed_invocations(admin, alpha, population)

        expected = [row["id"] for row in await admin.fetch(_BEFORE_ELIGIBLE, tenants)]
        granted = await _drain_broker(caller)

        report.require(
            "equivalence:claim-eligibility",
            set(granted) == set(expected) and len(expected) == 4,
            "BEFORE finds " + str(len(expected)) + " claimable of "
            + str(len(population)) + " seeded; the broker granted exactly the "
            "same set - terminal status, not-yet-due and live-lease rows are "
            "excluded by both",
        )
        report.require(
            "equivalence:ordering",
            granted == expected,
            "the broker's grant sequence is BEFORE's (available_at, created_at, "
            "id) order, row for row",
        )

        expiring = await _seed_invocations(
            admin, alpha,
            [{"status": "running", "available_at": now - timedelta(minutes=1),
              "lease_expires_at": now + timedelta(hours=1),
              "lease_token": uuid.uuid4()}],
        )
        before_live = [r["id"] for r in await admin.fetch(_BEFORE_ELIGIBLE, tenants)]
        granted_live = await _drain_broker(caller)
        await admin.execute(
            "UPDATE gpu_provider_invocations SET lease_expires_at = $2 WHERE id = $1",
            expiring[0], now - timedelta(seconds=1),
        )
        before_expired = [r["id"] for r in await admin.fetch(_BEFORE_ELIGIBLE, tenants)]
        granted_expired = await _drain_broker(caller)
        report.require(
            "equivalence:lease-expiry",
            expiring[0] not in before_live
            and expiring[0] not in granted_live
            and before_expired == [expiring[0]]
            and granted_expired == [expiring[0]],
            "a row with a live lease is claimable by neither; once its lease is "
            "past it is claimable by both, and it is the only such row",
        )

        contended = await _seed_invocations(
            admin, alpha,
            [{"status": "queued", "available_at": now - timedelta(minutes=1)}
             for _ in range(8)],
        )
        batches = await asyncio.gather(
            *(_drain_broker(connection, limit=6) for connection in callers)
        )
        broker_grants = [claim for batch in batches for claim in batch]
        report.require(
            "equivalence:concurrency",
            sorted(broker_grants) == sorted(contended)
            and len(set(broker_grants)) == len(broker_grants),
            str(len(callers)) + " concurrent callers drained "
            + str(len(contended)) + " contended rows into "
            + str(len(broker_grants)) + " grants, all distinct and none lost - "
            "the exactly-once property BEFORE gets from FOR UPDATE SKIP LOCKED, "
            "which the broker's subquery also uses",
        )
    finally:
        for connection in callers:
            await connection.close()
        await admin.execute("REVOKE akc_gpu_worker FROM " + login)
        await admin.execute("ALTER ROLE " + login + " PASSWORD NULL")
        for tenant in tenants:
            await admin.execute(
                "DELETE FROM gpu_provider_invocations WHERE tenant_id = $1", tenant
            )


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
        await _broker_pass(admin, _parts(url), alpha, beta, report)
        await _equivalence_pass(admin, _parts(url), alpha, beta, report)
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
