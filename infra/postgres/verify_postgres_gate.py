"""CI-only PostgreSQL migration, RLS, and worker-role verification."""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlsplit

import asyncpg  # type: ignore[import-untyped]
from akc_scheduler.database import (
    create_dispatch_engine,
    create_scheduler_engine,
    verify_dispatch_database,
    verify_scheduler_database,
)
from akc_scheduler.scheduler import (
    dispatch_advisory_lock_key,
    dispatch_claim_statement,
)
from akc_scheduler.settings import SchedulerSettings
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
APP_ROLE = "akc_ci_app_runtime"
TENANT_TABLES = frozenset(
    {
        "api_keys",
        "audit_events",
        "block_revisions",
        "blocks",
        "credit_accounts",
        "credit_ledger",
        "deletion_receipts",
        "document_versions",
        "documents",
        "entities",
        "exports",
        "feature_flags",
        "idempotency_records",
        "job_events",
        "knowledge_notes",
        "memberships",
        "outbox_events",
        "page_assets",
        "pages",
        "processing_jobs",
        "project_memberships",
        "projects",
        "relations",
        "review_items",
        "source_files",
        "team_invitation_deliveries",
        "team_invitations",
        "tenants",
        "upload_sessions",
        "webhook_deliveries",
        "webhook_endpoints",
    }
)

PROJECT_SCOPED_TABLES = frozenset(
    {
        "analysis_tasks",
        "block_revisions",
        "blocks",
        "document_semantic_classifications",
        "document_versions",
        "documents",
        "entities",
        "exports",
        "gpu_invocation_events",
        "gpu_provider_attempts",
        "gpu_provider_invocations",
        "job_events",
        "knowledge_notes",
        "page_assets",
        "page_attempt_transition_events",
        "page_attempts",
        "pages",
        "processing_jobs",
        "project_memberships",
        "projects",
        "relations",
        "review_items",
        "source_files",
        "upload_sessions",
        "url_fetch_tasks",
    }
)


class ConnectionParts(TypedDict):
    host: str
    port: int
    database: str


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare-roles",
        action="store_true",
        help="bootstrap only the disposable CI scheduler login roles",
    )
    return parser.parse_args()


def _admin_url() -> str:
    value = os.environ.get("AKC_CI_ADMIN_DATABASE_URL", "")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.path.strip("/")
    ):
        raise RuntimeError("CI PostgreSQL verification requires an explicit loopback URL")
    return value


def _connection_parts(url: str) -> ConnectionParts:
    parsed = urlsplit(url)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 5432,
        "database": parsed.path.strip("/"),
    }


async def _prepare_roles(admin_url: str) -> None:
    if os.environ.get("CI", "").casefold() != "true":
        raise RuntimeError("role bootstrap is restricted to CI")
    sql = (ROOT / "infra/postgres/init/010-scheduler-runtime.sql").read_text(encoding="utf-8")
    connection = await asyncpg.connect(admin_url)
    try:
        await connection.execute(sql)
    finally:
        await connection.close()


