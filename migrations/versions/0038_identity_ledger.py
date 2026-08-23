"""Persist identity transitions in an append-only server-side ledger.

§15.5 records every identity transition -- MATCH/NEW/MERGE/SPLIT/RETIRE -- in
an append-only ledger so temporal queries and audits can answer *what became
of this identity* years later, not just what the corpus looks like now.
``akc_cir.identity_ledger.IdentityLedger`` keeps the per-run JSONL form,
tamper-evident through a digest chain. This table is where those entries land
when the run is server-side: one row per entry, shaped for the same guarantees
rather than for convenience.

The columns lift exactly what the ledger's readers filter and join on;
everything else about an entry travels inside ``payload`` as the canonical
field dict (seq, ts_utc, prior_ids, evidence_refs, note) verbatim, so the row
and the JSONL line reconstruct each other without a translation layer:

* ``logical_id`` -- the transition's subject, the equality everything above
  the ledger keys on.
* ``kind`` -- the five §15.5 transitions, constrained at the database so no
  writer can invent a sixth.
* ``payload`` -- the rest of the entry, JSONB, read back into a
  ``LedgerEntry`` unchanged.

Append-only is enforced the way ``collection_integrity_decisions`` is: FORCE
row-level security, tenant-scoped SELECT and INSERT policies, and *no* UPDATE
or DELETE policy at all, so mutation fails closed for any role that cannot
bypass RLS. The Python store never issues an update either; a corrected entry
is a new entry, which is the entire point of a ledger.

Revision ID: 0038_identity_ledger
Revises: 0037_gpu_post_claim_authorization
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB

revision = "0038_identity_ledger"
down_revision = "0037_gpu_post_claim_authorization"
branch_labels = None
depends_on = None

_TABLE = "identity_ledger"

#: The §15.5 transitions, mirrored from akc_cir.identity_ledger.LedgerKind.
_KINDS = ("MATCH", "NEW", "MERGE", "SPLIT", "RETIRE")

# The runtime role the API assumes (created by 0034_dual_plane_authorization).
# Granted only what the policies admit: reads and inserts, never mutation.
_API_PLANE_ROLE = "akc_api_plane"


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _create_table() -> None:
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        # bigserial rather than a uuid: the ledger's order is its meaning, and
        # the sequence is the server-side twin of the entry seq in payload.
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("logical_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(f"'{kind}'" for kind in _KINDS) + ")",
            name="ck_identity_ledger_kind",
        ),
        sa.CheckConstraint(
            "length(logical_id) > 0",
            name="ck_identity_ledger_logical_id",
        ),
    )
    # Replay for one identity, newest last; and time-windowed replays.
    op.create_index(
        "identity_ledger_tenant_logical_idx",
        _TABLE,
        ["tenant_id", "logical_id", "created_at"],
    )
    op.create_index(
        "identity_ledger_tenant_created_idx",
        _TABLE,
        ["tenant_id", "created_at"],
    )


def _tenant_setting() -> str:
    return "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _enable_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f'ALTER TABLE "{_TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_TABLE}" FORCE ROW LEVEL SECURITY')
    tenant_scope = f'"{_TABLE}".tenant_id = {_tenant_setting()}'
    for operation in ("select", "insert"):
        op.execute(f'DROP POLICY IF EXISTS "{_TABLE}_{operation}" ON "{_TABLE}"')
    op.execute(
        f'CREATE POLICY "{_TABLE}_select" ON "{_TABLE}" '
        f"FOR SELECT USING ({tenant_scope})"
    )
    op.execute(
        f'CREATE POLICY "{_TABLE}_insert" ON "{_TABLE}" '
        f"FOR INSERT WITH CHECK ({tenant_scope})"
    )
    # Append-only by deliberate absence: no UPDATE and no DELETE policy, so
    # mutation fails closed for any role that cannot bypass row-level security.


def _grant_api_plane() -> None:
    """Grant the human plane reads and inserts, nothing else."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "DO $$ BEGIN\n"  # noqa: S608 - fixed migration-owned identifiers, no external input.
        "IF EXISTS (\n"
        f"    SELECT 1 FROM pg_roles WHERE rolname = '{_API_PLANE_ROLE}'\n"
        ") THEN\n"
        'EXECUTE \'GRANT SELECT, INSERT ON TABLE "{_TABLE}" TO\'\n'
        f"       '{_API_PLANE_ROLE}';\n"
        "END IF;\n"
        "END $$;"
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _create_table()
    _enable_rls()
    _grant_api_plane()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    if _TABLE in _tables():
        op.drop_table(_TABLE)
