"""Catalog-driven tenant-isolation gate.

The predecessor checks in ``verify_postgres_gate.py`` carried two hardcoded
table lists. A hardcoded list cannot fail for a table nobody remembered to add
to it, which is the only way this class of defect ever appears: a migration
gives a table a ``tenant_id`` and forgets the row-level security that is
supposed to travel with it. ``collection_metadata_backfill_checkpoints`` sat
that way from 0026 until the privilege receipt found it by reading the catalog.

So the inventory here comes from ``pg_class``/``pg_attribute`` at run time.
Every table carrying ``tenant_id`` is in scope automatically, and a new one
arrives already covered.

Reuses ``scripts/generate_privilege_receipt.py`` rather than re-deriving the
catalog queries — that script is the single definition of what a privilege
receipt contains.

Three things this asserts, in order of what they are worth:

1. Every tenant-scoped table has RLS, FORCE RLS and at least one policy.
2. The policies actually isolate: a role holding exactly the union of the real
   worker grants, with no BYPASSRLS and no ownership, cannot read, write or
   guess its way into another tenant's rows.
3. The five append-only ledgers hold no UPDATE/DELETE grant or policy.

What it deliberately does *not* claim is recorded in ``PENDING_INVARIANTS``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import asyncpg  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_privilege_receipt import (  # noqa: E402
    APPEND_ONLY,
    GLOBAL_CONTROL,
    collect,
    findings,
)

PROBE_ROLE = "akc_ci_worker_surface_probe"

WORKER_ROLES = (
    "akc_analysis_worker",
    "akc_deletion_worker",
    "akc_dispatch_worker",
    "akc_gpu_worker",
    "akc_payment_worker",
    "akc_scheduler",
    "akc_url_fetcher",
)

# Invariants this gate cannot assert yet, each with the reason. Printed on every
# run: a gate that quietly checks less than it appears to is worse than no gate.
PENDING_INVARIANTS = (
    (
        "worker roles are NOBYPASSRLS",
        "blocked: the project-access policies added by 0015 reference memberships "
        "and project_memberships, which no worker role may read. Removing BYPASSRLS "
        "makes every worker query against those tables fail with "
        "'permission denied for table memberships'. See docs/audit/"
        "V5_WORKER_PRIVILEGE_BOUNDARY.md.",
    ),
    (
        "cross-tenant isolation proven as the real worker roles",
        "blocked by the same item: while the worker roles hold BYPASSRLS they see "
        "every tenant by definition, so isolation is proven against a role holding "
        "their exact grant surface without BYPASSRLS instead.",
    ),
)


class GateFailure(AssertionError):
    """A tenant-isolation invariant did not hold."""


def _admin_url() -> str:
    value = os.environ.get("AKC_CI_ADMIN_DATABASE_URL", "")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"postgresql", "postgres"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.path.strip("/")
    ):
        raise RuntimeError("the schema security gate requires an explicit loopback URL")
    return value


def _connection_parts(url: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 5432,
        "database": parsed.path.strip("/"),
    }


def tenant_scoped(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    """Every table the catalog says carries a tenant dimension."""

    return [
        table
        for table in receipt["tables"]
        if table["tenant_id"] and table["table"] not in GLOBAL_CONTROL
    ]


def worker_grant_surface(receipt: dict[str, Any]) -> dict[str, set[str]]:
    """The union of what the seven runtime roles may do, per table.

    This is what the probe role is given. Anything wider proves isolation
    against a role more privileged than the ones that actually run, which is the
    flaw the disposable ``GRANT ... ON ALL TABLES`` probe had.
    """

    surface: dict[str, set[str]] = {}
    for table in receipt["tables"]:
        for grantee, privileges in table["grants"].items():
            if grantee not in WORKER_ROLES:
                continue
            allowed = {p.rstrip("*") for p in privileges}
            surface.setdefault(table["table"], set()).update(allowed)
    return surface


_COLUMN_GRANTS = """
SELECT c.relname AS table_name,
       a.attname AS column_name,
       acl.privilege_type AS privilege
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid
CROSS JOIN LATERAL aclexplode(a.attacl) AS acl
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
  AND pg_get_userbyid(acl.grantee) = ANY($1::text[])
