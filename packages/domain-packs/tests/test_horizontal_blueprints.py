from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
import yaml
from akc_domain_packs import ArchitectureProfile, builtin_blueprints, plan_architecture
from akc_domain_packs.blueprints import (
    BlueprintModule,
    builtin_blueprint_modules,
    discover_blueprint_modules,
)
from akc_domain_packs.horizontal import horizontal_blueprint_modules, horizontal_blueprints
from akc_product_core.semantics import _DOMAIN_OBJECT_TYPES

_COMPONENTS = {
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


def _all_modules() -> tuple[BlueprintModule, ...]:
    return (*builtin_blueprint_modules(), *horizontal_blueprint_modules())


def _asset(module_id: str, path: str) -> dict[str, Any]:
    root = files("akc_domain_packs")
    for base in ("blueprints", "horizontal_modules"):
        node = root.joinpath(base, module_id, path)
        if node.is_file():
            loaded: dict[str, Any] = yaml.safe_load(node.read_text(encoding="utf-8"))
            return loaded
    raise AssertionError(f"{module_id}/{path} not found")


def test_both_horizontal_modules_validate_and_hash() -> None:
    modules = horizontal_blueprint_modules()
    assert {m.blueprint.id for m in modules} == {"creative-works", "team-workspace"}
    for module in modules:
        assert _COMPONENTS.issubset({a.path for a in module.assets})
        assert module.module_sha256.startswith("sha256:")


def test_horizontal_registry_composes_nine_without_replacing_builtins() -> None:
    registry = horizontal_blueprints()
    assert len(registry.blueprints) == 9
    builtin = builtin_blueprints()
    assert len(builtin.blueprints) == 7
    for blueprint_id, digest in builtin.module_sha256.items():
        assert registry.module_sha256[blueprint_id] == digest


def test_every_ontology_relation_is_inside_its_module_policy() -> None:
    for module in _all_modules():
        ontology = _asset(module.blueprint.id, "ontology/ontology.yaml")
        classes = set(ontology["classes"])
        policy = set(module.blueprint.relation_policy)
        assert "model_inferred" not in policy
        for relation in ontology["relations"]:
            assert relation["authority"] in policy, (module.blueprint.id, relation)
            assert relation["source"] in classes and relation["target"] in classes, relation


def test_every_module_declares_unresolved_and_quarantine_cases() -> None:
    for module in _all_modules():
        cases = _asset(module.blueprint.id, "tests/cases.yaml")["cases"]
        expected = {case["expected"] for case in cases}
        assert {"unresolved", "quarantine"} <= expected, module.blueprint.id


def test_selection_for_every_product_core_domain_is_unchanged() -> None:
    registry = horizontal_blueprints()
    for domain, object_types in _DOMAIN_OBJECT_TYPES.items():
        profile = ArchitectureProfile(
            domain=domain,
            object_types=object_types,
            user_goal="compile",
            corpus_size=10,
            temporal_structure="undated",
        )
        assert plan_architecture(profile, registry=registry) == plan_architecture(profile)


def test_requesting_creative_or_team_yields_its_plan() -> None:
    for blueprint_id in ("creative-works", "team-workspace"):
        profile = ArchitectureProfile(
            domain="mixed",
            object_types=("document",),
            user_goal="compile",
            corpus_size=1,
            temporal_structure="undated",
            requested_blueprint=blueprint_id,
        )
        plan = plan_architecture(profile, registry=horizontal_blueprints())
        assert plan.blueprint == blueprint_id
        assert plan.module_sha256 == horizontal_blueprints().module_sha256[blueprint_id]
        with pytest.raises(LookupError):
            plan_architecture(profile)


def test_horizontal_module_with_model_inferred_relation_policy_is_rejected(
    tmp_path: Path,
) -> None:
    source = files("akc_domain_packs").joinpath("horizontal_modules", "creative-works")
    target = tmp_path / "creative-works"
    shutil.copytree(str(source), target)
    module_yaml = target / "module.yaml"
    payload = yaml.safe_load(module_yaml.read_text(encoding="utf-8"))
    payload["relation_policy"] = ["model_inferred"]
    module_yaml.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="model-inferred"):
        discover_blueprint_modules(tmp_path)
