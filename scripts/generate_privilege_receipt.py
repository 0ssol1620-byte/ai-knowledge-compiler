"""Emit a machine-readable privilege receipt from a live PostgreSQL catalog.

The catalog is the only authority on who owns what and which rows a role can
reach. Migration source cannot answer it — RLS here is enabled through f-string
loops over table lists, so static analysis undercounts badly, and an offline
``alembic upgrade --sql`` run halts where a migration inspects the connection.
Two attempts at both are recorded as failed in
``docs/audit/V5_TENANT_SCOPE_SURVEY.md``.

So this connects to a database with ``alembic upgrade head`` applied and reads
``pg_class``, ``pg_policy``, ``pg_attribute`` and the relation ACLs directly.

Run against the CI PostgreSQL service, or any throwaway cluster:

    python scripts/generate_privilege_receipt.py --url postgresql://... \
        --out docs/audit/receipts/privilege-receipt.json

``--check`` compares against an existing receipt and exits non-zero on drift,
which is what makes this a gate rather than a report.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import asyncpg

SCHEMA = "tavonel.privilege-receipt.v1"

# Ledgers whose rows are evidence: written once, never revised. An append-only
# table wants INSERT and no UPDATE/DELETE — the asymmetry is the security
# property, so the receipt records it and the gate can assert it.
APPEND_ONLY = frozenset(
    {
        "attempt_validations",
        "semantic_health_events",
        "continuity_edges",
        "accepted_blocks",
        "arbitration_decisions",
    }
)

# Genuinely global: no tenant dimension exists to scope by. Everything else
# carrying tenant_id is expected to be tenant-scoped. Justifications live in
# docs/audit/V5_TENANT_SCOPE_SURVEY.md §4.
GLOBAL_CONTROL = frozenset(
    {
        "tenants",
        "users",
        "model_registry",
        "oidc_identities",
        "oidc_login_transactions",
        "alembic_version",
    }
)

_TABLES = """
SELECT c.relname AS table_name,
       pg_get_userbyid(c.relowner) AS owner,
       c.relrowsecurity AS rls_enabled,
       c.relforcerowsecurity AS rls_forced,
       c.relkind AS kind
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
ORDER BY c.relname
"""

_COLUMNS = """
SELECT c.relname AS table_name, a.attname AS column_name
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
  AND a.attnum > 0 AND NOT a.attisdropped
  AND a.attname IN ('tenant_id', 'workspace_id', 'project_id')
"""

_POLICIES = """
SELECT c.relname AS table_name,
       p.polname AS policy_name,
       CASE p.polcmd WHEN 'r' THEN 'SELECT' WHEN 'a' THEN 'INSERT'
                     WHEN 'w' THEN 'UPDATE' WHEN 'd' THEN 'DELETE'
                     WHEN '*' THEN 'ALL' ELSE p.polcmd::text END AS command,
       CASE WHEN p.polpermissive THEN 'PERMISSIVE' ELSE 'RESTRICTIVE' END AS kind,
       COALESCE(
         (SELECT array_agg(pg_get_userbyid(r) ORDER BY pg_get_userbyid(r))
          FROM unnest(p.polroles) AS r
          WHERE r <> 0), ARRAY['PUBLIC']) AS roles,
       pg_get_expr(p.polqual, p.polrelid) AS using_expr,
       pg_get_expr(p.polwithcheck, p.polrelid) AS check_expr
FROM pg_policy p
JOIN pg_class c ON c.oid = p.polrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
ORDER BY c.relname, p.polname
"""

# aclexplode turns the packed ACL into one row per (grantee, privilege), which
# is the shape a least-privilege review needs. A NULL relacl means default
# privileges, i.e. owner only — recorded as such rather than as "no grants".
_GRANTS = """
SELECT c.relname AS table_name,
       CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END AS grantee,
       a.privilege_type AS privilege,
       a.is_grantable AS grantable
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) AS a
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
ORDER BY c.relname, grantee, privilege
"""

_ROLES = """
SELECT rolname, rolsuper, rolbypassrls, rolcanlogin, rolcreaterole,
       rolcreatedb, rolreplication, rolinherit
