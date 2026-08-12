"""Separate the human and worker authorization planes, and bound the control plane.

Everything here is inert while the seven worker roles hold ``BYPASSRLS``. That
is deliberate: arming is removing that attribute role by role, and nothing about
arming belongs in the migration that prepares for it.

**1. A human authorization plane that exists.** ``akc_api_plane`` is the runtime
role the API assumes; ``akc_api_runtime`` is the login principal that assumes
it. Splitting them means the credential that authenticates is not the identity
that authorizes. Both are ``NOINHERIT`` like every other runtime role here, so
the plane is reached by ``SET ROLE`` and ``current_user`` becomes the plane —
which is the only arrangement that works, because ``pg_policy.polroles`` does
not reach a ``NOINHERIT`` member of a group (measured in
``docs/audit/V5_WORKER_AUTHZ_SPIKE.md`` D). Policies target the plane directly
and never a group.

Every membership-referencing policy then moves from ``PUBLIC`` to that plane. A
policy asking "is this person a member" has no answer for a worker, and leaving
it applicable is exactly what makes a worker's query die with *permission denied
for table memberships* the moment ``BYPASSRLS`` goes. Tenant isolation is
untouched — the ``*_tenant_*`` policies still apply to everyone.

**2. Permissive halves for both planes.** A ``RESTRICTIVE`` policy grants
nothing on its own; 37 tables in this catalog carry only restrictive policies
and are default-deny for any role that cannot bypass row-level security (spike
C). Both planes get a tenant-scoped permissive policy wherever nothing else
would admit them, and the migration refuses to finish while any granted
operation has no permissive policy behind it. That check found six gaps on its
first run, two of which — ``akc_dispatch_worker`` on ``collections`` and
``collection_events`` — were latent breaks waiting for arming day.

The human plane is granted only the operations its policies actually admit.
``collection_integrity_decisions`` has no update or delete policy because those
decisions are immutable; the plane therefore gets no update or delete grant
there, rather than a policy invented to justify one.

**3. A control plane with edges.** The scheduler gets a permissive policy on
each of the seven tables it holds a grant on, gated on the transaction
*declaring* which control-plane purpose it serves and on no tenant being bound.
Declaring a purpose is what makes this a boundary rather than a blanket
exemption: a transaction that has bound a tenant cannot reopen the cross-tenant
view, and an undeclared or unapproved purpose returns nothing.
``infra/postgres/control_plane_registry.py`` is the approved list and CI fails
when the catalog disagrees with it.

**4. Claim binding on the four lease-bearing tables.** A worker may touch a row
only while it holds that row's live lease, or while it is discovering work with
no tenant and no claim bound. Reusing another job's lease, acting on an expired
one, or forging a tenant, project or claim identifier all fail closed. The
binding targets worker roles only — a person has no claim, so catching the human
plane in it would take three tables to zero rows for the API.

Every table list is re-derived from the live catalog and asserted against the
count this migration was written for. A previous census of this schema was wrong
by seven tables, and a hardcoded list would have carried that error forward.

Revision ID: 0034_dual_plane_authorization
Revises: 0033_backfill_checkpoint_tenant_rls
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0034_dual_plane_authorization"
down_revision = "0033_backfill_checkpoint_tenant_rls"
branch_labels = None
depends_on = None

HUMAN_PLANE_ROLE = "akc_api_plane"
HUMAN_PLANE_LOGIN_ROLE = "akc_api_runtime"
CONTROL_PLANE_ROLE = "akc_scheduler"

# The purposes a transaction may declare. Kept in step with
# akc_security.tenant_context.CONTROL_PLANE_PURPOSES and
# infra/postgres/control_plane_registry.py by
# tests/security/test_control_plane_boundary.py.
CONTROL_PLANE_PURPOSES = ("claim", "job_discovery", "lease", "retention", "scheduling")

# Counts this migration was written against, at 0033. Asserted, not trusted.
EXPECTED_MEMBERSHIP_POLICIES = 247
EXPECTED_HUMAN_PLANE_TABLES = 63
EXPECTED_CONTROL_PLANE_TABLES = 7
EXPECTED_LEASE_TABLES = 4

# Claim binding is a worker-plane control. The human plane holds grants on three
# of the four lease-bearing tables and must not be caught by it. Derived per
# table from the ACLs, then checked against this list so an unrecognised role
# fails the migration instead of silently acquiring a policy.
WORKER_PLANE_ROLES = (
    "akc_analysis_worker",
    "akc_deletion_worker",
    "akc_dispatch_worker",
    "akc_gpu_worker",
    "akc_payment_worker",
    "akc_scheduler",
    "akc_url_fetcher",
)

# Support tables the human plane must read for the membership subqueries in the
# retargeted policies to plan at all. Narrow on purpose: `users` is global and
# carries no row-level security, so it is not admitted here.
HUMAN_PLANE_SUPPORT_TABLES = ("memberships", "tenants")

_OPERATIONS = "(VALUES ('SELECT', 'r'), ('INSERT', 'a'), ('UPDATE', 'w'), ('DELETE', 'd'))"

_MEMBERSHIP_POLICIES = """
SELECT c.relname, p.polname
FROM pg_policy p
JOIN pg_class c ON c.oid = p.polrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND (
    coalesce(pg_get_expr(p.polqual, p.polrelid), '') LIKE '%memberships%'
    OR coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '') LIKE '%memberships%'
  )
