"""Give each polled queue a claim broker, so workers stop needing to read it.

Founder decision F-1 (2026-08-11), Option B. The problem it solves was measured
before it was designed: with ``BYPASSRLS`` removed, ``akc_url_fetcher`` reads
**zero rows** from ``url_fetch_tasks`` whether it declares a control-plane
purpose or not, because the only permissive policy there requires a tenant and a
queue poll has none. The rejected fix was to give each worker a purpose-gated
cross-tenant ``SELECT`` on its own queue. That works, and it means a compromised
worker can read every tenant's URLs, parameters and manifests by declaring a
purpose it was going to declare anyway.

**What lands instead.** One ``SECURITY DEFINER`` function per polled queue,
owned by ``akc_claim_broker``, which claims a row and returns exactly five
identifiers — claim id, tenant, project, lease token, lease expiry. The worker
holds ``EXECUTE`` and **no cross-tenant read at all**. It then binds the claim
and re-reads the row under ordinary tenant scope, where the ``0034`` claim
binding already constrains it to that one row.

The cross-tenant capability does not disappear; it moves into one non-login role
that can only be reached through a function whose return surface is five UUIDs
and a timestamp. That is the entire trade, and it is smaller than the one the
alternative asked for.

**Why the function is safe to own the capability.**

* ``akc_claim_broker`` is ``NOBYPASSRLS``. It reaches the queues through
  permissive policies created here, gated on the same declared purpose the
  control plane uses and on no tenant being bound. A definer function owned by a
  bypassing role would be a blanket exemption wearing a function's clothes.
* ``search_path`` is pinned to ``pg_catalog, public`` and every call inside the
  body is schema-qualified, so a caller cannot shadow a function name.
* ``LANGUAGE sql`` with no dynamic SQL and no ``EXECUTE``. The only argument is
  an integer, and it is clamped. There is no string to inject into.
* ``EXECUTE`` is revoked from ``PUBLIC`` — which PostgreSQL grants by default,
  and which would otherwise hand the capability to every role in the cluster —
  and granted to exactly one worker role per queue.
* The claim is one statement: ``UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP
  LOCKED LIMIT 1) RETURNING``. There is no window between choosing a row and
  stamping its lease, and the token returned is the token just written to the row
  returned, by construction rather than by a second read.
* Every grant writes an ``audit_events`` row naming the queue, the row, the
  declared purpose and the session principal, in the same statement, so a claim
  that happened and a claim that was audited cannot diverge.

Inert. No role's ``BYPASSRLS`` changes here, and while it holds, nothing calls
these functions — the workers' existing claim paths still run and
``AKC_CLAIM_BROKER_ENABLED`` defaults to false.

Revision ID: 0035_claim_broker
Revises: 0034_dual_plane_authorization
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0035_claim_broker"
down_revision = "0034_dual_plane_authorization"
branch_labels = None
depends_on = None

BROKER_ROLE = "akc_claim_broker"
AUDIT_TABLE = "audit_events"

CONTROL_PLANE_PURPOSES = ("claim", "job_discovery", "lease", "retention", "scheduling")

# queue -> (function, the one role that may execute it, claimable predicate).
#
# The predicates reproduce the ORM claim statements they replace, and the two are
# asserted equal by services/url-fetcher and scheduler tests rather than trusted
# to stay in step by reading.
#   url_fetch_tasks           services/url-fetcher/.../worker.py url_fetch_claim_statement
#   gpu_provider_invocations  services/scheduler/.../gpu_jobs.py GpuJobRuntime._claim
BROKERS: dict[str, tuple[str, str, str]] = {
    "url_fetch_tasks": (
        "akc_claim_url_fetch_task",
        "akc_url_fetcher",
        "candidate.status IN ('queued', 'retry', 'running') "
        "AND candidate.available_at <= pg_catalog.now() "
        "AND (candidate.status IN ('queued', 'retry') "
        "OR candidate.lease_expires_at IS NULL "
        "OR candidate.lease_expires_at <= pg_catalog.now())",
    ),
    "gpu_provider_invocations": (
        "akc_claim_gpu_invocation",
        "akc_gpu_worker",
        "candidate.status IN ('queued', 'submitting', 'submitted', 'running', "
        "'retry', 'cancel_requested', 'cancelling') "
        "AND candidate.available_at <= pg_catalog.now() "
        "AND (candidate.lease_expires_at IS NULL "
        "OR candidate.lease_expires_at <= pg_catalog.now())",
    ),
}

# Lease-bearing tables with no broker, and why. Asserted against the catalog so
# the two sets together are the whole lease surface.
LEASE_TABLES_WITHOUT_BROKER = ("analysis_tasks", "deletion_requests")

# The lease a broker may stamp, in seconds. A caller passing something absurd
# would otherwise park a row for as long as it liked, which is a denial of
# service on that job rather than a security failure — but it is free to prevent.
MIN_LEASE_SECONDS = 1
MAX_LEASE_SECONDS = 3600

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

_ROLE_HOLDS_SELECT = """
SELECT count(*)
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) AS a
WHERE n.nspname = 'public' AND c.relname = :table
  AND pg_get_userbyid(a.grantee) = :role
  AND a.privilege_type = 'SELECT'