async def _verify_schema(admin: asyncpg.Connection[asyncpg.Record]) -> None:
    expected_heads = set(ScriptDirectory.from_config(Config("alembic.ini")).get_heads())
    current_heads = {
        str(row["version_num"])
        for row in await admin.fetch("SELECT version_num FROM alembic_version")
    }
    if current_heads != expected_heads:
        raise AssertionError(
            f"database heads {sorted(current_heads)} != source heads {sorted(expected_heads)}"
        )

    rows = await admin.fetch(
        """
        SELECT
            class.relname,
            class.relrowsecurity,
            class.relforcerowsecurity,
            count(policy.policyname) AS policy_count
        FROM pg_class AS class
        JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
        LEFT JOIN pg_policies AS policy
          ON policy.schemaname = namespace.nspname
         AND policy.tablename = class.relname
        WHERE namespace.nspname = 'public'
          AND class.relname = ANY($1::text[])
        GROUP BY class.relname, class.relrowsecurity, class.relforcerowsecurity
        """,
        sorted(TENANT_TABLES),
    )
    observed = {str(row["relname"]): row for row in rows}
    if set(observed) != TENANT_TABLES:
        raise AssertionError(f"missing tenant RLS tables: {sorted(TENANT_TABLES - set(observed))}")
    unsafe = sorted(
        name
        for name, row in observed.items()
        if not row["relrowsecurity"]
        or not row["relforcerowsecurity"]
        or int(row["policy_count"]) < 1
    )
    if unsafe:
        raise AssertionError(f"RLS is not forced with a policy on: {unsafe}")

    project_policy_rows = await admin.fetch(
        """
        SELECT tablename, policyname, permissive, cmd
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = ANY($1::text[])
          AND policyname LIKE '%_project_%'
        """,
        sorted(PROJECT_SCOPED_TABLES),
    )
    project_policies: dict[str, dict[str, asyncpg.Record]] = {}
    for row in project_policy_rows:
        project_policies.setdefault(str(row["tablename"]), {})[
            str(row["cmd"]).upper()
        ] = row
    missing_project_tables = PROJECT_SCOPED_TABLES - set(project_policies)
    if missing_project_tables:
        raise AssertionError(
            "missing project RLS policies: "
            f"{sorted(missing_project_tables)}"
        )
    for table in PROJECT_SCOPED_TABLES:
        commands = project_policies[table]
        if set(commands) != {"SELECT", "INSERT", "UPDATE", "DELETE"}:
            raise AssertionError(
                f"incomplete project RLS command policies on {table}: "
                f"{sorted(commands)}"
            )
        expected = "PERMISSIVE" if table == "project_memberships" else "RESTRICTIVE"
        unexpected = sorted(
            command
            for command, row in commands.items()
            if str(row["permissive"]).upper() != expected
        )
        if unexpected:
            raise AssertionError(
                f"unsafe project RLS policy mode on {table}: {unexpected}"
            )
    creator_function = await admin.fetchrow(
        """
        SELECT procedure.prosecdef, role.rolname
        FROM pg_proc procedure
        JOIN pg_roles role ON role.oid = procedure.proowner
        JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = 'public'
          AND procedure.proname = 'akc_is_current_project_creator'
        """
    )
    if (
        creator_function is None
        or not bool(creator_function["prosecdef"])
        or str(creator_function["rolname"]) != "akc_dispatch_worker"
    ):
        raise AssertionError("project creator bootstrap function is not safely owned")


async def _verify_role_membership(
    admin: asyncpg.Connection[asyncpg.Record],
) -> None:
    expected = {
        ("akc_scheduler_runtime", "akc_scheduler"): True,
        ("akc_scheduler_runtime", "akc_dispatch_worker"): False,
        ("akc_dispatch_runtime", "akc_dispatch_worker"): True,
        ("akc_dispatch_runtime", "akc_scheduler"): False,
        ("akc_scheduler", "akc_dispatch_worker"): False,
        ("akc_dispatch_worker", "akc_scheduler"): False,
    }
    for (member, role), allowed in expected.items():
        actual = await admin.fetchval(
            "SELECT pg_has_role($1, $2, 'MEMBER')",
            member,
            role,
        )
        if bool(actual) is not allowed:
            raise AssertionError(f"unexpected role membership: {member} -> {role}")

    rows = await admin.fetch(
        """
        SELECT rolname, rolcanlogin, rolinherit, rolbypassrls, rolsuper,
               rolcreaterole, rolcreatedb, rolreplication
        FROM pg_roles
        WHERE rolname = ANY($1::text[])
        """,
        [
            "akc_scheduler",
            "akc_dispatch_worker",
            "akc_scheduler_runtime",
            "akc_dispatch_runtime",
        ],
    )
    roles = {str(row["rolname"]): row for row in rows}
    if len(roles) != 4:
        raise AssertionError("required scheduler roles are missing")
    for name in ("akc_scheduler", "akc_dispatch_worker"):
        row = roles[name]
        if row["rolcanlogin"] or row["rolinherit"] or not row["rolbypassrls"]:
            raise AssertionError(f"unsafe effective role attributes: {name}")
    for name in ("akc_scheduler_runtime", "akc_dispatch_runtime"):
        row = roles[name]
        if not row["rolcanlogin"] or row["rolinherit"] or row["rolbypassrls"]:
            raise AssertionError(f"unsafe login role attributes: {name}")
    for name, row in roles.items():
        if any(
            bool(row[field])
            for field in ("rolsuper", "rolcreaterole", "rolcreatedb", "rolreplication")
        ):
            raise AssertionError(f"privileged scheduler role: {name}")


