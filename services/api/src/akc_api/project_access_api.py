"""Owner/admin API for explicit project membership management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from akc_api.database import get_session
from akc_api.idempotency import idempotent_mutation
from akc_api.models import Membership, Project, User, utcnow
from akc_api.project_access import (
    ProjectRole,
    allowed_project_roles_for_tenant_role,
)
from akc_api.project_access_models import ProjectMembership
from akc_api.security import Principal, require_roles
from akc_api.services import audit

router = APIRouter(prefix="/v1", tags=["project-access"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ProjectAdminDep = Annotated[Principal, Depends(require_roles("owner", "admin"))]


class WireModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ProjectMemberGrant(WireModel):
    user_id: uuid.UUID
    role: ProjectRole


class ProjectMemberRolePatch(WireModel):
    role: ProjectRole


class ProjectMemberResponse(WireModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: Literal["editor", "reviewer", "viewer"]
    tenant_role: str
    created_at: datetime
    updated_at: datetime


class ProjectMemberListResponse(WireModel):
    items: list[ProjectMemberResponse]


async def _project(
    session: AsyncSession,
    *,
    principal: Principal,
    project_id: uuid.UUID,
    lock: bool = False,
) -> Project:
    statement = select(Project).where(
        Project.tenant_id == principal.tenant_id,
        Project.id == project_id,
        Project.deletion_requested_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    project = await session.scalar(statement)
    if project is None:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})
    return project


async def _target(
    session: AsyncSession,
    *,
    principal: Principal,
    user_id: uuid.UUID,
) -> tuple[User, Membership]:
    row = (
        await session.execute(
            select(User, Membership)
            .join(
                Membership,
                (Membership.user_id == User.id)
                & (Membership.tenant_id == principal.tenant_id),
            )
            .where(User.id == user_id, User.is_active.is_(True))
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "TEAM_MEMBER_NOT_FOUND"})
    return cast(User, row[0]), cast(Membership, row[1])


def _authorize_target_role(membership: Membership, role: ProjectRole) -> None:
    if membership.role in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "PROJECT_ACCESS_IMPLICIT_ADMIN"},
        )
    if role not in allowed_project_roles_for_tenant_role(membership.role):
        raise HTTPException(
            status_code=403,
            detail={"code": "PROJECT_ROLE_ESCALATION_DENIED"},
        )


def _response(
    row: ProjectMembership,
    *,
    user: User,
    tenant_membership: Membership,
) -> ProjectMemberResponse:
    return ProjectMemberResponse(
        user_id=row.user_id,
        email=user.email,
        display_name=user.display_name,
        role=cast(Literal["editor", "reviewer", "viewer"], row.role),
        tenant_role=tenant_membership.role,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get(
    "/projects/{project_id}/members",
    response_model=ProjectMemberListResponse,
)
async def list_project_members(
    project_id: uuid.UUID,
    principal: ProjectAdminDep,
    session: SessionDep,
) -> ProjectMemberListResponse:
    await _project(session, principal=principal, project_id=project_id)
    rows = (
        await session.execute(
            select(ProjectMembership, User, Membership)
            .join(User, User.id == ProjectMembership.user_id)
            .join(
                Membership,
                (Membership.tenant_id == ProjectMembership.tenant_id)
                & (Membership.user_id == ProjectMembership.user_id),
            )
            .where(
                ProjectMembership.tenant_id == principal.tenant_id,
                ProjectMembership.project_id == project_id,
                User.is_active.is_(True),
            )
            .order_by(ProjectMembership.created_at, ProjectMembership.user_id)
        )
    ).all()
    return ProjectMemberListResponse(
        items=[
            _response(project_membership, user=user, tenant_membership=membership)
            for project_membership, user, membership in rows
        ]
    )


@router.post(
    "/projects/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=201,
)
@idempotent_mutation
async def grant_project_member(
    project_id: uuid.UUID,
    payload: ProjectMemberGrant,
    principal: ProjectAdminDep,
    session: SessionDep,
) -> ProjectMemberResponse:
    await _project(session, principal=principal, project_id=project_id, lock=True)
    user, tenant_membership = await _target(
        session,
        principal=principal,
        user_id=payload.user_id,
    )
    _authorize_target_role(tenant_membership, payload.role)
    row = await session.scalar(
        select(ProjectMembership)
        .where(
            ProjectMembership.tenant_id == principal.tenant_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == payload.user_id,
        )
        .with_for_update()
    )
    if row is not None:
        if row.role != payload.role:
            raise HTTPException(
                status_code=409,
                detail={"code": "PROJECT_MEMBERSHIP_EXISTS"},
            )
        return _response(row, user=user, tenant_membership=tenant_membership)
    row = ProjectMembership(
        tenant_id=principal.tenant_id,
        project_id=project_id,
        user_id=payload.user_id,
        role=payload.role,
        granted_by=principal.user_id,
    )
    session.add(row)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="project.member_granted",
        target_type="project_membership",
        target_id=f"{project_id}:{payload.user_id}",
        metadata={
            "project_id": str(project_id),
            "user_id": str(payload.user_id),
            "role": payload.role,
        },
    )
    await session.commit()
    return _response(row, user=user, tenant_membership=tenant_membership)


@router.patch(
    "/projects/{project_id}/members/{user_id}",
    response_model=ProjectMemberResponse,
)
@idempotent_mutation
async def change_project_member_role(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: ProjectMemberRolePatch,
    principal: ProjectAdminDep,
    session: SessionDep,
) -> ProjectMemberResponse:
    await _project(session, principal=principal, project_id=project_id, lock=True)
    user, tenant_membership = await _target(
        session,
        principal=principal,
        user_id=user_id,
    )
    _authorize_target_role(tenant_membership, payload.role)
    row = await session.scalar(
        select(ProjectMembership)
        .where(
            ProjectMembership.tenant_id == principal.tenant_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "PROJECT_MEMBERSHIP_NOT_FOUND"},
        )
    if row.role != payload.role:
        row.role = payload.role
        row.granted_by = principal.user_id
        row.updated_at = utcnow()
        await audit(
            session,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            action="project.member_role_changed",
            target_type="project_membership",
            target_id=f"{project_id}:{user_id}",
            metadata={"project_id": str(project_id), "user_id": str(user_id), "role": payload.role},
        )
        await session.commit()
    return _response(row, user=user, tenant_membership=tenant_membership)


@router.delete(
    "/projects/{project_id}/members/{user_id}",
    status_code=204,
)
@idempotent_mutation
async def revoke_project_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    principal: ProjectAdminDep,
    session: SessionDep,
) -> Response:
    await _project(session, principal=principal, project_id=project_id, lock=True)
    target = await session.execute(
        select(User, Membership)
        .join(
            Membership,
            (Membership.user_id == User.id)
            & (Membership.tenant_id == principal.tenant_id),
        )
        .where(User.id == user_id)
    )
    target_row = target.one_or_none()
    if target_row is not None and cast(Membership, target_row[1]).role in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "PROJECT_ACCESS_IMPLICIT_ADMIN"},
        )
    row = await session.scalar(
        select(ProjectMembership)
        .where(
            ProjectMembership.tenant_id == principal.tenant_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        return Response(status_code=204)
    await session.delete(row)
    await audit(
        session,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        action="project.member_revoked",
        target_type="project_membership",
        target_id=f"{project_id}:{user_id}",
        metadata={"project_id": str(project_id), "user_id": str(user_id)},
    )
    await session.commit()
    return Response(status_code=204)
