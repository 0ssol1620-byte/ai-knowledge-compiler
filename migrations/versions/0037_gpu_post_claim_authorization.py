"""Let a claim holder release its lease, and give a provider callback a boundary.

**One deterministic security state, and no role attribute changes here.** The
revision this replaces read ``AKC_CANARY_B_DISARM_GPU`` and removed
``BYPASSRLS`` from ``akc_gpu_worker`` when it was set. That made one revision
describe two different privilege states depending on an environment variable,
and a no-op application does not re-run when the variable later flips. The
canary disarm now lives in ``infra/postgres/canary_b_disarm.py``, which is an
operation somebody performs against one cluster rather than a schema fact.

What lands here is the schema half canary B needs, and it is the same in every
environment: **no worker role's ``BYPASSRLS`` changes, in either direction.**

---

**Why the `0034` claim binding is not sufficient as written.** Measured against a
NOBYPASSRLS ``akc_gpu_worker`` on a throwaway PostgreSQL 17.2 cluster at
``0036_claim_backlog_probe``:

    post-claim read, tenant bound only ....................... 0 rows
    post-claim read, tenant+project+claim+lease bound ........ 1 row
    UPDATE … SET lease_token = NULL, with the claim bound .... ERROR 42501

The first two are why ``_locked_invocation`` now binds the claim; that is code,
and it is in the same change. The third is why this migration exists. Every
post-claim path ends by giving the lease up — submission, poll wait, admission,
failure, cancellation and both terminal branches — and the ``0034`` predicate
requires the row to *still be a live claim after the update*. A worker could
read its claim and never finish it.

**The disjunct that solves it is ``held`` with the expiry cleared instead of
compared**: the same tenant, project, row and lease token, with no expiry at all.
A release therefore gives up an authority instead of acquiring one, and the only
session that can write or read a released row is the one that could already
reach it. The worker keeps writing the row unleased — it just clears
``lease_expires_at`` and leaves the token that proves whose release it was.
Every claim predicate in this schema already treats ``lease_expires_at IS NULL``
as claimable, so nothing about reclaiming changes, and a re-claim overwrites the
token.

Three other shapes were built and measured before this one, and all are worse:

* Admitting ``lease_token IS NULL`` leaves a predicate holding only a tenant and
  an id. A worker then reads **and writes** any unleased row in its tenant whose
  id it knows — demonstrated on a scratch table, where exactly that read
  returned a row it had never claimed.
* Admitting ``lease_expires_at <= now()`` works and is narrow — it only ever
  admits the row whose token you hold — but it makes a *lapsed* lease
  indistinguishable from a released one, and a lapsed lease means this worker was
  superseded. ``shadow_validate_dual_plane``'s ``claim:expired-lease`` case
  asserts that a session presenting its own expired lease sees nothing, and this
  shape turned it red. That gate was not edited.
* Putting the release in ``WITH CHECK`` alone does not work at all. An
  ``UPDATE``'s new row must satisfy the read side of an ``ALL`` policy as well,
  so the write still fails 42501 — with the confusing symptom that the
  ``WITH CHECK`` expression evaluates *true* against the row PostgreSQL just
  rejected. Splitting the policy into ``FOR SELECT`` and ``FOR UPDATE`` fails
  identically.

**The callback is a second authorization plane, not a claim with a hole in it.**
``GpuInvocationWorker.admit_callback`` runs as ``akc_gpu_worker`` on the same
engine as the claim loop — ``create_gpu_engine`` pins the role on the connection
— so canary B applies to it, and its read named no tenant at all. It also has no
lease, and that is not an oversight: the lease is released when the job is handed
to the provider, so every ordinary callback arrives without one. The row this
migration admits it to is therefore bounded by something a callback actually has
— its own row, and evidence that the provider was given that row at all
(``provider_job_id IS NOT NULL``) — and by ``app.claim_id IS NULL``, which keeps
the two planes from ever being satisfied at once.

``akc_resolve_gpu_callback`` is how a tenant-scoped session learns which tenant a
callback's row belongs to, which is the same problem the claim broker solved and
is solved the same way: a ``SECURITY DEFINER`` function owned by
``akc_claim_broker``, gated on a declared control-plane purpose, with a fixed
return surface. It returns **three** identifiers and no lease, because minting a
lease token for a callback is precisely the forgery the claim binding exists to
detect.

**What this migration does not do.** It grants nothing new to any worker on
``gpu_provider_invocations``. In particular ``akc_gpu_worker`` still holds no
``INSERT`` there, so ``_create_transition`` cannot write its child row — measured
as ``permission denied for table gpu_provider_invocations`` **with ``BYPASSRLS``
on and off alike**, which makes it a pre-existing gap rather than anything canary
B causes. Widening a privilege is a decision; it is recorded in
``docs/audit/V5_GPU_ACCESS_SITE_MATRIX.md`` and not taken here.

Revision ID: 0037_gpu_post_claim_authorization
Revises: 0036_claim_backlog_probe
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0037_gpu_post_claim_authorization"
down_revision = "0036_claim_backlog_probe"
branch_labels = None
depends_on = None

BROKER_ROLE = "akc_claim_broker"
CALLBACK_RESOLVER = "akc_resolve_gpu_callback"
CALLBACK_QUEUE = "gpu_provider_invocations"
CALLBACK_ROLE = "akc_gpu_worker"

CONTROL_PLANE_PURPOSES = ("claim", "job_discovery", "lease", "retention", "scheduling")

# The same four this migration's predecessors decided about. Asserted against the
# catalog rather than trusted, so a fifth lease-bearing table fails the migration
# instead of quietly keeping the older predicate.
EXPECTED_LEASE_TABLES = 4

# Roles the claim binding names. Re-derived per table from the ACLs by `0034`;
# repeated here so a policy this migration rewrites cannot silently acquire or
# lose a role between the two.
WORKER_PLANE_ROLES = (
    "akc_analysis_worker",
    "akc_deletion_worker",
    "akc_dispatch_worker",
    "akc_gpu_worker",
    "akc_payment_worker",
    "akc_scheduler",
    "akc_url_fetcher",
)

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
  AND a.attname = ANY (ARRAY['tenant_id', 'project_id', 'provider_job_id'])
"""

