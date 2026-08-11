"""Give the collection metadata backfill checkpoints tenant-scoped RLS.

``collection_metadata_backfill_checkpoints`` was created by
``0026_collection_metadata_encryption_bridge`` with a ``tenant_id`` column but
without row-level security. Its ACL is empty, so no runtime role reaches it
today and this is defence in depth rather than a live exposure — but it is the
one table in the catalog that acquired a tenant dimension without acquiring the
protection that travels with it.

The policy shape is copied from the surrounding tenant-scoped tables:
RESTRICTIVE, TO PUBLIC, comparing ``tenant_id`` to ``app.tenant_id``. It adds no
new policy vocabulary, and RESTRICTIVE means no later permissive policy can
widen it.

Revision ID: 0033_backfill_checkpoint_tenant_rls
Revises: 0032_accepted_block_invalidations
"""

from __future__ import annotations

from alembic import op

revision = "0033_backfill_checkpoint_tenant_rls"
down_revision = "0032_accepted_block_invalidations"
branch_labels = None
depends_on = None

_TABLE = "collection_metadata_backfill_checkpoints"
_OPERATIONS = ("select", "insert", "update", "delete")


def _tenant_setting() -> str:
    return "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f'ALTER TABLE "{_TABLE}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_TABLE}" FORCE ROW LEVEL SECURITY')
    tenant = f'"{_TABLE}".tenant_id = {_tenant_setting()}'
    for operation in _OPERATIONS:
        op.execute(f'DROP POLICY IF EXISTS "{_TABLE}_tenant_{operation}" ON "{_TABLE}"')
    op.execute(
        f'CREATE POLICY "{_TABLE}_tenant_select" ON "{_TABLE}" '
        f"AS RESTRICTIVE FOR SELECT USING ({tenant})"
    )
    op.execute(
        f'CREATE POLICY "{_TABLE}_tenant_insert" ON "{_TABLE}" '
        f"AS RESTRICTIVE FOR INSERT WITH CHECK ({tenant})"
    )
    op.execute(
        f'CREATE POLICY "{_TABLE}_tenant_update" ON "{_TABLE}" '
        f"AS RESTRICTIVE FOR UPDATE USING ({tenant}) WITH CHECK ({tenant})"
    )
    op.execute(
        f'CREATE POLICY "{_TABLE}_tenant_delete" ON "{_TABLE}" '
        f"AS RESTRICTIVE FOR DELETE USING ({tenant})"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for operation in _OPERATIONS:
        op.execute(f'DROP POLICY IF EXISTS "{_TABLE}_tenant_{operation}" ON "{_TABLE}"')
    op.execute(f'ALTER TABLE "{_TABLE}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{_TABLE}" DISABLE ROW LEVEL SECURITY')
