"""Add the second backlog probe, so starvation can be told from a blocked queue.

``0035`` gave each brokered queue a ``…_depth()`` probe reporting **claimable**
work. One count is not enough. Three situations produce an empty poll and they
are different problems:

* nothing pending — an idle queue, and never an incident;
* pending work, none of it claimable — every row is leased to somebody else, so
  this worker is correctly waiting;
* pending work that *is* claimable, and this worker still gets nothing — row-level
  security is hiding it.

Only the third is starvation, and it is the arming failure mode that raises no
error. Distinguishing it needs **total** backlog beside claimable backlog, which
is what ``…_backlog()`` adds here.

The predicates are the pending half of ``0035``'s claimable predicates — the same
status and availability filters with the lease clause removed. Both counts are
therefore taken over the same population, and ``backlog - claimable`` is exactly
"pending but leased".

Same shape as the brokers and for the same reasons: ``SECURITY DEFINER`` owned by
``akc_claim_broker``, pinned ``search_path``, no dynamic SQL, the same declared
control-plane purpose gate, ``EXECUTE`` revoked from ``PUBLIC`` and granted to one
worker role. A count leaks no row.

Additive and inert: nothing is armed, no role's ``BYPASSRLS`` changes, and the
only caller is the starvation detector, which reports and does not decide.

Revision ID: 0036_claim_backlog_probe
Revises: 0035_claim_broker
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0036_claim_backlog_probe"
down_revision = "0035_claim_broker"
branch_labels = None
depends_on = None

BROKER_ROLE = "akc_claim_broker"
CONTROL_PLANE_PURPOSES = ("claim", "job_discovery", "lease", "retention", "scheduling")

# queue -> (probe function, the one role that may execute it, pending predicate).
#
# "Pending" is the claimable predicate from 0035 with the lease clause dropped:
# work that exists and is due, whether or not somebody currently holds it.
BACKLOG_PROBES: dict[str, tuple[str, str, str]] = {
    "url_fetch_tasks": (
        "akc_claim_url_fetch_task_backlog",
        "akc_url_fetcher",
        "candidate.status IN ('queued', 'retry', 'running') "
        "AND candidate.available_at <= pg_catalog.now()",
    ),
    "gpu_provider_invocations": (
        "akc_claim_gpu_invocation_backlog",
        "akc_gpu_worker",
        "candidate.status IN ('queued', 'submitting', 'submitted', 'running', "
        "'retry', 'cancel_requested', 'cancelling') "
        "AND candidate.available_at <= pg_catalog.now()",
    ),
}

_BROKER_EXISTS = """
SELECT count(*) FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND p.proname = :name
"""


def _setting(name: str) -> str:
    return f"NULLIF(current_setting('{name}', true), '')"


def _control_plane_predicate() -> str:
    purposes = ", ".join(f"'{purpose}'" for purpose in CONTROL_PLANE_PURPOSES)
    return (
        f"({_setting('app.control_plane')} = ANY (ARRAY[{purposes}]) "
        f"AND {_setting('app.tenant_id')} IS NULL)"
    )


def _scalar(statement: str, **parameters: object) -> int:
    return int(op.get_bind().execute(text(statement), parameters).scalar_one())


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for queue, (function, role, pending) in sorted(BACKLOG_PROBES.items()):
        # The claimable probe from 0035 must already exist, or the pair this
        # migration completes is only half present and the detector would compare
        # a backlog against nothing.
        claimable = function.replace("_backlog", "_depth")
        if _scalar(_BROKER_EXISTS, name=claimable) != 1:
            raise RuntimeError(f"{claimable} is missing; 0035 did not run for {queue}")
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
                  AND {pending}
            $function$
            """
        )
        op.execute(f"ALTER FUNCTION public.{function}() OWNER TO {BROKER_ROLE}")
        op.execute(f"REVOKE ALL ON FUNCTION public.{function}() FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{function}() TO {role}")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for _queue, (function, _role, _pending) in sorted(BACKLOG_PROBES.items()):
        op.execute(f"DROP FUNCTION IF EXISTS public.{function}()")
