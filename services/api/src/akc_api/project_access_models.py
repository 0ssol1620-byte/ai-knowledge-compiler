"""Project-scoped membership persistence.

Tenant owners and administrators retain implicit access to every project.  The
rows in this table are therefore the explicit, bounded grants used by all
other tenant roles.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from akc_api.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProjectMembership(Base):
    """An explicit project grant constrained by the tenant-level role."""

    __tablename__ = "project_memberships"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="viewer")
    granted_by: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "role IN ('editor','reviewer','viewer')",
            name="project_memberships_role_check",
        ),
        Index(
            "project_memberships_user_projects_idx",
            "tenant_id",
            "user_id",
            "project_id",
        ),
    )