_CLAIM_POLICY_ROLES = r"""
SELECT pg_get_userbyid(r) AS rolname
FROM pg_policy p
JOIN pg_class c ON c.oid = p.polrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL unnest(p.polroles) AS r
WHERE n.nspname = 'public'
  AND c.relname = :table
  AND p.polname = :policy
ORDER BY 1
"""

# The `0034` shape, verbatim, so the downgrade restores what was there rather
# than an approximation of it.
_LEGACY_PREDICATE_TABLES = """
SELECT c.relname
FROM pg_policy p
JOIN pg_class c ON c.oid = p.polrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND p.polname = c.relname || '_claim_binding'
ORDER BY 1
"""


def _setting(name: str) -> str:
    return f"NULLIF(current_setting('{name}', true), '')"


def _control_plane_predicate() -> str:
    purposes = ", ".join(f"'{purpose}'" for purpose in CONTROL_PLANE_PURPOSES)
    return (
        f"({_setting('app.control_plane')} = ANY (ARRAY[{purposes}]) "
        f"AND {_setting('app.tenant_id')} IS NULL)"
    )


def _tenant_match(table: str) -> str:
    return f'"{table}".tenant_id = {_setting("app.tenant_id")}::uuid'


def _project_match(table: str, *, has_project: bool) -> str:
    if not has_project:
        return ""
    return (
        f' AND "{table}".project_id IS NOT DISTINCT FROM '
        f'{_setting("app.project_id")}::uuid'
    )


def _discovery() -> str:
    return (
        f"({_setting('app.claim_id')} IS NULL "
        f"AND {_setting('app.tenant_id')} IS NULL)"
    )


