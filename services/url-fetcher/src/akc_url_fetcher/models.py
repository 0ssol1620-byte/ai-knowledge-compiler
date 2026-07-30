"""Persistence model for durable, tenant-bound URL ingestion."""

from __future__ import annotations

import uuid
from datetime import datetime

from akc_api.database import Base
from akc_api.models import utcnow, uuid4
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class UrlFetchTask(Base):
    """Encrypted URL request and its durable execution lease.

    ``encrypted_url`` is the sole at-rest representation containing the query
    string. ``canonical_url`` is deliberately query-free and ``query_hmac`` is
    a keyed correlation digest, so status and audit surfaces never reveal URL
    credentials.
    """

    __tablename__ = "url_fetch_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
    )
    encrypted_url: Mapped[bytes] = mapped_column(LargeBinary)
    canonical_url: Mapped[str] = mapped_column(String(2048))
    query_hmac: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    content_type: Mapped[str | None] = mapped_column(String(160))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_file_id"],
            ["source_files.tenant_id", "source_files.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "document_id"),
        CheckConstraint(
            "status IN "
            "('queued','running','retry','completed','failed','dead_letter','cancelled')",
            name="url_fetch_tasks_status_check",
        ),
        CheckConstraint("attempt_count >= 0", name="url_fetch_tasks_attempt_nonnegative"),
        CheckConstraint(
            "max_attempts BETWEEN 1 AND 10",
            name="url_fetch_tasks_max_attempts_check",
        ),
        CheckConstraint(
            "attempt_count <= max_attempts",
            name="url_fetch_tasks_attempt_bound",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="url_fetch_tasks_size_nonnegative",
        ),
        CheckConstraint(
            "query_hmac IS NULL OR length(query_hmac) = 64",
            name="url_fetch_tasks_query_hmac_shape",
        ),
        CheckConstraint(
            "source_sha256 IS NULL OR length(source_sha256) = 64",
            name="url_fetch_tasks_source_sha_shape",
        ),
        Index(
            "url_fetch_tasks_due_idx",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text("status IN ('queued','retry','running')"),
            sqlite_where=text("status IN ('queued','retry','running')"),
        ),
        Index(
            "url_fetch_tasks_tenant_created_idx",
            "tenant_id",
            "created_at",
            "id",
        ),
    )
