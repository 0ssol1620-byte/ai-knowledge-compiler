"""CI-only PostgreSQL migration, RLS, and worker-role verification."""

from __future__ import annotations

import argparse
import asyncio
import os
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

# The tenant-table inventory and the cross-tenant isolation probe used to live
# here as two hardcoded frozensets and a disposable role granted
# ``SELECT, INSERT, UPDATE, DELETE ON ALL TABLES`` — a role broader than any
# role that actually runs, so isolation was proven against a strawman. Both now
# live in ``schema_security_gate.py``, which reads the catalog: every table
# carrying ``tenant_id`` is in scope automatically, and the probe reproduces the
# real per-worker grant surface.
#
# What stays here is what that gate does not cover: role membership topology,
# the scheduler/dispatch capability contracts, and dispatch advisory fairness.

# Tables that carry project_id yet are deliberately not project-scoped. Named
# with the reason so the set cannot grow by accident: anything else with a
# project_id column and no project_memberships policy fails the gate.
PROJECT_SCOPE_EXCEPTIONS = frozenset(
    {
        # The membership table itself. A policy consulting project_memberships
        # to decide access to project_memberships would recurse.
        "project_memberships",
        # Pre-existing gap, not introduced here: trial_sessions carries
        # project_id but holds only a tenant-isolation policy. Recorded in
        # docs/audit/V5_WORKER_PRIVILEGE_BOUNDARY.md rather than closed here,
        # because changing its policy is a scope decision, not a repair.
        "trial_sessions",
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

    # Tenant-table RLS coverage is asserted from the catalog by
    # schema_security_gate.py. What remains here is the project-scope policy
    # *shape*, which that gate does not model: the inventory is every table the
    # catalog shows carrying a project policy, so a new one is covered on
    # arrival rather than when someone remembers to edit a list.
    project_policy_rows = await admin.fetch(
        """
        SELECT tablename, policyname, permissive, cmd
        FROM pg_policies
        WHERE schemaname = 'public'
          AND policyname LIKE '%_project_%'
        """
    )
    project_policies: dict[str, dict[str, asyncpg.Record]] = {}
    for row in project_policy_rows:
        project_policies.setdefault(str(row["tablename"]), {})[str(row["cmd"]).upper()] = row
    project_scoped_tables = frozenset(project_policies)
    if not project_scoped_tables:
        raise AssertionError("no project-scoped RLS policies found; the catalog query is wrong")
    # Completeness in the other direction: a table with project_id whose
    # policies never consult project_memberships is not project-scoped, whatever
    # its policies are named. Matching on the expression rather than the policy
    # name is what makes this catch a table added under a new convention.
    enforced = {
        str(row["relname"])
        for row in await admin.fetch(
            """
            SELECT DISTINCT class.relname
            FROM pg_class AS class
            JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
            JOIN pg_policy AS policy ON policy.polrelid = class.oid
            WHERE namespace.nspname = 'public'
              AND (
                COALESCE(pg_get_expr(policy.polqual, policy.polrelid), '')
                || COALESCE(pg_get_expr(policy.polwithcheck, policy.polrelid), '')
              ) LIKE '%project_memberships%'
            """
        )
    }
    with_project_column = {
        str(row["relname"])
        for row in await admin.fetch(
            """
            SELECT DISTINCT class.relname
            FROM pg_class AS class
            JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace
            JOIN pg_attribute AS attribute ON attribute.attrelid = class.oid
            WHERE namespace.nspname = 'public'
              AND class.relkind IN ('r', 'p')
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
              AND attribute.attname = 'project_id'
            """
        )
    }
    unguarded = sorted(with_project_column - enforced - PROJECT_SCOPE_EXCEPTIONS)
    if unguarded:
        raise AssertionError(
            "tables carry project_id but no policy consults project_memberships: "
            f"{unguarded}"
        )
    for table in project_scoped_tables:
        commands = project_policies[table]
        if set(commands) != {"SELECT", "INSERT", "UPDATE", "DELETE"}:
            raise AssertionError(
                f"incomplete project RLS command policies on {table}: {sorted(commands)}"
            )
        expected = "PERMISSIVE" if table == "project_memberships" else "RESTRICTIVE"
        unexpected = sorted(
            command
            for command, row in commands.items()
            if str(row["permissive"]).upper() != expected
        )
        if unexpected:
            raise AssertionError(f"unsafe project RLS policy mode on {table}: {unexpected}")
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


async def _verify(admin_url: str) -> None:
    parts = _connection_parts(admin_url)
    admin = await asyncpg.connect(admin_url)
    try:
        await _verify_schema(admin)
        await _verify_role_membership(admin)
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