ORDER BY 1, 2
"""

_DEFAULT_DENY_TABLES = """
SELECT c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND c.relrowsecurity
  AND NOT EXISTS (
    SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid AND p.polpermissive
  )
ORDER BY 1
"""

# Operations a permissive policy would admit for one role, per table. Used to
# size the human plane's grants: a grant with no policy behind it is not access,
# it is a promise the catalog cannot keep.
_ADMITTED_OPERATIONS = f"""
SELECT c.relname, w.privilege
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN {_OPERATIONS} AS w(privilege, polcmd)
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND (
    NOT c.relrowsecurity
    OR EXISTS (
      SELECT 1 FROM pg_policy p
      WHERE p.polrelid = c.oid
        AND p.polpermissive
        AND p.polcmd IN ('*', w.polcmd)
        AND (
          p.polroles = '{{0}}'::oid[]
          OR (SELECT oid FROM pg_roles WHERE rolname = :role) = ANY (p.polroles)
        )
    )
  )
ORDER BY 1, 2
"""

# Every granted (role, table, operation) that no permissive policy would admit.
# RESTRICTIVE policies only subtract, so such a pair is silently default-deny.
_PERMISSIVE_COVERAGE_GAPS = f"""
SELECT pg_get_userbyid(acl.grantee) AS grantee, c.relname, acl.privilege_type
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) AS acl
JOIN {_OPERATIONS} AS w(privilege, polcmd) ON w.privilege = acl.privilege_type
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND c.relrowsecurity
  AND pg_get_userbyid(acl.grantee) LIKE 'akc\\_%' ESCAPE '\\'
  AND NOT EXISTS (
    SELECT 1 FROM pg_policy p
    WHERE p.polrelid = c.oid
      AND p.polpermissive
      AND p.polcmd IN ('*', w.polcmd)
      AND (p.polroles = '{{0}}'::oid[] OR acl.grantee = ANY (p.polroles))
  )
ORDER BY 1, 2, 3
"""

_CONTROL_PLANE_GRANTS = """
SELECT c.relname, a.privilege_type
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) AS a
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND pg_get_userbyid(a.grantee) = :role
UNION
SELECT c.relname, a.privilege_type
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute att ON att.attrelid = c.oid
CROSS JOIN LATERAL aclexplode(att.attacl) AS a
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND pg_get_userbyid(a.grantee) = :role
ORDER BY 1, 2
"""

_LEASE_TABLES = """
SELECT c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND EXISTS (
    SELECT 1 FROM pg_attribute a
    WHERE a.attrelid = c.oid AND a.attnum > 0 AND a.attname = 'lease_token'
  )
  AND EXISTS (
    SELECT 1 FROM pg_attribute a
    WHERE a.attrelid = c.oid AND a.attnum > 0 AND a.attname = 'lease_expires_at'
  )