def _held(table: str, *, has_project: bool) -> str:
    return (
        "("
        f"{_tenant_match(table)}"
        f' AND "{table}".id = {_setting("app.claim_id")}::uuid'
        f' AND "{table}".lease_token = {_setting("app.lease_token")}::uuid'
        f' AND "{table}".lease_expires_at > now()'
        f"{_project_match(table, has_project=has_project)}"
        ")"
    )


def _released(table: str, *, has_project: bool) -> str:
    """The one row shape a holder may leave behind: its own claim, given up.

    ``held`` with the expiry cleared instead of compared. The token still has to
    match, so the only session that can produce or read a released row is the one
    that could already reach it — releasing gives up an authority rather than
    acquiring a new one.

    **Two alternatives were built and measured, and both are worse.**

    Admitting ``lease_token IS NULL`` (which is what the code used to write)
    leaves the predicate holding only a tenant and an id, so every unleased row
    in the tenant becomes readable *and writable* to any worker that knows its
    id. On a scratch table with that shape a worker read a row it had never
    claimed; with this shape the same read returns nothing.

    Admitting ``lease_expires_at <= now()`` reads more naturally — a release is
    just an expiry — but it erases the difference between *given up* and *lapsed*,
    and a lapsed lease is the one case the whole binding exists to refuse: a
    worker whose lease expired has been superseded, and letting it keep reading
    its old row is how two writers end up on one job. ``shadow_validate_dual_plane``
    asserts that by name (``claim:expired-lease``) and turned red on that shape.
    ``NULL`` is not a sentinel invented for this predicate — it is what the column
    already means everywhere else in the schema, and every claim predicate here
    already treats ``lease_expires_at IS NULL`` as claimable.
    """

    return (
        "("
        f"{_tenant_match(table)}"
        f' AND "{table}".id = {_setting("app.claim_id")}::uuid'
        f' AND "{table}".lease_token = {_setting("app.lease_token")}::uuid'
        f' AND "{table}".lease_expires_at IS NULL'
        f"{_project_match(table, has_project=has_project)}"
        ")"
    )


def _callback(table: str, *, has_project: bool) -> str:
    return (
        "("
        f"{_setting('app.claim_id')} IS NULL"
        f" AND {_tenant_match(table)}"
        f' AND "{table}".id = {_setting("app.callback_id")}::uuid'
        f' AND "{table}".provider_job_id IS NOT NULL'
        f"{_project_match(table, has_project=has_project)}"
        ")"
    )


def _rows(statement: str, **parameters: object) -> list[tuple[str, ...]]:
    result = op.get_bind().execute(text(statement), parameters)
    return [tuple(str(value) for value in row) for row in result]


def _names(statement: str, **parameters: object) -> list[str]:
    return [row[0] for row in _rows(statement, **parameters)]


def _lease_tables() -> list[str]:
    tables = _names(_LEASE_TABLES)
    if len(tables) != EXPECTED_LEASE_TABLES:
        raise RuntimeError(
            f"lease-bearing tables are {len(tables)}, "
            f"expected {EXPECTED_LEASE_TABLES}: {tables}"
        )
    return tables


def _policy_roles(table: str) -> list[str]:
    """Whom the existing policy names, so the rewrite keeps exactly that set."""

    roles = _names(_CLAIM_POLICY_ROLES, table=table, policy=f"{table}_claim_binding")
    if not roles:
        raise RuntimeError(f"{table} has no claim binding policy to rewrite")
    unknown = sorted(set(roles) - set(WORKER_PLANE_ROLES))
    if unknown:
        raise RuntimeError(f"{table}_claim_binding names unrecognised roles: {unknown}")
    return roles