ORDER BY 1, 2, 3
"""


async def worker_column_surface(
    admin: asyncpg.Connection[asyncpg.Record],
) -> dict[tuple[str, str], set[str]]:
    """Column-level grants held by the worker roles.

    The privilege receipt records ``pg_class.relacl`` only. Workers also hold
    column-scoped UPDATE — that is how ``outbox_events.published_at`` is
    writable while the table is not — so a probe built from table ACLs alone is
    narrower than the real runtime surface and would prove isolation against a
    role that cannot even attempt the writes the workers make.
    """

    surface: dict[tuple[str, str], set[str]] = {}
    for row in await admin.fetch(_COLUMN_GRANTS, list(WORKER_ROLES)):
        key = (str(row["table_name"]), str(row["column_name"]))
        surface.setdefault(key, set()).add(str(row["privilege"]))
    return surface


def _verify_tenant_rls(receipt: dict[str, Any]) -> None:
    """Item 1: the inventory is complete and every member is protected."""

    scoped = tenant_scoped(receipt)
    if not scoped:
        raise GateFailure("catalog reported no tenant-scoped tables; the query is wrong")
    unprotected = sorted(
        table["table"]
        for table in scoped
        if not table["rls_enabled"] or not table["rls_forced"] or table["policy_count"] < 1
    )
    if unprotected:
        raise GateFailure(
            "tables carry tenant_id without forced RLS and a policy: " + ", ".join(unprotected)
        )
    print(f"  tenant-scoped tables with FORCE RLS and >=1 policy: {len(scoped)}/{len(scoped)}")


_APPEND_ONLY_COLUMN_GRANTS = """
SELECT c.relname AS table_name,
       a.attname AS column_name,
       pg_get_userbyid(acl.grantee) AS grantee,
       acl.privilege_type AS privilege
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid
CROSS JOIN LATERAL aclexplode(a.attacl) AS acl
WHERE n.nspname = 'public'
  AND c.relname = ANY($1::text[])
  AND acl.grantee <> c.relowner
  -- Only mutation widens an append-only ledger. PostgreSQL grants SELECT,
  -- INSERT, UPDATE and REFERENCES at column level; DELETE and TRUNCATE exist
  -- only on the table, so UPDATE is the whole column-level violation set.
  -- Without this filter the gate reports a legitimate column SELECT grant as
  -- "widened", which is safe but wrong, and would block an analytics role for
  -- a reason the message does not describe.
  AND acl.privilege_type = 'UPDATE'
