"""Give every source adapter one durable row to park its resume token in.

**Why a table, and why now.** The adapters in ``packages/source-adapters``
turn an upstream system into an ordered stream of change events, and each poll
returns the cursor to resume from next time. Nothing here stores it yet: a
scheduler restart would drop the token and force every source back to a full
pull, re-emitting history the compiler already has. ``source_cursors`` is the
one row per source where the latest cursor is written after a successful fetch
and read before the next one.

**One row per source, keyed by ``source_id``.** The adapter builds ids like
``git:<repo>`` or ``obsidian:<vault>``, so the primary key *is* the identity
the events carry — there is no second id to keep in sync, and upserting a
poll's cursor cannot fan out into duplicates. ``adapter`` names the connector
that wrote the token (``git``, ``obsidian``, ...) so an operator can see what
produced a stuck position without decoding the payload.

**``cursor`` is the adapter's own state, not a schema of ours.** The git
adapter keeps ``{"head": <sha>}``; the obsidian adapter keeps a whole
``path -> {sha256, mtime_ns, size}`` snapshot. Both are canonical JSON by
construction (``akc_source_adapters.envelope.canonical_json``), so the column
is ``jsonb`` on PostgreSQL — queryable when someone must debug a resume, and
byte-stable across writers because the adapters already normalize keys. The
SQLite development database has no ``jsonb`` and takes plain ``JSON`` with the
same shape.

**What this migration deliberately does not do.** No foreign keys into source
registries (none exists yet), no index beyond the primary key (the access path
is always "one source's latest cursor", which the key already serves), and no
history — the table holds positions, not events; the event log lives elsewhere.
Losing a row costs at most one redundant full pull, so the table stays simple
on purpose.

Revision ID: 0039_source_adapter_cursors
Revises: 0037_gpu_post_claim_authorization
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0039_source_adapter_cursors"
down_revision = "0038_identity_ledger"
branch_labels = None
depends_on = None

TABLE = "source_cursors"

# Adapter-built ids ("git:<repo>", "obsidian:<vault>") are directory names at
# heart; 255 covers every plausible name without inviting unbounded text keys.
SOURCE_ID_LENGTH = 255
ADAPTER_LENGTH = 64


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("source_id", sa.String(length=SOURCE_ID_LENGTH), primary_key=True),
        sa.Column("adapter", sa.String(length=ADAPTER_LENGTH), nullable=False),
        # jsonb on PostgreSQL; the dev SQLite database has no jsonb and gets
        # plain JSON with the identical shape.
        sa.Column(
            "cursor",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
