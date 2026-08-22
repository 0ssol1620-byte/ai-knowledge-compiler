"""Declarative knowledge blueprints and deterministic architecture planning."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.resources import files
from pathlib import PurePosixPath
from typing import Annotated, Any

import yaml
from pydantic import Field, field_validator, model_validator

from .registry import WireModel

_BLUEPRINT_ID = r"^[a-z][a-z0-9-]{2,79}$"
_VERSION = r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$"
_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,119}$"
_FORBIDDEN_KEYS = frozenset(
    {
        "code",
        "python",
        "shell",
        "command",
        "executable",
        "network",
        "url",
        "webhook",
        "plugin",
    }
)
_COMPONENT_FILES = {
    "ontology": "ontology.yaml",
    "schemas": "objects.schema.json",
    "prompts": "compiler.md",
    "templates": "views.yaml",
    "directory": "layout.yaml",
    "validators": "rules.yaml",
    "mappings": "canonical.yaml",
    "examples": "example.yaml",
    "tests": "cases.yaml",
    "migrations": "manifest.yaml",
}
_DECLARATIVE_SUFFIXES = frozenset({".json", ".md", ".ttl", ".yaml", ".yml"})
_EXECUTABLE_SUFFIXES = frozenset({".bat", ".cmd", ".com", ".exe", ".js", ".ps1", ".py", ".sh"})
_PROMPT_FORBIDDEN_MARKERS = (
    "```bash",
    "```cmd",
    "```powershell",
    "```python",
    "```sh",
    "http://",
    "https://",
)


class KnowledgeBlueprint(WireModel):
    id: Annotated[str, Field(pattern=_BLUEPRINT_ID)]
    version: Annotated[str, Field(pattern=_VERSION)]
    display_name: Annotated[str, Field(min_length=1, max_length=120)]
    domains: Annotated[tuple[str, ...], Field(min_length=1, max_length=20)]
    object_types: Annotated[tuple[str, ...], Field(min_length=1, max_length=30)]
    root_views: Annotated[tuple[str, ...], Field(min_length=1, max_length=12)]
    moc_templates: Annotated[tuple[str, ...], Field(min_length=1, max_length=20)]
    folder_depth: Annotated[int, Field(ge=1, le=5)]
    naming_policy: Annotated[str, Field(pattern=r"^(stable-title|stable-id-title|date-title)$")]
    source_preservation: bool = True
    relation_policy: Annotated[
        tuple[str, ...],
        Field(min_length=1, max_length=4),
    ] = ("source_explicit", "structured_derived", "rule_derived")
    validators: Annotated[tuple[str, ...], Field(min_length=1, max_length=20)]
    export_profiles: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]

    @field_validator(
        "domains",
        "object_types",
        "root_views",
        "moc_templates",
        "relation_policy",
        "validators",
        "export_profiles",
    )
    @classmethod
    def unique_safe_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("blueprint lists must be unique")
        if any(not item or len(item) > 120 for item in value):
            raise ValueError("blueprint list item is invalid")
        return value

    @field_validator("root_views", "moc_templates")
    @classmethod
    def portable_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        import re

        if any(re.fullmatch(_SAFE_NAME, item) is None for item in value):
            raise ValueError("blueprint folder and MOC names must be portable")
        return value

    @model_validator(mode="after")
    def enforce_verified_relation_policy(self) -> KnowledgeBlueprint:
        if "model_inferred" in self.relation_policy:
            raise ValueError("model-inferred relations cannot enter the verified graph")
        if not self.source_preservation:
            raise ValueError("built-in blueprints must preserve source material")
        return self


class BlueprintRegistry(WireModel):
    blueprints: tuple[KnowledgeBlueprint, ...]
    module_sha256: dict[str, Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def unique_ids(self) -> BlueprintRegistry:
        ids = [blueprint.id for blueprint in self.blueprints]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("the blueprint registry requires unique module ids")
        if self.module_sha256 and set(self.module_sha256) != set(ids):
            raise ValueError("module hashes must cover the complete blueprint registry")
        return self

    def get(self, blueprint_id: str) -> KnowledgeBlueprint:
        for blueprint in self.blueprints:
            if blueprint.id == blueprint_id:
                return blueprint
        raise LookupError(f"unknown knowledge blueprint: {blueprint_id}")


class ArchitectureProfile(WireModel):
    domain: Annotated[str, Field(min_length=1, max_length=120)]
    object_types: Annotated[tuple[str, ...], Field(min_length=1, max_length=30)]
    user_goal: Annotated[str, Field(min_length=1, max_length=500)]
    corpus_size: Annotated[int, Field(ge=1)]
    temporal_structure: Annotated[str, Field(min_length=1, max_length=120)]
    existing_folders: Annotated[tuple[str, ...], Field(max_length=500)] = ()
    requested_blueprint: str | None = None

    @field_validator("object_types", "existing_folders")
    @classmethod
    def unique_profile_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("architecture profile values must be unique")
        return value


class ArchitecturePlan(WireModel):
    blueprint: str
    blueprint_version: str
    root_views: tuple[str, ...]
    mocs: tuple[str, ...]
    folder_paths: tuple[str, ...]
    folder_depth: Annotated[int, Field(ge=1, le=5)]
    naming_policy: str
    source_preservation: bool
    relation_policy: tuple[str, ...]
    preserved_existing_folders: bool
    warnings: tuple[str, ...] = ()
    module_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")] | None = None
    plan_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class BlueprintAsset(WireModel):
    path: Annotated[str, Field(min_length=3, max_length=240)]
    media_type: Annotated[
        str,
        Field(pattern=r"^(application/json|application/yaml|text/markdown|text/turtle)$"),
    ]
    size_bytes: Annotated[int, Field(ge=1, le=256 * 1024)]
    sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class BlueprintModule(WireModel):
    blueprint: KnowledgeBlueprint
    assets: Annotated[tuple[BlueprintAsset, ...], Field(min_length=10, max_length=128)]
    module_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def complete_and_unique_assets(self) -> BlueprintModule:
        paths = [asset.path for asset in self.assets]
        if len(paths) != len(set(paths)):
            raise ValueError("blueprint module asset paths must be unique")
        expected = {f"{directory}/{filename}" for directory, filename in _COMPONENT_FILES.items()}
        if not expected.issubset(paths):
            raise ValueError("blueprint module is missing required declarative assets")
        return self


def _reject_forbidden_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in _FORBIDDEN_KEYS:
                raise ValueError(f"blueprint contains forbidden executable key: {key}")
            _reject_forbidden_keys(child)
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden_keys(child)


def validate_blueprint_payload(payload: dict[str, Any]) -> KnowledgeBlueprint:
    _reject_forbidden_keys(payload)
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if not canonical or len(canonical) > 128 * 1024:
        raise ValueError("blueprint payload exceeds the declarative size boundary")
    return KnowledgeBlueprint.model_validate(payload)


def _media_type(suffix: str) -> str:
    return {
        ".json": "application/json",
        ".md": "text/markdown",
        ".ttl": "text/turtle",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
    }[suffix]


def _walk_files(directory: Any, prefix: str = "") -> list[tuple[str, Any]]:
    discovered: list[tuple[str, Any]] = []
    for child in sorted(directory.iterdir(), key=lambda item: item.name):
        relative = f"{prefix}/{child.name}" if prefix else child.name
        if child.is_dir():
            discovered.extend(_walk_files(child, relative))
        elif child.is_file():
            discovered.append((relative, child))
        else:
            raise ValueError(f"unsupported blueprint module entry: {relative}")
    return discovered


def _load_declarative_asset(path: str, raw: bytes, blueprint_id: str) -> None:
    suffix = PurePosixPath(path).suffix.casefold()
    if suffix in _EXECUTABLE_SUFFIXES or suffix not in _DECLARATIVE_SUFFIXES:
        raise ValueError(f"non-declarative blueprint module asset: {path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"blueprint asset must be UTF-8 text: {path}") from exc
    if suffix == ".json":
        payload = json.loads(text)
        _reject_forbidden_keys(payload)
        if not isinstance(payload, dict):
            raise ValueError(f"blueprint JSON asset must be an object: {path}")
    elif suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
        _reject_forbidden_keys(payload)
        if not isinstance(payload, dict):
            raise ValueError(f"blueprint YAML asset must be an object: {path}")
    elif suffix == ".md":
        folded = text.casefold()
        if any(marker in folded for marker in _PROMPT_FORBIDDEN_MARKERS):
            raise ValueError(f"prompt asset contains executable or network content: {path}")
        if not text.startswith("---\n"):
            raise ValueError(f"prompt asset requires declarative YAML front matter: {path}")
        _, front_matter, _ = text.split("---", maxsplit=2)
        payload = yaml.safe_load(front_matter)
        _reject_forbidden_keys(payload)
        if not isinstance(payload, dict):
            raise ValueError(f"prompt front matter must be an object: {path}")
    else:
        payload = {"blueprint": blueprint_id}
    declared_blueprint = payload.get("blueprint")
    if declared_blueprint != blueprint_id:
        raise ValueError(f"blueprint asset identity mismatch: {path}")


def validate_blueprint_module(directory: Any) -> BlueprintModule:
    module_file = directory.joinpath("module.yaml")
    if not module_file.is_file():
        raise ValueError("blueprint module is missing module.yaml")
    module_raw = module_file.read_bytes()
    if not module_raw or len(module_raw) > 128 * 1024:
        raise ValueError("blueprint module.yaml exceeds the declarative size boundary")
    payload = yaml.safe_load(module_raw)
    if not isinstance(payload, dict):
        raise ValueError("blueprint module.yaml root must be an object")
    blueprint = validate_blueprint_payload(payload)
    if blueprint.id != directory.name:
        raise ValueError("blueprint module directory and declared id do not match")

    for component, filename in _COMPONENT_FILES.items():
        component_dir = directory.joinpath(component)
        if not component_dir.is_dir() or not component_dir.joinpath(filename).is_file():
            raise ValueError(f"blueprint module is missing {component}/{filename}")

    assets: list[BlueprintAsset] = []
    total_size = len(module_raw)
    digest_material: list[bytes] = [b"module.yaml\0", module_raw]
    for path, asset in _walk_files(directory):
        if path == "module.yaml":
            continue
        raw = asset.read_bytes()
        if not raw or len(raw) > 256 * 1024:
            raise ValueError(f"blueprint module asset has invalid size: {path}")
        total_size += len(raw)
        if total_size > 2 * 1024 * 1024:
            raise ValueError("blueprint module exceeds the 2 MiB declarative boundary")
        _load_declarative_asset(path, raw, blueprint.id)
        suffix = PurePosixPath(path).suffix.casefold()
        digest = hashlib.sha256(raw).hexdigest()
        assets.append(
            BlueprintAsset(
                path=path,
                media_type=_media_type(suffix),
                size_bytes=len(raw),
                sha256=f"sha256:{digest}",
            )
        )
        digest_material.extend((path.encode("utf-8"), b"\0", raw))
    module_digest = hashlib.sha256(b"".join(digest_material)).hexdigest()
    return BlueprintModule(
        blueprint=blueprint,
        assets=tuple(assets),
        module_sha256=f"sha256:{module_digest}",
    )


@lru_cache(maxsize=1)
def builtin_blueprint_modules() -> tuple[BlueprintModule, ...]:
    root = files("akc_domain_packs").joinpath("blueprints")
    loaded: list[BlueprintModule] = []
    for directory in sorted(root.iterdir(), key=lambda item: item.name):
        if not directory.is_dir():
            continue
        try:
            loaded.append(validate_blueprint_module(directory))
        except (OSError, json.JSONDecodeError, yaml.YAMLError, ValueError, TypeError) as exc:
            raise RuntimeError(f"invalid blueprint module: {directory.name}") from exc
    if len(loaded) != 7:
        raise RuntimeError("the built-in blueprint module registry must contain seven modules")
    return tuple(loaded)


def discover_blueprint_modules(root: Any) -> tuple[BlueprintModule, ...]:
    """Validate a bounded ``modules/{blueprint}`` drop-in directory fail closed."""

    if not root.is_dir():
        raise ValueError("blueprint module root must be a directory")
    entries = sorted(root.iterdir(), key=lambda item: item.name)
    if not entries or len(entries) > 100:
        raise ValueError("blueprint module root must contain between 1 and 100 modules")
    modules: list[BlueprintModule] = []
    for entry in entries:
        if not entry.is_dir():
            raise ValueError(f"unexpected file in blueprint module root: {entry.name}")
        modules.append(validate_blueprint_module(entry))
    ids = [module.blueprint.id for module in modules]
    if len(ids) != len(set(ids)):
        raise ValueError("blueprint module ids must be unique")
    return tuple(modules)


def registry_from_modules(
    modules: tuple[BlueprintModule, ...],
    *,
    include_builtins: bool = True,
) -> BlueprintRegistry:
    """Compose verified module receipts without permitting built-in replacement."""

    combined = (*builtin_blueprint_modules(), *modules) if include_builtins else modules
    ids = [module.blueprint.id for module in combined]
    if len(ids) != len(set(ids)):
        raise ValueError("drop-in modules cannot replace an existing blueprint id")
    return BlueprintRegistry(
        blueprints=tuple(module.blueprint for module in combined),
        module_sha256={module.blueprint.id: module.module_sha256 for module in combined},
    )


@lru_cache(maxsize=1)
def builtin_blueprints() -> BlueprintRegistry:
    modules = builtin_blueprint_modules()
    return BlueprintRegistry(
        blueprints=tuple(module.blueprint for module in modules),
        module_sha256={module.blueprint.id: module.module_sha256 for module in modules},
    )


def _select_blueprint(
    profile: ArchitectureProfile,
    registry: BlueprintRegistry,
) -> KnowledgeBlueprint:
    if profile.requested_blueprint is not None:
        return registry.get(profile.requested_blueprint)
    domain = profile.domain.casefold()
    object_types = {item.casefold() for item in profile.object_types}
    ranked = sorted(
        registry.blueprints,
        key=lambda blueprint: (
            -(
                (2 if domain in {item.casefold() for item in blueprint.domains} else 0)
                + len(object_types.intersection(item.casefold() for item in blueprint.object_types))
            ),
            blueprint.id,
        ),
    )
    return ranked[0]


def plan_architecture(
    profile: ArchitectureProfile,
    *,
    registry: BlueprintRegistry | None = None,
) -> ArchitecturePlan:
    selected = _select_blueprint(profile, registry or builtin_blueprints())
    root_views = selected.root_views
    mocs = tuple(
        f"{name} MOC" if not name.endswith("MOC") else name for name in selected.moc_templates
    )
    folder_paths = tuple(["Sources", *root_views, "MOCs", "Evidence", "Packages"])
    warnings = ("existing_folder_merge_requires_preview",) if profile.existing_folders else ()
    unsigned = {
        "blueprint": selected.id,
        "blueprint_version": selected.version,
        "root_views": root_views,
        "mocs": mocs,
        "folder_paths": folder_paths,
        "folder_depth": selected.folder_depth,
        "naming_policy": selected.naming_policy,
        "source_preservation": selected.source_preservation,
        "relation_policy": selected.relation_policy,
        "preserved_existing_folders": bool(profile.existing_folders),
        "warnings": warnings,
        "module_sha256": (registry or builtin_blueprints()).module_sha256.get(selected.id),
    }
    digest = hashlib.sha256(
        json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return ArchitecturePlan(**unsigned, plan_sha256=f"sha256:{digest}")


__all__ = [
    "ArchitecturePlan",
    "ArchitectureProfile",
    "BlueprintAsset",
    "BlueprintModule",
    "BlueprintRegistry",
    "KnowledgeBlueprint",
    "builtin_blueprint_modules",
    "builtin_blueprints",
    "discover_blueprint_modules",
    "plan_architecture",
    "registry_from_modules",
    "validate_blueprint_module",
    "validate_blueprint_payload",
]
