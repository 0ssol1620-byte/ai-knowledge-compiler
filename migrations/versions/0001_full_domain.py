"""Create the complete v1 tenant-safe domain schema.

Revision ID: 0001_full_domain
Revises:
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op

from akc_api import models as _models  # noqa: F401
from akc_api.database import Base

revision = "0001_full_domain"
down_revision = None
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "tenants",
    "memberships",
    "api_keys",
    "projects",
    "upload_sessions",
    "source_files",
    "documents",
    "document_versions",
    "pages",
    "page_assets",
    "blocks",
    "block_revisions",
    "processing_jobs",
    "job_events",
    "review_items",
    "knowledge_notes",
    "entities",
    "relations",
    "exports",
    "credit_accounts",
    "credit_ledger",
    "idempotency_records",
    "outbox_events",
    "audit_events",
    "deletion_receipts",
    "webhook_endpoints",
    "webhook_deliveries",
    "feature_flags",
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    if bind.dialect.name != "postgresql":
        return
    for table in TENANT_TABLES:
        tenant_expression = "id" if table == "tenants" else "tenant_id"
        if table == "memberships":
            using = (
                "(tenant_id = "
                "NULLIF(current_setting('app.tenant_id', true), '')::uuid "
                "OR user_id = "
                "NULLIF(current_setting('app.user_id', true), '')::uuid)"
            )
            check = (
                "(tenant_id = "
                "NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
            )
        elif table == "feature_flags":
            using = (
                "(tenant_id IS NULL OR tenant_id = "
                "NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
            )
            check = (
                "(tenant_id = "
                "NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
            )
        else:
            using = (
                f"({tenant_expression} = "
                "NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
            )
            check = using
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f"USING {using} WITH CHECK {check}"
        )
    op.execute("REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON deletion_receipts FROM PUBLIC")


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, checkfirst=True)
