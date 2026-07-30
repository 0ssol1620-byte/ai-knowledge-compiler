"""Central project authorization predicates and guards."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import ColumnElement, exists, false, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from akc_api.project_access_models import ProjectMembership
from akc_api.security import Principal

ProjectCapability = Literal["read", "review", "write", "manage"]
ProjectRole = Literal["editor", "reviewer", "viewer"]

_ADMIN_ROLES = frozenset({"owner", "admin"})
_TENANT_CAPABILITIES: dict[str, frozenset[ProjectCapability]] = {
    "editor": frozenset({"read", "review", "write"}),
    "reviewer": frozenset({"read", "review"}),
    "viewer": frozenset({"read"}),
    "billing": frozenset(),
}
_PROJECT_CAPABILITIES: dict[str, frozenset[ProjectCapability]] = {
    "editor": frozenset({"read", "review", "write"}),
    "reviewer": frozenset({"read", "review"}),
    "viewer": frozenset({"read"}),
}
_PROJECT_ROLES_FOR_CAPABILITY: dict[ProjectCapability, tuple[str, ...]] = {
    "read": ("editor", "reviewer", "viewer"),
    "review": ("editor", "reviewer"),
    "write": ("editor",),
    "manage": (),
}
_ROLE_CEILINGS: dict[str, frozenset[str]] = {
    "editor": frozenset({"editor", "reviewer", "viewer"}),
    "reviewer": frozenset({"reviewer", "viewer"}),
    "viewer": frozenset({"viewer"}),
    "billing": frozenset(),
}


def is_project_admin(principal: Principal) -> bool:
    """Return whether the tenant role grants implicit project administration."""

    return not principal.roles.isdisjoint(_ADMIN_ROLES)


def tenant_allows(principal: Principal, capability: ProjectCapability) -> bool:
    if is_project_admin(principal):
        return True
    return any(
        capability in _TENANT_CAPABILITIES.get(role, frozenset())
        for role in principal.roles
    )


def allowed_project_roles_for_tenant_role(tenant_role: str) -> frozenset[str]:
    """Bound project grants so they can never elevate the tenant membership."""

    return _ROLE_CEILINGS.get(tenant_role, frozenset())


def project_access_predicate(
    principal: Principal,
    project_id_column: (
        ColumnElement[uuid.UUID] | InstrumentedAttribute[uuid.UUID]
    ),
    capability: ProjectCapability = "read",
) -> ColumnElement[bool]:
    """Build a reusable SQL predicate for lists and direct resource queries."""

    if is_project_admin(principal):
        return true()
    if not tenant_allows(principal, capability):
        return false()
    project_roles = _PROJECT_ROLES_FOR_CAPABILITY[capability]
    if not project_roles:
        return false()
    return exists(
        select(ProjectMembership.project_id).where(
            ProjectMembership.tenant_id == principal.tenant_id,
            ProjectMembership.project_id == project_id_column,
            ProjectMembership.user_id == principal.user_id,
            ProjectMembership.role.in_(project_roles),
        )
    )


async def require_project_access(
    session: AsyncSession,
    *,
    principal: Principal,
    project_id: uuid.UUID,
    capability: ProjectCapability = "read",
) -> ProjectMembership | None:
    """Enforce the tenant/project role intersection.

    An absent explicit grant is deliberately indistinguishable from an absent
    project.  A present grant with insufficient effective privilege returns
    403 so clients can distinguish assignment from role limitations.
    """

    if is_project_admin(principal):
        return None
    membership = await session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.tenant_id == principal.tenant_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == principal.user_id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROJECT_NOT_FOUND"},
        )
    if (
        not tenant_allows(principal, capability)
        or capability not in _PROJECT_CAPABILITIES.get(membership.role, frozenset())
    ):
        raise HTTPException(
            status_code=403,
            detail={"code": "PROJECT_PERMISSION_DENIED"},
        )
    return membership