ORDER BY 1, 2, 3
"""


async def _verify_append_only(
    admin: asyncpg.Connection[asyncpg.Record], receipt: dict[str, Any]
) -> None:
    """Item 3: the evidence ledgers are still append-only.

    Table ACLs are not sufficient on their own. PostgreSQL lets UPDATE be
    granted per column, which is how ``outbox_events.published_at`` is writable
    while the table is not — so a single ``GRANT UPDATE(col)`` on a ledger would
    make it mutable while ``pg_class.relacl`` still looked clean. The privilege
    receipt records only table ACLs, so this reads ``pg_attribute.attacl``
    straight from the catalog rather than trusting the receipt for it.
    """

    violations: list[str] = []
    for table in receipt["tables"]:
        if table["table"] not in APPEND_ONLY:
            continue
        for policy in table["policies"]:
            if policy["command"] in {"UPDATE", "DELETE", "ALL"}:
                violations.append(f"{table['table']}: {policy['command']} policy {policy['name']}")
        for grantee, privileges in table["grants"].items():
            if grantee == table["owner"]:
                continue
            bad = sorted({p.rstrip("*") for p in privileges} & {"UPDATE", "DELETE", "TRUNCATE"})
            if bad:
                violations.append(f"{table['table']}: grants {'+'.join(bad)} to {grantee}")
    for row in await admin.fetch(_APPEND_ONLY_COLUMN_GRANTS, sorted(APPEND_ONLY)):
        violations.append(
            f"{row['table_name']}: grants {row['privilege']} "
            f"({row['column_name']}) to {row['grantee']}"
        )
    if violations:
        raise GateFailure("append-only ledgers were widened: " + "; ".join(violations))
    print(
        f"  append-only ledgers with no UPDATE/DELETE grant or policy: {len(APPEND_ONLY)} "
        "(table and column ACLs)"
    )


def _verify_runtime_roles_are_not_owners(receipt: dict[str, Any]) -> None:
    """Negative test 9: no runtime role owns an application table."""

    owned = sorted(
        table["table"] for table in receipt["tables"] if table["owner"] in WORKER_ROLES
    )
    if owned:
        raise GateFailure("worker roles own application tables: " + ", ".join(owned))
    superusers = sorted(
        role["rolname"]
        for role in receipt["roles"]
        if role["rolname"] in WORKER_ROLES and role["rolsuper"]
    )
    if superusers:
        raise GateFailure("worker roles are SUPERUSER: " + ", ".join(superusers))
    print(f"  worker roles owning no application table and not SUPERUSER: {len(WORKER_ROLES)}")


def _report_bypassrls(receipt: dict[str, Any]) -> list[str]:
    """Negative test 8, reported rather than enforced. See PENDING_INVARIANTS."""

    holders = sorted(
        role["rolname"]
        for role in receipt["roles"]
        if role["rolname"] in WORKER_ROLES and role["rolbypassrls"]
    )
    if len(holders) > len(WORKER_ROLES):
        raise GateFailure("more roles hold BYPASSRLS than the known worker set")
    unknown = sorted(
        role["rolname"]
        for role in receipt["roles"]
        if role["rolbypassrls"]
        and role["rolname"].startswith("akc_")
        and role["rolname"] not in WORKER_ROLES
    )
    if unknown:
        raise GateFailure("an unexpected akc_ role holds BYPASSRLS: " + ", ".join(unknown))
    print(f"  worker roles holding BYPASSRLS: {len(holders)}/{len(WORKER_ROLES)} (not yet removed)")
    return holders


async def _seed_tenant(
    admin: asyncpg.Connection[asyncpg.Record], label: str
) -> dict[str, uuid.UUID]:
    tenant = uuid.uuid4()
    event = uuid.uuid4()
    now = datetime.now(UTC)
    await admin.execute(
        """
        INSERT INTO tenants (
            id, slug, name, plan_code, region, data_retention_days,
            private_mode, external_transfer_allowed, training_opt_in,
            preview_pii_masking, created_at, updated_at
        ) VALUES ($1, $2, $3, 'free', 'ap-northeast', 7, true, false, false, true, $4, $4)
        """,
        tenant, f"ci-gate-{label}-{tenant.hex}", f"CI gate {label}", now,
    )
    await admin.execute(
        """
        INSERT INTO outbox_events (
            id, tenant_id, aggregate_type, aggregate_id, event_type,
            payload, available_at, attempts, created_at
        ) VALUES ($1, $2, 'tenant', $2, 'ci.gate.probe.v1', '{}', $3, 0, $3)
        """,
        event, tenant, now,
    )
    return {"tenant": tenant, "event": event}


async def _verify_isolation(
    admin: asyncpg.Connection[asyncpg.Record],
    parts: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    """Negative tests 1-7 against the real worker grant surface."""

    password = secrets.token_urlsafe(32)
    surface = worker_grant_surface(receipt)
    probe: asyncpg.Connection[asyncpg.Record] | None = None
    seeded: list[dict[str, uuid.UUID]] = []
    # A run that died between GRANT and cleanup leaves a role holding
    # privileges, and a plain DROP ROLE fails on the dependency. Revoke first so
    # the gate is rerunnable rather than needing a hand-cleaned database.
    await admin.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PROBE_ROLE}') THEN
                EXECUTE 'DROP OWNED BY {PROBE_ROLE}';
                EXECUTE 'DROP ROLE {PROBE_ROLE}';
            END IF;
        END
        $$
        """  # noqa: S608 - PROBE_ROLE is a module constant, never input.
    )
    await admin.execute(
        f"""
        CREATE ROLE {PROBE_ROLE}
          LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
          NOREPLICATION NOBYPASSRLS PASSWORD '{password}'
        """
    )
    await admin.execute(f"GRANT USAGE ON SCHEMA public TO {PROBE_ROLE}")
    for table, privileges in sorted(surface.items()):
        await admin.execute(
            f'GRANT {", ".join(sorted(privileges))} ON TABLE "{table}" TO {PROBE_ROLE}'
        )
    columns = await worker_column_surface(admin)
    for (table, column), privileges in sorted(columns.items()):
        await admin.execute(
            f'GRANT {", ".join(sorted(privileges))} ("{column}") '
            f'ON TABLE "{table}" TO {PROBE_ROLE}'
        )
    granted_tables = len(surface)
    granted_columns = len(columns)
    try:
        alpha = await _seed_tenant(admin, "alpha")
        beta = await _seed_tenant(admin, "beta")
        seeded = [alpha, beta]
        probe = await asyncpg.connect(user=PROBE_ROLE, password=password, **parts)

        # 4. missing tenant context -> fail closed (no rows, never all rows).
        for table in ("tenants", "outbox_events"):
            visible = await probe.fetchval(f'SELECT count(*) FROM "{table}"')  # noqa: S608
            if int(visible) != 0:
                raise GateFailure(f"{table} rows are visible with no tenant context")
        print("  [4] missing tenant context yields zero rows")

        # 1. cross-tenant SELECT, and 3. direct-PK guessing.
        for own, other in ((alpha, beta), (beta, alpha)):
            async with probe.transaction():
                await probe.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(own["tenant"])
                )
                rows = {r["id"] for r in await probe.fetch("SELECT id FROM tenants")}
                if rows != {own["tenant"]}:
                    raise GateFailure("cross-tenant SELECT escaped the policy")
                guessed = await probe.fetchval(
                    "SELECT count(*) FROM tenants WHERE id = $1", other["tenant"]
                )
                if int(guessed) != 0:
                    raise GateFailure("a guessed primary key reached another tenant")
                guessed_event = await probe.fetchval(
                    "SELECT count(*) FROM outbox_events WHERE id = $1", other["event"]
                )
                if int(guessed_event) != 0:
                    raise GateFailure("a guessed outbox primary key reached another tenant")
        print("  [1] cross-tenant SELECT blocked")
        print("  [3] direct primary-key guessing blocked")

        # 2. cross-tenant INSERT / UPDATE / DELETE.
        async with probe.transaction():
            await probe.execute(
                "SELECT set_config('app.tenant_id', $1, true)", str(alpha["tenant"])
            )
            try:
                await probe.execute(
                    """
                    INSERT INTO outbox_events (
                        id, tenant_id, aggregate_type, aggregate_id, event_type,
                        payload, available_at, attempts, created_at
                    ) VALUES ($1, $2, 'tenant', $2, 'ci.gate.cross.v1', '{}', now(), 0, now())
                    """,
                    uuid.uuid4(), beta["tenant"],
                )
            except asyncpg.InsufficientPrivilegeError:
                pass
            else:
                raise GateFailure("cross-tenant INSERT escaped the WITH CHECK")
        # A rejected INSERT aborts its transaction, so the write probes that
        # follow need their own.
        async with probe.transaction():
            await probe.execute(
                "SELECT set_config('app.tenant_id', $1, true)", str(alpha["tenant"])
            )
            deleted = await probe.execute(
                "DELETE FROM outbox_events WHERE id = $1", beta["event"]
            )
            if deleted != "DELETE 0":
                raise GateFailure(f"cross-tenant DELETE affected rows: {deleted}")
            updated = await probe.execute(
                "UPDATE outbox_events SET attempts = attempts + 1 WHERE id = $1",
                beta["event"],
            )
            if not updated.startswith("UPDATE 0"):
                raise GateFailure(f"cross-tenant UPDATE affected rows: {updated}")
        print("  [2] cross-tenant INSERT blocked, cross-tenant DELETE affected 0 rows")

        # 5. spoofed context, and 6. context disagreeing with the job row.
        async with probe.transaction():
            await probe.execute("SELECT set_config('app.tenant_id', $1, true)", str(uuid.uuid4()))
            stolen = await probe.fetchval("SELECT count(*) FROM outbox_events")
            if int(stolen) != 0:
                raise GateFailure("a spoofed tenant context returned rows")
        async with probe.transaction():
            await probe.execute(
                "SELECT set_config('app.tenant_id', $1, true)", str(alpha["tenant"])
            )
            mismatched = await probe.fetchval(
                "SELECT count(*) FROM outbox_events WHERE id = $1", beta["event"]
            )
            if int(mismatched) != 0:
                raise GateFailure("a job row from another tenant was reachable")
        print("  [5] spoofed tenant context returns nothing")
        print("  [6] job row whose tenant disagrees with the context is unreachable")

        # 7. append-only ledgers reject UPDATE and DELETE for this surface.
        for ledger in sorted(APPEND_ONLY):
            for privilege in ("UPDATE", "DELETE"):
                allowed = await probe.fetchval(
                    "SELECT has_table_privilege($1, $2, $3)",
                    PROBE_ROLE, f"public.{ledger}", privilege,
                )
                if bool(allowed):
                    raise GateFailure(f"{ledger} grants {privilege} to the worker surface")
        print(f"  [7] append-only ledgers reject UPDATE/DELETE ({len(APPEND_ONLY)} ledgers)")
        print(
            "  probe role held the real worker surface: "
            f"{granted_tables} tables, {granted_columns} column grants"
        )
    finally:
        if probe is not None:
            await probe.close()
        for entry in seeded:
            await admin.execute("DELETE FROM outbox_events WHERE tenant_id = $1", entry["tenant"])
            await admin.execute("DELETE FROM tenants WHERE id = $1", entry["tenant"])
        await admin.execute(f"REASSIGN OWNED BY {PROBE_ROLE} TO CURRENT_USER")
        await admin.execute(f"DROP OWNED BY {PROBE_ROLE}")
        await admin.execute(f"DROP ROLE {PROBE_ROLE}")


def write_receipt(receipt: dict[str, Any], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"receipt written to {out}")


async def run(admin_url: str) -> dict[str, Any]:
    parts = _connection_parts(admin_url)
    admin = await asyncpg.connect(admin_url)
    try:
        receipt: dict[str, Any] = await collect(admin)
        receipt["findings"] = findings(receipt)
        print(f"catalog: {receipt['table_count']} tables at {receipt['alembic_revision']}")
        _verify_tenant_rls(receipt)
        await _verify_append_only(admin, receipt)
        _verify_runtime_roles_are_not_owners(receipt)
        _report_bypassrls(receipt)
        await _verify_isolation(admin, parts, receipt)
    finally:
        await admin.close()
    print("\nnot asserted by this gate:")
    for name, reason in PENDING_INVARIANTS:
        print(f"  - {name}\n      {reason}")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-out", type=Path, default=None)
    args = parser.parse_args()
    receipt = asyncio.run(run(_admin_url()))
    if args.receipt_out is not None:
        write_receipt(receipt, args.receipt_out)
    print("\nschema security gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
