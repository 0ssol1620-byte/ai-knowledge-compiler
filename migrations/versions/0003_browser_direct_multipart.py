"""Add resumable browser-direct multipart upload session state.

Revision ID: 0003_browser_multipart
Revises: 0002_scheduler_hardening
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0003_browser_multipart"
down_revision = "0002_scheduler_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {str(column["name"]) for column in inspector.get_columns("upload_sessions")}
    constraints = {
        str(constraint["name"])
        for constraint in inspector.get_check_constraints("upload_sessions")
        if constraint.get("name")
    }
    indexes = {str(index["name"]) for index in inspector.get_indexes("upload_sessions")}
    with op.batch_alter_table("upload_sessions") as batch:
        if "upload_mode" not in columns:
            batch.add_column(
                sa.Column(
                    "upload_mode",
                    sa.String(length=16),
                    nullable=False,
                    server_default="single",
                )
            )
        if "provider_upload_id" not in columns:
            batch.add_column(sa.Column("provider_upload_id", sa.String(length=512), nullable=True))
        if "multipart_part_size" not in columns:
            batch.add_column(sa.Column("multipart_part_size", sa.Integer(), nullable=True))
        if "multipart_part_count" not in columns:
            batch.add_column(sa.Column("multipart_part_count", sa.Integer(), nullable=True))
        if "ck_upload_sessions_upload_mode" not in constraints:
            batch.create_check_constraint(
                "ck_upload_sessions_upload_mode",
                "upload_mode IN ('single','multipart')",
            )
        if "ck_upload_sessions_multipart_shape" not in constraints:
            batch.create_check_constraint(
                "ck_upload_sessions_multipart_shape",
                "(upload_mode = 'single' AND provider_upload_id IS NULL "
                "AND multipart_part_size IS NULL AND multipart_part_count IS NULL) "
                "OR (upload_mode = 'multipart' AND provider_upload_id IS NOT NULL "
                "AND multipart_part_size > 0 AND multipart_part_count > 0)",
            )
        if "upload_sessions_expiry_idx" not in indexes:
            batch.create_index(
                "upload_sessions_expiry_idx",
                ["status", "expires_at"],
                unique=False,
            )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {str(column["name"]) for column in inspector.get_columns("upload_sessions")}
    constraints = {
        str(constraint["name"])
        for constraint in inspector.get_check_constraints("upload_sessions")
        if constraint.get("name")
    }
    indexes = {str(index["name"]) for index in inspector.get_indexes("upload_sessions")}
    with op.batch_alter_table("upload_sessions") as batch:
        if "upload_sessions_expiry_idx" in indexes:
            batch.drop_index("upload_sessions_expiry_idx")
        if "ck_upload_sessions_multipart_shape" in constraints:
            batch.drop_constraint(
                "ck_upload_sessions_multipart_shape",
                type_="check",
            )
        if "ck_upload_sessions_upload_mode" in constraints:
            batch.drop_constraint(
                "ck_upload_sessions_upload_mode",
                type_="check",
            )
        if "multipart_part_count" in columns:
            batch.drop_column("multipart_part_count")
        if "multipart_part_size" in columns:
            batch.drop_column("multipart_part_size")
        if "provider_upload_id" in columns:
            batch.drop_column("provider_upload_id")
        if "upload_mode" in columns:
            batch.drop_column("upload_mode")
