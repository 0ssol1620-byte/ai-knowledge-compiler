from __future__ import annotations

import pytest
from akc_domain_packs import (
    SchemaPolicyError,
    builtin_domain_packs,
    validate_user_schema,
)


def test_all_six_product_domain_packs_are_versioned_and_unique() -> None:
    registry = builtin_domain_packs()

    assert {pack.id for pack in registry.packs} == {
        "study_pack",
        "research_pack",
        "work_project_pack",
        "legal_contract_pack",
        "technical_support_pack",
        "archive_book_pack",
    }
    assert all(pack.quality_rules for pack in registry.packs)
    assert all(
        rule.severity != "review_required" or rule.autonomous_outcome == "unresolved"
        for pack in registry.packs
        for rule in pack.quality_rules
    )
    assert registry.get("legal_contract_pack").forbidden_claims


def test_closed_custom_schema_returns_stable_content_receipt() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "case_number": {"type": "string", "maxLength": 80},
            "priority": {"enum": ["low", "medium", "high"]},
        },
        "required": ["case_number"],
    }

    first = validate_user_schema(schema)
    second = validate_user_schema(dict(reversed(list(schema.items()))))

    assert first.schema_sha256 == second.schema_sha256
    assert first.property_count == 2
    assert first.policy_version == "custom-schema-policy-1.0"


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        (
            {"type": "object", "additionalProperties": True, "properties": {}},
            "closed object",
        ),
        (
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"evidenceBlockIds": {"type": "array"}},
            },
            "provenance",
        ),
        (
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"x": {"$ref": "https://evil.example/schema.json"}},
            },
            "local",
        ),
        (
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"x": {"type": "string", "pattern": "(a+)+$"}},
            },
            "backtracking",
        ),
    ],
)
def test_unsafe_custom_schema_features_fail_closed(
    schema: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(SchemaPolicyError, match=message):
        validate_user_schema(schema)


def test_schema_depth_and_size_are_bounded() -> None:
    child: dict[str, object] = {"type": "string"}
    for _ in range(25):
        child = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"nested": child},
        }
    with pytest.raises(SchemaPolicyError, match="nesting"):
        validate_user_schema(child)

    with pytest.raises(SchemaPolicyError, match="byte limit"):
        validate_user_schema(
            {
                "type": "object",
                "additionalProperties": False,
                "description": "x" * (129 * 1024),
                "properties": {},
            }
        )
