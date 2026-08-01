from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import pytest
from akc_domain_packs import (
    ArchitectureProfile,
    builtin_blueprint_modules,
    builtin_blueprints,
    plan_architecture,
    registry_from_modules,
    validate_blueprint_module,
    validate_blueprint_payload,
)


def test_builtin_registry_contains_the_seven_v4_blueprints() -> None:
    registry = builtin_blueprints()
    assert {blueprint.id for blueprint in registry.blueprints} == {
        "corporate-filings",
        "research-library",
        "technical-documentation",
        "course-materials",
        "personal-knowledge",
        "legal-contracts",
        "generic-mixed-corpus",
    }
    assert all(blueprint.source_preservation for blueprint in registry.blueprints)
    assert all(
        "model_inferred" not in blueprint.relation_policy for blueprint in registry.blueprints
    )
    assert set(registry.module_sha256) == {blueprint.id for blueprint in registry.blueprints}


def test_every_module_contains_the_complete_declarative_drop_in_contract() -> None:
    required = {
        "ontology/ontology.yaml",
        "schemas/objects.schema.json",
        "prompts/compiler.md",
        "templates/views.yaml",
        "directory/layout.yaml",
        "validators/rules.yaml",
        "mappings/canonical.yaml",
        "examples/example.yaml",
        "tests/cases.yaml",
        "migrations/manifest.yaml",
    }
    modules = builtin_blueprint_modules()
    assert len(modules) == 7
    for module in modules:
        assert required.issubset({asset.path for asset in module.assets})
        assert module.module_sha256.startswith("sha256:")
        assert all(asset.size_bytes > 0 for asset in module.assets)


def test_drop_in_registry_rejects_replacement_of_a_builtin_module() -> None:
    duplicate = builtin_blueprint_modules()[0]
    with pytest.raises(ValueError, match="cannot replace"):
        registry_from_modules((duplicate,))


def test_architecture_plan_is_deterministic_and_finance_specific() -> None:
    profile = ArchitectureProfile(
        domain="finance",
        object_types=("company", "filing", "metric"),
        user_goal="Build an authority-grounded filing knowledge base",
        corpus_size=5000,
        temporal_structure="quarterly",
    )
    first = plan_architecture(profile)
    second = plan_architecture(profile)
    assert first == second
    assert first.blueprint == "corporate-filings"
    assert first.root_views == ("Companies", "Filings", "Risks", "Metrics")
    assert first.source_preservation
    assert first.module_sha256 == builtin_blueprints().module_sha256["corporate-filings"]
    assert first.plan_sha256.startswith("sha256:")


@pytest.mark.parametrize("forbidden", ["python", "shell", "network", "url"])
def test_blueprint_payload_rejects_executable_or_network_keys(forbidden: str) -> None:
    payload = {
        "id": "unsafe-module",
        "version": "1.0.0",
        "display_name": "Unsafe",
        "domains": ["general"],
        "object_types": ["document"],
        "root_views": ["Documents"],
        "moc_templates": ["Documents"],
        "folder_depth": 2,
        "naming_policy": "stable-title",
        "source_preservation": True,
        "relation_policy": ["source_explicit"],
        "validators": ["source_coverage"],
        "export_profiles": ["obsidian"],
        forbidden: "forbidden",
    }
    with pytest.raises(ValueError, match="forbidden executable key"):
        validate_blueprint_payload(payload)


def test_module_rejects_missing_component_directory(tmp_path: Path) -> None:
    # A synthetic path-like module proves the registry fails closed before activation.
    module = tmp_path / "corporate-filings"
    module.mkdir()
    module_source = files("akc_domain_packs").joinpath(
        "blueprints", "corporate-filings", "module.yaml"
    )
    (module / "module.yaml").write_bytes(module_source.read_bytes())
    with pytest.raises(ValueError, match=r"missing ontology/ontology\.yaml"):
        validate_blueprint_module(module)
