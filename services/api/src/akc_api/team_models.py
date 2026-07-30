"""Tenant-scoped persistence for team invitations and their delivery outbox."""

from __future__ import annotations

import uuid
from datetime import datetime

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

from akc_api.database import Base
from akc_api.models import utcnow, uuid4


class TeamInvitation(Base):
    """One-time team membership grant with no plaintext token or email."""

    __tablename__ = "team_invitations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    invited_by: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id"),
        nullable=False,
    )
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id"),
    )
    recipient_pseudonym: Mapped[str] = mapped_column(String(67), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(
            "role IN ('owner','admin','editor','reviewer','viewer','billing')",
            name="team_invitations_role_check",
        ),
        CheckConstraint(
            "status IN ('pending','accepted','cancelled','expired')",
            name="team_invitations_status_check",
        ),
        CheckConstraint(
            "("
            "status = 'pending' AND accepted_at IS NULL AND cancelled_at IS NULL"
            ") OR ("
            "status = 'accepted' AND accepted_at IS NOT NULL "
            "AND cancelled_at IS NULL AND accepted_by IS NOT NULL"
            ") OR ("
            "status = 'cancelled' AND cancelled_at IS NOT NULL "
            "AND accepted_at IS NULL"
            ") OR ("
            "status = 'expired' AND accepted_at IS NULL"
            ")",
            name="team_invitations_state_check",
        ),
        Index(
            "team_invitations_tenant_created_idx",
            "tenant_id",
            "created_at",
            "id",
        ),
        Index(
            "team_invitations_expiry_idx",
            "expires_at",
            "id",
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index(
            "team_invitations_active_recipient_uq",
            "tenant_id",
            "recipient_pseudonym",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )


class TeamInvitationDelivery(Base):
    """Encrypted, retryable invitation email outbox."""

    __tablename__ = "team_invitation_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    invitation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    recipient_pseudonym: Mapped[str] = mapped_column(String(67), nullable=False)
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "invitation_id"],
            ["team_invitations.tenant_id", "team_invitations.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "invitation_id"),
        CheckConstraint(
            "status IN ('pending','retry','delivered','dead_letter')",
            name="team_invitation_deliveries_status_check",
        ),
        CheckConstraint("attempts >= 0", name="team_invitation_deliveries_attempts_check"),
        Index(
            "team_invitation_deliveries_due_idx",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text("status IN ('pending','retry')"),
            sqlite_where=text("status IN ('pending','retry')"),
        ),
    )