ORDER BY 1
"""

_TABLE_COLUMNS = """
SELECT c.relname, a.attname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid
WHERE n.nspname = 'public'
  AND c.relkind IN ('r', 'p')
  AND a.attnum > 0
  AND NOT a.attisdropped
  AND a.attname = ANY (ARRAY['tenant_id', 'project_id'])
"""

# Policies this migration created, found by name so the downgrade does not have
# to re-derive the conditions that produced them — by then the catalog no longer
# satisfies those conditions, because these policies are what changed it.
_CREATED_POLICIES = r"""
SELECT c.relname, p.polname
FROM pg_policy p
JOIN pg_class c ON c.oid = p.polrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND (
    p.polname LIKE '%\_human\_plane' ESCAPE '\'
    OR p.polname LIKE '%\_worker\_plane' ESCAPE '\'
    OR p.polname LIKE '%\_control\_plane\_%' ESCAPE '\'
    OR p.polname LIKE '%\_claim\_binding' ESCAPE '\'
  )
ORDER BY 1, 2
"""

_WORKER_GRANTS_ON = """
SELECT DISTINCT pg_get_userbyid(a.grantee) AS grantee
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) AS a
WHERE n.nspname = 'public' AND c.relname = :table
  AND pg_get_userbyid(a.grantee) LIKE 'akc\\_%' ESCAPE '\\'