async def _verify_scheduler_capabilities(parts: ConnectionParts) -> None:
    host = parts["host"]
    port = parts["port"]
    database = parts["database"]
    scheduler_settings = SchedulerSettings(
        env="test",
        database_url=(
            "postgresql+asyncpg://akc_scheduler_runtime:"
            f"akc_scheduler_dev_only_change_me@{host}:{port}/{database}"
        ),
    )
    dispatch_settings = SchedulerSettings(
        env="test",
        database_url=(
            "postgresql+asyncpg://akc_dispatch_runtime:"
            f"akc_dispatch_dev_only_change_me@{host}:{port}/{database}"
        ),
    )
    scheduler_engine = create_scheduler_engine(scheduler_settings)
    dispatch_engine = create_dispatch_engine(dispatch_settings)
    try:
        scheduler_capability = await verify_scheduler_database(
            scheduler_engine,
            scheduler_settings,
        )
        dispatch_capability = await verify_dispatch_database(
            dispatch_engine,
            dispatch_settings,
        )
        if (
            scheduler_capability.effective_role != "akc_scheduler"
            or dispatch_capability.effective_role != "akc_dispatch_worker"
        ):
            raise AssertionError("worker engines assumed an unexpected role")
        async with dispatch_engine.connect() as connection, connection.begin():
            # This executes the ranked one-candidate-per-tenant SKIP LOCKED
            # statement against real PostgreSQL, rather than only compiling it.
            await connection.execute(
                dispatch_claim_statement(
                    now=datetime.now(UTC),
                    dialect_name="postgresql",
                    candidate_tenants=64,
                )
            )
    finally:
        await scheduler_engine.dispose()
        await dispatch_engine.dispose()


async def _connect_dispatch_runtime(
    parts: ConnectionParts,
) -> asyncpg.Connection[asyncpg.Record]:
    password = "".join(("akc_dispatch", "_dev_only_change_me"))
    return await asyncpg.connect(
        user="akc_dispatch_runtime",
        password=password,
        server_settings={
            "application_name": "akc-ci-dispatch-fairness",
            "role": "akc_dispatch_worker",
        },
        **parts,
    )


async def _verify_dispatch_advisory_fairness(parts: ConnectionParts) -> None:
    """Prove tenant locks exclude one tenant without blocking another."""

    first = await _connect_dispatch_runtime(parts)
    second = await _connect_dispatch_runtime(parts)
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    job_a = uuid.uuid4()
    tenant_a_key = dispatch_advisory_lock_key("tenant", tenant_a)
    tenant_b_key = dispatch_advisory_lock_key("tenant", tenant_b)
    job_a_key = dispatch_advisory_lock_key("job", job_a)
    if len({tenant_a_key, tenant_b_key, job_a_key}) != 3:
        raise AssertionError("dispatch advisory lock namespaces collided")
    try:
        if not await first.fetchval(
            "SELECT pg_try_advisory_lock($1::bigint)",
            tenant_a_key,
        ):
            raise AssertionError("first tenant semaphore acquisition failed")
        if await second.fetchval(
            "SELECT pg_try_advisory_lock($1::bigint)",
            tenant_a_key,
        ):
            raise AssertionError("same tenant acquired capacity on two replicas")
        if not await second.fetchval(
            "SELECT pg_try_advisory_lock($1::bigint)",
            tenant_b_key,
        ):
            raise AssertionError("busy tenant blocked independent tenant capacity")
        if not await first.fetchval(
            "SELECT pg_try_advisory_lock($1::bigint)",
            job_a_key,
        ):
            raise AssertionError("job lock collided with tenant namespace")

        if not await first.fetchval(
            "SELECT pg_advisory_unlock($1::bigint)",
            job_a_key,
        ):
            raise AssertionError("job advisory lock did not release")
        if not await first.fetchval(
            "SELECT pg_advisory_unlock($1::bigint)",
            tenant_a_key,
        ):
            raise AssertionError("tenant advisory lock did not release")
        if not await second.fetchval(
            "SELECT pg_try_advisory_lock($1::bigint)",
            tenant_a_key,
        ):
            raise AssertionError("released tenant capacity was not reusable")
        if not await second.fetchval(
            "SELECT pg_advisory_unlock($1::bigint)",
            tenant_a_key,
        ):
            raise AssertionError("reacquired tenant lock did not release")

        # A terminated worker session is the final fail-safe for a cancellation
        # that interrupts explicit unlock.
        if not await first.fetchval(
            "SELECT pg_try_advisory_lock($1::bigint)",
            tenant_a_key,
        ):
            raise AssertionError("disconnect release setup failed")
        await first.close()
        if not await second.fetchval(
            "SELECT pg_try_advisory_lock($1::bigint)",
            tenant_a_key,
        ):
            raise AssertionError("closed worker session retained tenant capacity")
    finally:
        if not first.is_closed():
            await first.execute("SELECT pg_advisory_unlock_all()")
            await first.close()
        if not second.is_closed():
            await second.execute("SELECT pg_advisory_unlock_all()")
            await second.close()


