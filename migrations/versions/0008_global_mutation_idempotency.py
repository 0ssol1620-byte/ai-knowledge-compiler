"""Harden and retain global mutation idempotency records.

Revision ID: 0008_global_mutation_idempotency
Revises: 0007_job_event_retention
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0008_global_mutation_idempotency"
down_revision = "0007_job_event_retention"
branch_labels = None
depends_on = None

SCHEDULER_ROLE = "akc_scheduler"


def _columns(table: str) -> set[str]:
    return {str(column["name"]) for column in inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {str(index["name"]) for index in inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if "response_body_ciphertext" not in _columns("idempotency_records"):
        op.add_column(
            "idempotency_records",
            sa.Column("response_body_ciphertext", sa.LargeBinary()),
        )
    if "idempotency_records_expiry_idx" not in _indexes("idempotency_records"):
        op.create_index(
            "idempotency_records_expiry_idx",
            "idempotency_records",
            ["expires_at", "id"],
        )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"GRANT SELECT, DELETE ON TABLE idempotency_records TO {SCHEDULER_ROLE}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE SELECT, DELETE ON TABLE idempotency_records FROM {SCHEDULER_ROLE}")
    if "idempotency_records_expiry_idx" in _indexes("idempotency_records"):
        op.drop_index(
            "idempotency_records_expiry_idx",
            table_name="idempotency_records",
        )
    if "response_body_ciphertext" in _columns("idempotency_records"):
        op.drop_column("idempotency_records", "response_body_ciphertext")