ORDER BY 1
"""


def _setting(name: str) -> str:
    return f"NULLIF(current_setting('{name}', true), '')"


def _tenant_match(table: str) -> str:
    return f'"{table}".tenant_id = {_setting("app.tenant_id")}::uuid'


def _control_plane_predicate() -> str:
    purposes = ", ".join(f"'{purpose}'" for purpose in CONTROL_PLANE_PURPOSES)
    return (
        f"({_setting('app.control_plane')} = ANY (ARRAY[{purposes}]) "
        f"AND {_setting('app.tenant_id')} IS NULL)"
    )


def _claim_predicate(table: str, *, has_project: bool) -> str:
    project = ""
    if has_project:
        project = (
            f' AND "{table}".project_id IS NOT DISTINCT FROM '
            f'{_setting("app.project_id")}::uuid'
        )
    return (
        "("
        f"({_setting('app.claim_id')} IS NULL "
        f"AND {_setting('app.tenant_id')} IS NULL)"
        " OR ("
        f"{_tenant_match(table)}"
        f' AND "{table}".id = {_setting("app.claim_id")}::uuid'
        f' AND "{table}".lease_token = {_setting("app.lease_token")}::uuid'
        f' AND "{table}".lease_expires_at > now()'
        f"{project}"
        "))"
    )


def _rows(statement: str, **parameters: object) -> list[tuple[str, ...]]:
    result = op.get_bind().execute(text(statement), parameters)
    return [tuple(str(value) for value in row) for row in result]


def _names(statement: str, **parameters: object) -> list[str]:
    return [row[0] for row in _rows(statement, **parameters)]


def _create_roles() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{HUMAN_PLANE_ROLE}'
            ) THEN
                CREATE ROLE {HUMAN_PLANE_ROLE}
                    NOLOGIN NOINHERIT NOBYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{HUMAN_PLANE_LOGIN_ROLE}'
            ) THEN
                -- NOLOGIN and no password: a migration must not mint a
                -- credential, and nothing connects as this role yet. Granting
                -- LOGIN with a real secret is a deploy step, recorded in
                -- docs/audit/V5_WORKER_AUTHZ_ARMING.md. The shadow harness sets
                -- a throwaway password for the length of one run and removes it,
                -- which is how the login-then-SET-ROLE chain gets proven without
                -- leaving a credential behind.
                CREATE ROLE {HUMAN_PLANE_LOGIN_ROLE}
                    NOLOGIN NOINHERIT NOBYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT {HUMAN_PLANE_ROLE} TO {HUMAN_PLANE_LOGIN_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {HUMAN_PLANE_ROLE}")


def _membership_policies() -> list[tuple[str, ...]]:
    policies = _rows(_MEMBERSHIP_POLICIES)
    if len(policies) != EXPECTED_MEMBERSHIP_POLICIES:
        raise RuntimeError(
            f"membership-referencing policies are {len(policies)}, "
            f"expected {EXPECTED_MEMBERSHIP_POLICIES}"
        )
    return policies


def _human_plane_surface(policies: list[tuple[str, ...]]) -> list[str]:
    tables = sorted({table for table, _ in policies})
    if len(tables) != EXPECTED_HUMAN_PLANE_TABLES:
        raise RuntimeError(
            f"human plane surface is {len(tables)} tables, "
            f"expected {EXPECTED_HUMAN_PLANE_TABLES}"
        )
    return tables


def _retarget_membership_policies(
    policies: list[tuple[str, ...]], *, target: str
) -> None:
    """Point every membership check at the plane that has memberships.

    A policy that does not apply to the current role is not planned, so the
    tables its expression references are not ACL-checked either — measured in
    ``docs/audit/V5_WORKER_AUTHZ_SPIKE.md`` (B). That is what lets a worker run
    without a grant on ``memberships``, and it is the whole mechanism behind the
    plane separation.
    """

    for table, policy in policies:
        op.execute(f'ALTER POLICY "{policy}" ON "{table}" TO {target}')


def _permissive_backfill(tables: list[str], *, roles: list[str], suffix: str) -> None:
    """Give a plane the permissive half it needs on default-deny tables.

    Tenant-scoped, matching the ``*_tenant_isolation`` shape used everywhere
    else. Not ``USING (true)``: a blanket exemption would make the restrictive
    policies beside it decorative.
    """

    columns = {(row[0], row[1]) for row in _rows(_TABLE_COLUMNS)}
    for table in tables:
        if (table, "tenant_id") not in columns:
            raise RuntimeError(f"{table} is default-deny and carries no tenant_id")
        match = _tenant_match(table)
        op.execute(
            f'CREATE POLICY "{table}_{suffix}" ON "{table}" '
            f"AS PERMISSIVE FOR ALL TO {', '.join(roles)} "
            f"USING ({match}) WITH CHECK ({match})"
        )


def _grant_human_plane(tables: list[str]) -> None:
    """Grant the plane exactly the operations its policies admit.

    ``collection_integrity_decisions`` carries no update or delete policy
    because those decisions are immutable evidence. The plane gets no update or
    delete grant there — the alternative would have been inventing a policy to
    justify a grant, which is backwards.
    """

    admitted: dict[str, set[str]] = {}
    for table, privilege in _rows(_ADMITTED_OPERATIONS, role=HUMAN_PLANE_ROLE):
        admitted.setdefault(table, set()).add(privilege)
    for table in [*tables, *HUMAN_PLANE_SUPPORT_TABLES]:
        wanted = {"SELECT"} if table in HUMAN_PLANE_SUPPORT_TABLES else None
        operations = admitted.get(table, set())
        if wanted is not None:
            operations &= wanted
        if not operations:
            raise RuntimeError(f"{table} admits the human plane for no operation")
        op.execute(
            f'GRANT {", ".join(sorted(operations))} ON TABLE "{table}" '
            f"TO {HUMAN_PLANE_ROLE}"
        )


def _control_plane_operations() -> dict[str, set[str]]:
    operations: dict[str, set[str]] = {}
    for table, privilege in _rows(_CONTROL_PLANE_GRANTS, role=CONTROL_PLANE_ROLE):
        if privilege in {"SELECT", "INSERT", "UPDATE", "DELETE"}:
            operations.setdefault(table, set()).add(privilege)
    if len(operations) != EXPECTED_CONTROL_PLANE_TABLES:
        raise RuntimeError(
            f"control plane surface is {len(operations)} tables, "
            f"expected {EXPECTED_CONTROL_PLANE_TABLES}: {sorted(operations)}"
        )
    return operations


def _create_control_plane_policies(operations: dict[str, set[str]]) -> None:
    predicate = _control_plane_predicate()
    for table in sorted(operations):
        for privilege in sorted(operations[table]):
            clause = (
                f"WITH CHECK ({predicate})"
                if privilege == "INSERT"
                else f"USING ({predicate})"
                if privilege in {"SELECT", "DELETE"}
                else f"USING ({predicate}) WITH CHECK ({predicate})"
            )
            op.execute(
                f'CREATE POLICY "{table}_control_plane_{privilege.lower()}" '
                f'ON "{table}" '
                f"AS PERMISSIVE FOR {privilege} TO {CONTROL_PLANE_ROLE} {clause}"
            )


def _lease_tables() -> list[str]:
    tables = _names(_LEASE_TABLES)
    if len(tables) != EXPECTED_LEASE_TABLES:
        raise RuntimeError(
            f"lease-bearing tables are {len(tables)}, "
            f"expected {EXPECTED_LEASE_TABLES}: {tables}"
        )
    return tables


def _worker_roles_on(table: str) -> list[str]:
    granted = _names(_WORKER_GRANTS_ON, table=table)
    unknown = sorted(set(granted) - set(WORKER_PLANE_ROLES) - {HUMAN_PLANE_ROLE})
    if unknown:
        raise RuntimeError(f"{table} is granted to unrecognised roles: {unknown}")
    return [role for role in granted if role in WORKER_PLANE_ROLES]


def _create_claim_policies(tables: list[str]) -> None:
    columns = {(row[0], row[1]) for row in _rows(_TABLE_COLUMNS)}
    for table in tables:
        roles = _worker_roles_on(table)
        if not roles:
            raise RuntimeError(f"{table} carries a lease but no worker may reach it")
        predicate = _claim_predicate(table, has_project=(table, "project_id") in columns)
        op.execute(
            f'CREATE POLICY "{table}_claim_binding" ON "{table}" '
            f"AS RESTRICTIVE FOR ALL TO {', '.join(roles)} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def _assert_permissive_coverage() -> None:
    gaps = _rows(_PERMISSIVE_COVERAGE_GAPS)
    if gaps:
        listed = ", ".join(f"{role} {table}.{privilege}" for role, table, privilege in gaps)
        raise RuntimeError(f"grants with no permissive policy to admit them: {listed}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _create_roles()
    policies = _membership_policies()
    human_plane = _human_plane_surface(policies)
    _retarget_membership_policies(policies, target=HUMAN_PLANE_ROLE)

    default_deny = set(_names(_DEFAULT_DENY_TABLES))
    _permissive_backfill(
        sorted(default_deny & set(human_plane)),
        roles=[HUMAN_PLANE_ROLE],
        suffix="human_plane",
    )
    # The worker plane needs the same treatment, and needs it more: these are
    # tables a worker already holds a grant on and would see nothing in.
    for table in sorted(default_deny):
        workers = _worker_roles_on(table)
        if workers:
            _permissive_backfill([table], roles=workers, suffix="worker_plane")

    _grant_human_plane(human_plane)
    _create_control_plane_policies(_control_plane_operations())
    _create_claim_policies(_lease_tables())
    _assert_permissive_coverage()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, policy in _rows(_CREATED_POLICIES):
        op.execute(f'DROP POLICY IF EXISTS "{policy}" ON "{table}"')
    _retarget_membership_policies(_rows(_MEMBERSHIP_POLICIES), target="PUBLIC")
    # DROP OWNED BY removes the grants; the policies above had to go first
    # because a policy naming a role holds a dependency on it.
    for role in (HUMAN_PLANE_LOGIN_ROLE, HUMAN_PLANE_ROLE):
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    EXECUTE 'DROP OWNED BY {role}';
                    EXECUTE 'DROP ROLE {role}';
                END IF;
            END
            $$
            """
        )