def _rewrite_claim_policies(*, with_release: bool) -> None:
    """Recreate every claim binding at one predicate shape.

    ``with_release`` is what the upgrade adds and the downgrade removes, so both
    directions run the same generator and there is one description of the policy
    rather than two that have to be kept in step.
    """

    columns = {(row[0], row[1]) for row in _rows(_TABLE_COLUMNS)}
    for table in _lease_tables():
        roles = _policy_roles(table)
        has_project = (table, "project_id") in columns
        has_callback = table == CALLBACK_QUEUE and with_release
        if has_callback and (table, "provider_job_id") not in columns:
            raise RuntimeError(f"{table} has no provider_job_id to bound a callback by")

        parts = [_discovery(), _held(table, has_project=has_project)]
        if with_release:
            # Both clauses, not WITH CHECK alone. An UPDATE's new row has to
            # satisfy the *read* side of an ``ALL`` policy too — measured, after
            # a WITH CHECK-only version failed with 42501 while the expression
            # it named evaluated true against the row it rejected. Splitting the
            # policy into FOR SELECT and FOR UPDATE was measured as well and
            # fails the same way, so this is not a shape that can be avoided.
            parts.append(_released(table, has_project=has_project))
        if has_callback:
            parts.append(_callback(table, has_project=has_project))
        predicate = "(" + " OR ".join(parts) + ")"

        op.execute(f'DROP POLICY "{table}_claim_binding" ON "{table}"')
        op.execute(
            f'CREATE POLICY "{table}_claim_binding" ON "{table}" '
            f"AS RESTRICTIVE FOR ALL TO {', '.join(roles)} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def _create_callback_resolver() -> None:
    op.execute(
        f"""
        CREATE FUNCTION public.{CALLBACK_RESOLVER}(callback_invocation_id uuid)
        RETURNS TABLE (
            callback_id uuid,
            tenant_id uuid,
            project_id uuid
        )
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        SET search_path = pg_catalog, public
        AS $function$
            SELECT invocation.id AS callback_id,
                   invocation.tenant_id AS tenant_id,
                   invocation.project_id AS project_id
            FROM public."{CALLBACK_QUEUE}" AS invocation
            WHERE {_control_plane_predicate()}
              AND invocation.id = callback_invocation_id
              AND invocation.provider_job_id IS NOT NULL
        $function$
        """
    )
    op.execute(
        f"ALTER FUNCTION public.{CALLBACK_RESOLVER}(uuid) OWNER TO {BROKER_ROLE}"
    )
    # PostgreSQL grants EXECUTE to PUBLIC by default; left alone this would hand
    # every role a cross-tenant "whose row is this" oracle.
    op.execute(f"REVOKE ALL ON FUNCTION public.{CALLBACK_RESOLVER}(uuid) FROM PUBLIC")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION public.{CALLBACK_RESOLVER}(uuid) TO {CALLBACK_ROLE}"
    )


def _assert_no_attribute_drift(before: list[tuple[str, ...]]) -> None:
    """This migration changes policies. It must not change who bypasses them."""

    after = _rows(
        r"SELECT rolname, rolbypassrls::text FROM pg_roles "
        r"WHERE rolname LIKE 'akc\_%' ESCAPE '\' ORDER BY 1"
    )
    if before != after:
        raise RuntimeError(f"role attributes changed: {before} -> {after}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    before = _rows(
        r"SELECT rolname, rolbypassrls::text FROM pg_roles "
        r"WHERE rolname LIKE 'akc\_%' ESCAPE '\' ORDER BY 1"
    )
    _rewrite_claim_policies(with_release=True)
    _create_callback_resolver()
    _assert_no_attribute_drift(before)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    before = _rows(
        r"SELECT rolname, rolbypassrls::text FROM pg_roles "
        r"WHERE rolname LIKE 'akc\_%' ESCAPE '\' ORDER BY 1"
    )
    op.execute(f"DROP FUNCTION IF EXISTS public.{CALLBACK_RESOLVER}(uuid)")
    _rewrite_claim_policies(with_release=False)
    _assert_no_attribute_drift(before)
