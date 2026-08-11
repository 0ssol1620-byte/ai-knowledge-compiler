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

Five things this asserts, in order of what they are worth:

1. Every tenant-scoped table has RLS, FORCE RLS and at least one policy.
2. The policies actually isolate: a role holding exactly the union of the real
   worker grants, with no BYPASSRLS and no ownership, cannot read, write or
   guess its way into another tenant's rows.
3. The five append-only ledgers hold no UPDATE/DELETE grant or policy.
4. The control-plane boundary is exactly the approved one. A migration that
   grants a control-plane role an eighth table fails here with its name, which
   is the whole reason ``control_plane_registry.py`` exists.
5. No granted operation is silently default-deny. A ``RESTRICTIVE`` policy
   grants nothing, so a role holding SELECT on a table whose every policy is
   restrictive sees zero rows and no error — the failure mode that would make
   arming day look like a data-loss incident.

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

from control_plane_registry import (  # noqa: E402
    CLAIM_BROKER_RETURN_COLUMNS,
    CLAIM_BROKER_ROLE,
    CLAIM_BROKERS,
    CONTROL_PLANE_ROLE,
    CONTROL_PLANE_SENSITIVE_COLUMNS,
    CONTROL_PLANE_TABLES,
    HUMAN_PLANE_LOGIN_ROLE,
    HUMAN_PLANE_ROLE,
    LEASE_TABLES,
    LEASE_TABLES_WITHOUT_BROKER,
)
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
        "no longer blocked by the schema — 0034 moved every membership-referencing "
        "policy to the human plane and 0035 gave the polled queues a claim broker, "
        "both shadow-proven. Two gates now stand in front of the first removal, "
        "and neither is green: GATE 1, zero-row starvation detection wired into "
        "the poll loops (the logic exists, no loop calls it); GATE 2, a CI run "
        "against pgvector/pgvector:pg17 with the unmodified migration tree. The "
        "claim sites also do not yet call the broker, so removing BYPASSRLS today "
        "would take the lease-bearing tables to zero rows — silently. The sequence "
        "is docs/audit/V5_WORKER_AUTHZ_DECISION_PACKAGE.md section 10.",
    ),
    (
        "cross-tenant isolation proven as the real worker roles",
        "still blocked by the same attribute: while the worker roles hold BYPASSRLS "
        "they see every tenant by definition, so isolation is proven here against a "
        "role holding their exact grant surface without it, and against the real "
        "roles only in the throwaway cluster the shadow harness builds.",
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


def _verify_control_plane_boundary(receipt: dict[str, Any]) -> None:
    """Item 4: the cross-tenant surface is the approved one, and no wider.

    Two directions, and both matter. A table granted to a control-plane role but
    not listed is an unreviewed widening. A listed table the catalog does not
    grant means the registry is describing a schema that no longer exists, which
    is how a boundary document quietly stops being about anything.
    """

    granted = {
        table["table"]
        for table in receipt["tables"]
        if CONTROL_PLANE_ROLE in table["grants"]
    }
    approved = set(CONTROL_PLANE_TABLES)
    if unapproved := sorted(granted - approved):
        raise GateFailure(
            f"{CONTROL_PLANE_ROLE} is granted tables outside the Control Plane "
            f"Authorization Boundary: {', '.join(unapproved)}. Admitting one is a "
            "founder decision — record it in infra/postgres/control_plane_registry.py "
            "with the reason, and say why it holds no tenant data-plane content."
        )
    if stale := sorted(approved - granted):
        raise GateFailure(
            "the control-plane registry lists tables the catalog does not grant: "
            + ", ".join(stale)
        )

    policed = {
        table["table"]
        for table in receipt["tables"]
        for policy in table["policies"]
        if "_control_plane_" in policy["name"]
    }
    if unpoliced := sorted(approved - policed):
        raise GateFailure(
            "control-plane tables with no purpose-gated policy: " + ", ".join(unpoliced)
        )
    borrowed = sorted(
        f"{table['table']}.{policy['name']} -> {role}"
        for table in receipt["tables"]
        for policy in table["policies"]
        if "_control_plane_" in policy["name"]
        for role in policy["roles"]
        if role != CONTROL_PLANE_ROLE
    )
    if borrowed:
        raise GateFailure(
            "a control-plane policy admits a role other than "
            f"{CONTROL_PLANE_ROLE}: {', '.join(borrowed)}"
        )
    print(
        f"  control-plane boundary: {len(approved)} approved tables, "
        f"{len(policed)} purpose-gated, no role but {CONTROL_PLANE_ROLE}"
    )


_PERMISSIVE_COVERAGE_GAPS = """
SELECT pg_get_userbyid(acl.grantee) AS grantee,
       c.relname AS table_name,
       acl.privilege_type AS privilege
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) AS acl
JOIN (VALUES ('SELECT', 'r'), ('INSERT', 'a'), ('UPDATE', 'w'), ('DELETE', 'd'))
     AS w(privilege, polcmd) ON w.privilege = acl.privilege_type
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND c.relrowsecurity
  AND pg_get_userbyid(acl.grantee) LIKE 'akc\\_%' ESCAPE '\\'
  -- The isolation probe is a disposable superset of the worker surface, built
  -- and dropped by this same run. A leftover from a crashed run would otherwise
  -- report gaps that belong to no role that exists.
  AND pg_get_userbyid(acl.grantee) <> $1
  AND NOT EXISTS (
    SELECT 1 FROM pg_policy p
    WHERE p.polrelid = c.oid
      AND p.polpermissive
      AND p.polcmd IN ('*', w.polcmd)
      AND (p.polroles = '{0}'::oid[] OR acl.grantee = ANY (p.polroles))
  )
ORDER BY 1, 2, 3
"""

_SENSITIVE_COLUMNS_PRESENT = """
SELECT c.relname AS table_name, a.attname AS column_name
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid
WHERE n.nspname = 'public' AND a.attnum > 0 AND NOT a.attisdropped
"""


async def _verify_permissive_coverage(
    admin: asyncpg.Connection[asyncpg.Record],
) -> None:
    """Item 5: nothing is granted that no permissive policy would admit.

    This is the quiet one. A ``RESTRICTIVE`` policy only subtracts, so a role
    granted SELECT on a table carrying nothing but restrictive policies gets
    zero rows and no error — indistinguishable from an empty table until
    somebody notices the pipeline stopped. Two such pairs existed before
    ``0034`` and were invisible only because ``BYPASSRLS`` was masking them.
    """

    gaps = await admin.fetch(_PERMISSIVE_COVERAGE_GAPS, PROBE_ROLE)
    if gaps:
        listed = ", ".join(
            f"{row['grantee']} {row['table_name']}.{row['privilege']}" for row in gaps
        )
        raise GateFailure(
            "granted operations with no permissive policy to admit them — these "
            f"return zero rows rather than an error: {listed}"
        )
    print("  every granted operation has a permissive policy behind it")


async def _verify_claim_binding(
    admin: asyncpg.Connection[asyncpg.Record], receipt: dict[str, Any]
) -> None:
    """The lease-bearing tables all carry their restrictive claim binding.

    Derived from the catalog rather than the registry, then compared: a table
    that gains a lease and no binding is exactly the gap this is for.
    """

    columns: dict[str, set[str]] = {}
    for row in await admin.fetch(_SENSITIVE_COLUMNS_PRESENT):
        columns.setdefault(str(row["table_name"]), set()).add(str(row["column_name"]))
    derived = {
        name
        for name, present in columns.items()
        if {"lease_token", "lease_expires_at"} <= present
    }
    if derived != set(LEASE_TABLES):
        raise GateFailure(
            f"lease-bearing tables changed: catalog {sorted(derived)} vs registry "
            f"{sorted(LEASE_TABLES)}"
        )
    bound = {
        table["table"]
        for table in receipt["tables"]
        for policy in table["policies"]
        if policy["name"].endswith("_claim_binding") and policy["kind"] == "RESTRICTIVE"
    }
    if unbound := sorted(derived - bound):
        raise GateFailure(
            "lease-bearing tables with no restrictive claim binding: "
            + ", ".join(unbound)
        )
    missing = sorted(
        f"{table}.{column}"
        for table, expected in CONTROL_PLANE_SENSITIVE_COLUMNS.items()
        for column in expected
        if column not in columns.get(table, set())
    )
    if missing:
        raise GateFailure(
            "the control-plane sensitive-column record names columns the catalog "
            "no longer has, so V5_CONTROL_PLANE_BOUNDARY.md is describing a schema "
            f"that moved: {', '.join(missing)}"
        )
    print(f"  lease-bearing tables with a restrictive claim binding: {len(bound)}")


_BROKER_FUNCTIONS = """
SELECT p.proname AS name,
       pg_get_userbyid(p.proowner) AS owner,
       p.prosecdef AS security_definer,
       coalesce(array_to_string(p.proconfig, ','), '') AS config,
       coalesce(
         (SELECT array_agg(a.attname ORDER BY a.ordinality)
          FROM unnest(p.proargnames, p.proargmodes)
               WITH ORDINALITY AS a(attname, mode, ordinality)
          WHERE a.mode = 't'), ARRAY[]::text[]) AS out_columns,
       coalesce(
         (SELECT array_agg(acl.grantee_name ORDER BY acl.grantee_name)
          FROM (
            SELECT CASE WHEN g.grantee = 0 THEN 'PUBLIC'
                        ELSE pg_get_userbyid(g.grantee) END AS grantee_name
            FROM aclexplode(p.proacl) AS g
            WHERE g.privilege_type = 'EXECUTE'
          ) AS acl), ARRAY[]::text[]) AS executors
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND p.proname = ANY($1::text[])
ORDER BY 1
"""


async def _verify_claim_brokers(
    admin: asyncpg.Connection[asyncpg.Record], receipt: dict[str, Any]
) -> None:
    """The brokers are the only cross-tenant claim path, and are shaped as agreed.

    Founder decision F-1 chose a ``SECURITY DEFINER`` broker over granting each
    worker a cross-tenant ``SELECT`` on its queue, on the strength of one
    property: the broker returns five identifiers rather than rows. If that
    surface grows, the decision it was made on no longer holds — so it is
    checked here rather than trusted to review.
    """

    if set(CLAIM_BROKERS) | set(LEASE_TABLES_WITHOUT_BROKER) != set(LEASE_TABLES):
        raise GateFailure(
            "the claim-broker registry does not cover the lease surface: "
            f"{sorted(set(CLAIM_BROKERS) | set(LEASE_TABLES_WITHOUT_BROKER))} "
            f"vs {sorted(LEASE_TABLES)}"
        )
    expected = {function for function, _role in CLAIM_BROKERS.values()}
    rows = {
        str(row["name"]): row
        for row in await admin.fetch(_BROKER_FUNCTIONS, sorted(expected))
    }
    if missing := sorted(expected - set(rows)):
        raise GateFailure("claim brokers absent from the catalog: " + ", ".join(missing))

    for queue, (function, role) in sorted(CLAIM_BROKERS.items()):
        row = rows[function]
        if str(row["owner"]) != CLAIM_BROKER_ROLE or not row["security_definer"]:
            raise GateFailure(
                f"{function} is owned by {row['owner']} "
                f"(security_definer={row['security_definer']}); expected "
                f"{CLAIM_BROKER_ROLE} and SECURITY DEFINER"
            )
        if "search_path=pg_catalog, public" not in str(row["config"]):
            raise GateFailure(
                f"{function} has no pinned search_path ({row['config']!r}); a "
                "definer function without one can be aimed at a caller's schema"
            )
        surface = tuple(row["out_columns"])
        if surface != CLAIM_BROKER_RETURN_COLUMNS:
            raise GateFailure(
                f"{function} returns {surface} — founder decision F-1 fixed the "
                f"surface at {CLAIM_BROKER_RETURN_COLUMNS}, and the decision to "
                "prefer a broker over a cross-tenant SELECT rests on it"
            )
        executors = sorted(row["executors"])
        if "PUBLIC" in executors:
            raise GateFailure(
                f"{function} is executable by PUBLIC — PostgreSQL grants that by "
                "default and the migration must revoke it"
            )
        if role not in executors:
            raise GateFailure(f"{function} is not executable by {role} ({executors})")
        if extra := sorted(set(executors) - {role, CLAIM_BROKER_ROLE}):
            raise GateFailure(
                f"{function} is executable by roles outside its queue: {extra}"
            )
        del queue

    broker_role = next(
        (role for role in receipt["roles"] if role["rolname"] == CLAIM_BROKER_ROLE),
        None,
    )
    if broker_role is None:
        raise GateFailure(f"{CLAIM_BROKER_ROLE} does not exist; 0035 did not run")
    unsafe = sorted(
        attribute
        for attribute in ("rolsuper", "rolbypassrls", "rolcanlogin", "rolcreaterole")
        if broker_role[attribute]
    )
    if unsafe:
        raise GateFailure(
            f"{CLAIM_BROKER_ROLE} holds {', '.join(unsafe)} — a definer function "
            "owned by a bypassing or loginable role is a blanket exemption with a "
            "function in front of it"
        )
    print(
        f"  claim brokers: {len(expected)} definer functions returning "
        f"{len(CLAIM_BROKER_RETURN_COLUMNS)} identifiers, pinned search_path, "
        f"no PUBLIC execute; {CLAIM_BROKER_ROLE} holds no bypass and cannot log in"
    )


def _verify_plane_roles(receipt: dict[str, Any]) -> None:
    """The human plane is a plane: separate login, no inheritance, no bypass."""

    roles = {role["rolname"]: role for role in receipt["roles"]}
    for name in (HUMAN_PLANE_ROLE, HUMAN_PLANE_LOGIN_ROLE):
        role = roles.get(name)
        if role is None:
            raise GateFailure(f"{name} does not exist; 0034 did not run")
        unsafe = sorted(
            attribute
            for attribute in ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb")
            if role[attribute]
        )
        if unsafe:
            raise GateFailure(f"{name} holds {', '.join(unsafe)}")
        if role["rolinherit"]:
            # An INHERIT login principal would carry the plane's rights without
            # SET ROLE, which is the separation this exists to make.
            raise GateFailure(f"{name} is INHERIT; the plane must be assumed, not held")
    memberships = {
        (member["member"], member["grantee_of"]) for member in receipt["role_memberships"]
    }
    if (HUMAN_PLANE_LOGIN_ROLE, HUMAN_PLANE_ROLE) not in memberships:
        raise GateFailure(
            f"{HUMAN_PLANE_LOGIN_ROLE} cannot assume {HUMAN_PLANE_ROLE}"
        )
    if inherited := sorted(
        grantee for member, grantee in memberships if member == HUMAN_PLANE_ROLE
    ):
        raise GateFailure(
            f"{HUMAN_PLANE_ROLE} is a member of {', '.join(inherited)}; the plane "
            "must be a leaf"
        )
    print(
        f"  {HUMAN_PLANE_LOGIN_ROLE} authenticates and assumes {HUMAN_PLANE_ROLE}, "
        "which holds no bypass and no memberships"
    )


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
        _verify_plane_roles(receipt)
        _verify_control_plane_boundary(receipt)
        await _verify_permissive_coverage(admin)
        await _verify_claim_binding(admin, receipt)
        await _verify_claim_brokers(admin, receipt)
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