FROM pg_roles
WHERE rolname NOT LIKE 'pg\\_%'
ORDER BY rolname
"""

_MEMBERSHIPS = """
SELECT pg_get_userbyid(m.member) AS member, pg_get_userbyid(m.roleid) AS grantee_of
FROM pg_auth_members m
ORDER BY 1, 2
"""


async def collect(conn: asyncpg.Connection) -> dict[str, Any]:
    tables = await conn.fetch(_TABLES)
    columns = await conn.fetch(_COLUMNS)
    policies = await conn.fetch(_POLICIES)
    grants = await conn.fetch(_GRANTS)
    roles = await conn.fetch(_ROLES)
    members = await conn.fetch(_MEMBERSHIPS)
    revision = await conn.fetchval("SELECT version_num FROM alembic_version")

    scope: dict[str, set[str]] = {}
    for row in columns:
        scope.setdefault(row["table_name"], set()).add(row["column_name"])

    by_table: dict[str, list[dict[str, Any]]] = {}
    for row in policies:
        by_table.setdefault(row["table_name"], []).append(
            {
                "name": row["policy_name"],
                "command": row["command"],
                "kind": row["kind"],
                "roles": list(row["roles"]),
                "using": row["using_expr"],
                "with_check": row["check_expr"],
            }
        )

    acl: dict[str, dict[str, list[str]]] = {}
    for row in grants:
        acl.setdefault(row["table_name"], {}).setdefault(row["grantee"], []).append(
            row["privilege"] + ("*" if row["grantable"] else "")
        )

    out_tables = []
    for row in tables:
        name = row["table_name"]
        cols = scope.get(name, set())
        pols = by_table.get(name, [])
        out_tables.append(
            {
                "table": name,
                "owner": row["owner"],
                "tenant_id": "tenant_id" in cols,
                "workspace_id": "workspace_id" in cols,
                "project_id": "project_id" in cols,
                "rls_enabled": row["rls_enabled"],
                "rls_forced": row["rls_forced"],
                "policy_count": len(pols),
                "policies": pols,
                "grants": {g: sorted(p) for g, p in sorted(acl.get(name, {}).items())},
                "append_only": name in APPEND_ONLY,
                "global_control": name in GLOBAL_CONTROL,
            }
        )

    return {
        "schema": SCHEMA,
        "alembic_revision": revision,
        "table_count": len(out_tables),
        "roles": [dict(r) for r in roles],
        "role_memberships": [dict(m) for m in members],
        "tables": out_tables,
    }


def findings(receipt: dict[str, Any]) -> list[dict[str, str]]:
    """Everything the receipt says is wrong, as data rather than prose."""
    out: list[dict[str, str]] = []
    for t in receipt["tables"]:
        name = t["table"]
        if t["tenant_id"] and not t["global_control"]:
            if not t["rls_enabled"]:
                out.append({"table": name, "finding": "tenant_id column but RLS not enabled"})
            elif t["policy_count"] == 0:
                out.append({"table": name, "finding": "RLS enabled but no policy — deny-all"})
            if t["rls_enabled"] and not t["rls_forced"]:
                out.append(
                    {"table": name, "finding": "RLS enabled but not FORCEd — owner bypasses"}
                )
        if t["append_only"]:
            for pol in t["policies"]:
                if pol["command"] in {"UPDATE", "DELETE", "ALL"}:
                    cmd, pname = pol["command"], pol["name"]
                    out.append(
                        {
                            "table": name,
                            "finding": f"append-only ledger has a {cmd} policy ({pname})",
                        }
                    )
            for grantee, privs in t["grants"].items():
                # The owner's full rights come with ownership and cannot be
                # revoked away; flagging them would report the definition of
                # ownership as a defect on every table. FORCE RLS is what
                # constrains the owner, and that is asserted separately.
                if grantee == t["owner"]:
                    continue
                bad = sorted({p.rstrip("*") for p in privs} & {"UPDATE", "DELETE", "TRUNCATE"})
                if bad:
                    out.append(
                        {
                            "table": name,
                            "finding": f"append-only ledger grants {', '.join(bad)} to {grantee}",
                        }
                    )
        for grantee, privs in t["grants"].items():
            if grantee == "PUBLIC":
                out.append(
                    {
                        "table": name,
                        "finding": f"privileges granted to PUBLIC: {', '.join(sorted(privs))}",
                    }
                )
    for role in receipt["roles"]:
        if role["rolname"].startswith("akc_") and role["rolbypassrls"]:
            out.append({"table": "-", "finding": f"role {role['rolname']} has BYPASSRLS"})
        if role["rolname"].startswith("akc_") and role["rolsuper"]:
            out.append({"table": "-", "finding": f"role {role['rolname']} is SUPERUSER"})
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=os.environ.get("AKC_RECEIPT_DATABASE_URL", ""))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--check", action="store_true", help="fail on drift from --out")
    args = ap.parse_args()

    if not args.url:
        print("no --url and AKC_RECEIPT_DATABASE_URL is unset", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(args.url.replace("+asyncpg", "").replace("+psycopg", ""))
    try:
        receipt = await collect(conn)
    finally:
        await conn.close()

    receipt["findings"] = findings(receipt)
    body = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False)
    receipt["receipt_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    rendered = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    if args.check:
        if not args.out.exists():
            print(f"{args.out} does not exist; run without --check first", file=sys.stderr)
            return 1
        if args.out.read_text(encoding="utf-8") != rendered:
            print(f"privilege receipt drifted from {args.out}", file=sys.stderr)
            return 1
        print(f"privilege receipt matches {args.out}")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    n = len(receipt["findings"])
    print(f"wrote {args.out}: {receipt['table_count']} tables, {n} finding(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
