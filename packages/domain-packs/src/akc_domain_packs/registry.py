"""Strict built-in domain packs and bounded custom JSON Schema validation."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Any, Literal

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_PACK_ID = r"^[a-z][a-z0-9_]{2,79}$"
_VERSION = r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$"
_SAFE_PROFILE = r"^[a-z][a-z0-9_]{2,79}$"
_MAX_SCHEMA_BYTES = 128 * 1024
_MAX_SCHEMA_NODES = 5_000
_MAX_SCHEMA_DEPTH = 20
_RESERVED_PROPERTIES = frozenset(
    {
        "documentId",
        "document_id",
        "evidenceBlockIds",
        "evidence_block_ids",
        "sourceBlockIds",
        "source_block_ids",
        "contentOrigin",
        "content_origin",
        "reviewStatus",
        "review_status",
    }
)


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QualityRule(WireModel):
    id: Annotated[str, Field(pattern=_PACK_ID)]
    description: Annotated[str, Field(min_length=1, max_length=500)]
    severity: Literal["warning", "review_required", "hard_fail"]
    evaluator: Annotated[str, Field(pattern=_SAFE_PROFILE)]


class DomainPack(WireModel):
    id: Annotated[str, Field(pattern=_PACK_ID)]
    version: Annotated[str, Field(pattern=_VERSION)]
    display_name: Annotated[str, Field(min_length=1, max_length=120)]
    description: Annotated[str, Field(min_length=1, max_length=1_000)]
    note_types: Annotated[tuple[str, ...], Field(min_length=1, max_length=30)]
    knowledge_profile: Annotated[str, Field(pattern=_SAFE_PROFILE)]
    export_profiles: Annotated[tuple[str, ...], Field(min_length=1, max_length=10)]
    quality_rules: Annotated[tuple[QualityRule, ...], Field(min_length=1, max_length=30)]
    forbidden_claims: Annotated[tuple[str, ...], Field(max_length=30)] = ()

    @field_validator("note_types", "export_profiles", "forbidden_claims")
    @classmethod
    def unique_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("domain-pack lists must not contain duplicates")
        if any(not item or len(item) > 100 for item in value):
            raise ValueError("domain-pack list item is invalid")
        return value

    @model_validator(mode="after")
    def unique_rules(self) -> DomainPack:
        rule_ids = [rule.id for rule in self.quality_rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("domain-pack quality rule IDs must be unique")
        return self


class DomainPackRegistry(WireModel):
    registry_version: Annotated[str, Field(pattern=_VERSION)]
    packs: tuple[DomainPack, ...]

    @model_validator(mode="after")
    def unique_packs(self) -> DomainPackRegistry:
        pack_ids = [pack.id for pack in self.packs]
        if not pack_ids or len(pack_ids) != len(set(pack_ids)):
            raise ValueError("domain-pack IDs must be non-empty and unique")
        return self

    def get(self, pack_id: str) -> DomainPack:
        for pack in self.packs:
            if pack.id == pack_id:
                return pack
        raise LookupError(f"unknown domain pack: {pack_id}")


class UserSchemaReceipt(WireModel):
    schema_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    canonical_size_bytes: Annotated[int, Field(ge=2, le=_MAX_SCHEMA_BYTES)]
    property_count: Annotated[int, Field(ge=0, le=1_000)]
    maximum_depth: Annotated[int, Field(ge=1, le=_MAX_SCHEMA_DEPTH)]
    policy_version: Literal["custom-schema-policy-1.0"] = "custom-schema-policy-1.0"


class SchemaPolicyError(ValueError):
    pass


@lru_cache(maxsize=1)
def builtin_domain_packs() -> DomainPackRegistry:
    resource = files("akc_domain_packs").joinpath("domain-packs.yaml")
    raw = resource.read_bytes()
    if not raw or len(raw) > 512 * 1024:
        raise RuntimeError("built-in domain-pack registry size is invalid")
    try:
        value = yaml.safe_load(raw)
        return DomainPackRegistry.model_validate(value)
    except (yaml.YAMLError, ValueError, TypeError) as exc:
        raise RuntimeError("built-in domain-pack registry is invalid") from exc


def _walk_schema(value: Any, *, depth: int = 1) -> tuple[int, int]:
    if depth > _MAX_SCHEMA_DEPTH:
        raise SchemaPolicyError("custom schema exceeds the maximum nesting depth")
    nodes = 1
    maximum_depth = depth
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 200:
                raise SchemaPolicyError("custom schema contains an invalid key")
            if key == "$ref" and (not isinstance(child, str) or not child.startswith("#/$defs/")):
                raise SchemaPolicyError("custom schema permits only local $defs references")
            if key == "$id":
                raise SchemaPolicyError("custom schema must not declare a remote identity")
            if key == "pattern":
                _validate_pattern(child)
            child_nodes, child_depth = _walk_schema(child, depth=depth + 1)
            nodes += child_nodes
            maximum_depth = max(maximum_depth, child_depth)
    elif isinstance(value, list):
        for child in value:
            child_nodes, child_depth = _walk_schema(child, depth=depth + 1)
            nodes += child_nodes
            maximum_depth = max(maximum_depth, child_depth)
    if nodes > _MAX_SCHEMA_NODES:
        raise SchemaPolicyError("custom schema exceeds the maximum node count")
    return nodes, maximum_depth


def _validate_pattern(value: Any) -> None:
    if not isinstance(value, str) or len(value) > 200:
        raise SchemaPolicyError("custom schema pattern is invalid")
    if (
        "(?" in value
        or re.search(r"\\[1-9]", value)
        or re.search(r"[*+?}][*+?{]", value)
        or re.search(r"\([^)]*[*+][^)]*\)[*+{]", value)
    ):
        raise SchemaPolicyError("custom schema pattern uses a forbidden backtracking construct")
    try:
        re.compile(value)
    except re.error as exc:
        raise SchemaPolicyError("custom schema pattern is invalid") from exc


def validate_user_schema(schema: dict[str, Any]) -> UserSchemaReceipt:
    """Validate a bounded extension schema without dereferencing remote content."""

    try:
        canonical = json.dumps(
            schema,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise SchemaPolicyError("custom schema is not canonical JSON") from exc
    if not canonical or len(canonical) > _MAX_SCHEMA_BYTES:
        raise SchemaPolicyError("custom schema exceeds the byte limit")
    if schema.get("$schema") not in {
        None,
        "https://json-schema.org/draft/2020-12/schema",
    }:
        raise SchemaPolicyError("custom schema must use JSON Schema 2020-12")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise SchemaPolicyError(
            "custom schema root must be a closed object with additionalProperties=false"
        )
    properties = schema.get("properties", {})
    if not isinstance(properties, dict) or len(properties) > 1_000:
        raise SchemaPolicyError("custom schema properties are invalid")
    reserved = _RESERVED_PROPERTIES.intersection(properties)
    if reserved:
        raise SchemaPolicyError("custom schema cannot override provenance-controlled fields")
    _, maximum_depth = _walk_schema(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SchemaPolicyError("custom schema fails JSON Schema validation") from exc
    return UserSchemaReceipt(
        schema_sha256="sha256:" + hashlib.sha256(canonical).hexdigest(),
        canonical_size_bytes=len(canonical),
        property_count=len(properties),
        maximum_depth=maximum_depth,
    )