async def _verify_tenant_isolation(
    admin: asyncpg.Connection[asyncpg.Record],
    parts: ConnectionParts,
) -> None:
    password = secrets.token_urlsafe(32)
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    tenant_c = uuid.uuid4()
    now = datetime.now(UTC)
    app: asyncpg.Connection[asyncpg.Record] | None = None
    await admin.execute(f"DROP ROLE IF EXISTS {APP_ROLE}")
    await admin.execute(
        f"""
        CREATE ROLE {APP_ROLE}
          LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
          NOREPLICATION NOBYPASSRLS PASSWORD '{password}'
        """
    )
    await admin.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    await admin.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
    )
    try:
        for tenant_id, suffix in ((tenant_a, "a"), (tenant_b, "b")):
            await admin.execute(
                """
                INSERT INTO tenants (
                    id, slug, name, plan_code, region, data_retention_days,
                    private_mode, external_transfer_allowed, training_opt_in,
                    preview_pii_masking, created_at, updated_at
                ) VALUES (
                    $1, $2, $3, 'free', 'ap-northeast', 7,
                    true, false, false, true, $4, $4
                )
                """,
                tenant_id,
                f"ci-rls-{suffix}-{tenant_id.hex}",
                f"CI tenant {suffix}",
                now,
            )
        app = await asyncpg.connect(
            user=APP_ROLE,
            password=password,
            **parts,
        )
        if await app.fetchval("SELECT count(*) FROM tenants") != 0:
            raise AssertionError("tenant rows are visible without an RLS context")
        for expected, forbidden in ((tenant_a, tenant_b), (tenant_b, tenant_a)):
            transaction = app.transaction()
            await transaction.start()
            try:
                await app.execute(
                    "SELECT set_config('app.tenant_id', $1, true)",
                    str(expected),
                )
                visible = {row["id"] for row in await app.fetch("SELECT id FROM tenants")}
                if visible != {expected} or forbidden in visible:
                    raise AssertionError("cross-tenant read escaped the RLS policy")
            finally:
                await transaction.rollback()

        transaction = app.transaction()
        await transaction.start()
        try:
            await app.execute(
                "SELECT set_config('app.tenant_id', $1, true)",
                str(tenant_a),
            )
            try:
                await app.execute(
                    """
                    INSERT INTO tenants (
                        id, slug, name, plan_code, region, data_retention_days,
                        private_mode, external_transfer_allowed, training_opt_in,
                        preview_pii_masking, created_at, updated_at
                    ) VALUES (
                        $1, $2, 'cross-tenant', 'free', 'ap-northeast', 7,
                        true, false, false, true, $3, $3
                    )
                    """,
                    tenant_c,
                    f"ci-rls-c-{tenant_c.hex}",
                    now,
                )
            except asyncpg.InsufficientPrivilegeError:
                pass
            else:
                raise AssertionError("cross-tenant write escaped the RLS WITH CHECK")
        finally:
            await transaction.rollback()
    finally:
        if app is not None:
            await app.close()
        await admin.execute(
            "DELETE FROM tenants WHERE id = ANY($1::uuid[])",
            [tenant_a, tenant_b],
        )
        await admin.execute(f"DROP OWNED BY {APP_ROLE}")
        await admin.execute(f"DROP ROLE {APP_ROLE}")


async def _verify(admin_url: str) -> None:
    parts = _connection_parts(admin_url)
    admin = await asyncpg.connect(admin_url)
    try:
        await _verify_schema(admin)
        await _verify_role_membership(admin)
        await _verify_tenant_isolation(admin, parts)
    finally:
        await admin.close()
    await _verify_scheduler_capabilities(parts)
    await _verify_dispatch_advisory_fairness(parts)


async def _main() -> None:
    args = _arguments()
    admin_url = _admin_url()
    if args.prepare_roles:
        await _prepare_roles(admin_url)
        print("CI PostgreSQL roles prepared")
        return
    await _verify(admin_url)
    print("PostgreSQL migration, RLS, and worker-role gate passed")


if __name__ == "__main__":
    asyncio.run(_main())
