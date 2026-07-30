"""Authenticated domain-pack discovery and bounded custom-schema validation."""

from __future__ import annotations

from typing import Annotated, Any

from akc_domain_packs import (
    DomainPack,
    DomainPackRegistry,
    SchemaPolicyError,
    UserSchemaReceipt,
    builtin_domain_packs,
    validate_user_schema,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from akc_api.security import Principal, get_principal, require_roles

router = APIRouter(prefix="/v1", tags=["domain-packs"])
PrincipalDep = Annotated[Principal, Depends(get_principal)]
EditorDep = Annotated[Principal, Depends(require_roles("owner", "admin", "editor"))]


class CustomSchemaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    custom_schema: dict[str, Any] = Field(alias="schema")


@router.get("/domain-packs", response_model=DomainPackRegistry)
async def list_domain_packs(_principal: PrincipalDep) -> DomainPackRegistry:
    return builtin_domain_packs()


@router.get("/domain-packs/{pack_id}", response_model=DomainPack)
async def get_domain_pack(pack_id: str, _principal: PrincipalDep) -> DomainPack:
    try:
        return builtin_domain_packs().get(pack_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOMAIN_PACK_NOT_FOUND"},
        ) from exc


@router.post(
    "/schema-profiles/validate",
    response_model=UserSchemaReceipt,
)
async def validate_custom_schema(
    payload: CustomSchemaRequest,
    _principal: EditorDep,
) -> UserSchemaReceipt:
    try:
        return validate_user_schema(payload.custom_schema)
    except SchemaPolicyError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "CUSTOM_SCHEMA_POLICY_VIOLATION"},
        ) from exc