"""

_QUEUE_HAS_PROJECT = """
SELECT count(*)
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relname = :table
  AND a.attnum > 0 AND NOT a.attisdropped AND a.attname = 'project_id'
"""


def _setting(name: str) -> str:
    return f"NULLIF(current_setting('{name}', true), '')"


def _control_plane_predicate() -> str:
    purposes = ", ".join(f"'{purpose}'" for purpose in CONTROL_PLANE_PURPOSES)
    return (
        f"({_setting('app.control_plane')} = ANY (ARRAY[{purposes}]) "
        f"AND {_setting('app.tenant_id')} IS NULL)"
    )


def _rows(statement: str, **parameters: object) -> list[tuple[str, ...]]:
    result = op.get_bind().execute(text(statement), parameters)
    return [tuple(str(value) for value in row) for row in result]


def _scalar(statement: str, **parameters: object) -> int:
    return int(op.get_bind().execute(text(statement), parameters).scalar_one())


def _assert_surface() -> None:
    """The broker set and the no-broker set are the whole lease surface."""

    lease_tables = {row[0] for row in _rows(_LEASE_TABLES)}
    covered = set(BROKERS) | set(LEASE_TABLES_WITHOUT_BROKER)
    if lease_tables != covered:
        raise RuntimeError(
            f"lease-bearing tables {sorted(lease_tables)} are not the set this "
            f"migration decides for: {sorted(covered)}"
        )
    for queue, (_function, role, _predicate) in BROKERS.items():
        if _scalar(_ROLE_HOLDS_SELECT, table=queue, role=role) < 1:
            raise RuntimeError(f"{role} holds no SELECT on {queue}; the mapping is wrong")
        if _scalar(_QUEUE_HAS_PROJECT, table=queue) != 1:
            raise RuntimeError(f"{queue} has no project_id; the broker contract needs one")


def _create_role() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{BROKER_ROLE}') THEN
                CREATE ROLE {BROKER_ROLE}
                    NOLOGIN NOINHERIT NOBYPASSRLS
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {BROKER_ROLE}")
    op.execute(f'GRANT INSERT ON TABLE "{AUDIT_TABLE}" TO {BROKER_ROLE}')
    predicate = _control_plane_predicate()
    op.execute(
        f'CREATE POLICY "{AUDIT_TABLE}_claim_broker_insert" ON "{AUDIT_TABLE}" '
        f"AS PERMISSIVE FOR INSERT TO {BROKER_ROLE} WITH CHECK ({predicate})"
    )
    for queue in sorted(BROKERS):
        op.execute(
            f'GRANT SELECT ON TABLE "{queue}" TO {BROKER_ROLE}'
        )
        op.execute(
            f'GRANT UPDATE (lease_token, lease_expires_at) ON TABLE "{queue}" '
            f"TO {BROKER_ROLE}"
        )
        op.execute(
            f'CREATE POLICY "{queue}_claim_broker_select" ON "{queue}" '
            f"AS PERMISSIVE FOR SELECT TO {BROKER_ROLE} USING ({predicate})"
        )
        op.execute(
            f'CREATE POLICY "{queue}_claim_broker_update" ON "{queue}" '
            f"AS PERMISSIVE FOR UPDATE TO {BROKER_ROLE} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )


def _create_broker(queue: str, function: str, role: str, claimable: str) -> None:
    # LEAST/GREATEST are grammar, not catalog functions, so they cannot be
    # schema-qualified — and for the same reason cannot be shadowed by a caller.
    lease = (
        f"LEAST(GREATEST(claim_lease_seconds, {MIN_LEASE_SECONDS}), {MAX_LEASE_SECONDS})"
    )
    op.execute(
        f"""
        CREATE FUNCTION public.{function}(claim_lease_seconds integer)
        RETURNS TABLE (
            claim_id uuid,
            tenant_id uuid,
            project_id uuid,
            lease_token uuid,
            lease_expires_at timestamptz
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
            WITH granted AS (
                UPDATE public."{queue}" AS queue
                SET lease_token = pg_catalog.gen_random_uuid(),
                    lease_expires_at = pg_catalog.now()
                        + pg_catalog.make_interval(secs => {lease})
                WHERE queue.id = (
                    SELECT candidate.id
                    FROM public."{queue}" AS candidate
                    WHERE {_control_plane_predicate()}
                      AND {claimable}
                    ORDER BY candidate.available_at,
                             candidate.created_at,
                             candidate.id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING queue.id AS claim_id,
                          queue.tenant_id AS tenant_id,
                          queue.project_id AS project_id,
                          queue.lease_token AS lease_token,
                          queue.lease_expires_at AS lease_expires_at
            ), audited AS (
                INSERT INTO public."{AUDIT_TABLE}" (
                    id, tenant_id, actor_id, action, target_type, target_id,
                    metadata, occurred_at
                )
                SELECT pg_catalog.gen_random_uuid(),
                       granted.tenant_id,
                       NULL,
                       'worker.claim.granted',
                       '{queue}',
                       granted.claim_id::text,
                       pg_catalog.json_build_object(
                           'purpose', current_setting('app.control_plane', true),
                           'principal', session_user,
                           'lease_expires_at', granted.lease_expires_at
                       ),
                       pg_catalog.now()
                FROM granted
                RETURNING 1
            )
            SELECT granted.claim_id,
                   granted.tenant_id,
                   granted.project_id,
                   granted.lease_token,
                   granted.lease_expires_at
            FROM granted
        $function$
        """
    )
    op.execute(f"ALTER FUNCTION public.{function}(integer) OWNER TO {BROKER_ROLE}")
    # PostgreSQL grants EXECUTE to PUBLIC by default. Left alone, every role in
    # the cluster would hold the cross-tenant claim capability.
    op.execute(f"REVOKE ALL ON FUNCTION public.{function}(integer) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.{function}(integer) TO {role}")


def _create_depth_probe(queue: str, function: str, role: str, claimable: str) -> None:
    """Claimable depth, for the starvation detector. A count and nothing else.

    Zero rows from a claim means either an idle queue or a worker that cannot
    see the work — the arming failure mode that raises nothing. Telling them
    apart needs a backlog number from something that is not the worker's own
    read path, and a count leaks no row.
    """

    op.execute(
        f"""
        CREATE FUNCTION public.{function}()
        RETURNS bigint
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        SET search_path = pg_catalog, public
        AS $function$
            SELECT pg_catalog.count(*)
            FROM public."{queue}" AS candidate
            WHERE {_control_plane_predicate()}
              AND {claimable}
        $function$
        """
    )
    op.execute(f"ALTER FUNCTION public.{function}() OWNER TO {BROKER_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION public.{function}() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.{function}() TO {role}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _assert_surface()
    _create_role()
    for queue in sorted(BROKERS):
        function, role, claimable = BROKERS[queue]
        _create_broker(queue, function, role, claimable)
        _create_depth_probe(queue, f"{function}_depth", role, claimable)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for queue in sorted(BROKERS):
        function, _role, _claimable = BROKERS[queue]
        op.execute(f"DROP FUNCTION IF EXISTS public.{function}(integer)")
        op.execute(f"DROP FUNCTION IF EXISTS public.{function}_depth()")
        op.execute(f'DROP POLICY IF EXISTS "{queue}_claim_broker_select" ON "{queue}"')
        op.execute(f'DROP POLICY IF EXISTS "{queue}_claim_broker_update" ON "{queue}"')
    op.execute(
        f'DROP POLICY IF EXISTS "{AUDIT_TABLE}_claim_broker_insert" ON "{AUDIT_TABLE}"'
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{BROKER_ROLE}') THEN
                EXECUTE 'DROP OWNED BY {BROKER_ROLE}';
                EXECUTE 'DROP ROLE {BROKER_ROLE}';
            END IF;
        END
        $$
        """
    )
