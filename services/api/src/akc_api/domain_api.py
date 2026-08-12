"""Authenticated domain-pack discovery and bounded custom-schema validation."""

from __future__ import annotations

from typing import Annotated, Any

from akc_domain_packs import (
    ArchitecturePlan,
    ArchitectureProfile,
    BlueprintModule,
    BlueprintRegistry,
    DomainPack,
    DomainPackRegistry,
    SchemaPolicyError,
    UserSchemaReceipt,
    builtin_blueprint_modules,
    builtin_blueprints,
    builtin_domain_packs,
    plan_architecture,
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


@router.get("/knowledge-blueprints", response_model=BlueprintRegistry)
async def list_knowledge_blueprints(_principal: PrincipalDep) -> BlueprintRegistry:
    """Return only modules that passed the complete declarative asset validator."""

    return builtin_blueprints()


@router.get("/knowledge-blueprints/{blueprint_id}", response_model=BlueprintModule)
async def get_knowledge_blueprint(
    blueprint_id: str,
    _principal: PrincipalDep,
) -> BlueprintModule:
    for module in builtin_blueprint_modules():
        if module.blueprint.id == blueprint_id:
            return module
    raise HTTPException(
        status_code=404,
        detail={"code": "KNOWLEDGE_BLUEPRINT_NOT_FOUND"},
    )


@router.post("/knowledge-blueprints/plan", response_model=ArchitecturePlan)
async def create_architecture_plan(
    payload: ArchitectureProfile,
    _principal: EditorDep,
) -> ArchitecturePlan:
    """Create a deterministic plan tied to the validated module digest."""

    try:
        return plan_architecture(payload)
    except LookupError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "KNOWLEDGE_BLUEPRINT_NOT_FOUND"},
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
