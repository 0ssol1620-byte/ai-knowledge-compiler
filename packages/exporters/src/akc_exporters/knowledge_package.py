"""Signed, deterministic, round-trip-verifiable Knowledge Package."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, TypedDict, runtime_checkable

from akc_cir import CanonicalKnowledgeModel, KnowledgeObjectKind, canonical_json
from akc_security import safe_relative_path
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .package import deterministic_zip

_REQUIRED_ROOTS = (
    "source",
    "canonical",
    "obsidian",
    "ontology",
    "graph",
    "rag",
    "provenance",
    "validation",
)

_REQUIRED_PROFILE_FILES = {
    "canonical": frozenset({"model.json"}),
    "obsidian": frozenset({"Home.md"}),
    "ontology": frozenset(
        {
            "knowledge.ttl",
            "knowledge.owl",
            "knowledge.jsonld",
            "knowledge.skos.ttl",
            "shapes.shacl.ttl",
            "vocabulary.md",
            "provenance.jsonld",
        }
    ),
    "graph": frozenset(
        {
            "nodes.csv",
            "relationships.csv",
            "constraints.cypher",
            "indexes.cypher",
            "import.cypher",
        }
    ),
    "rag": frozenset(
        {
            "documents.jsonl",
            "chunks.jsonl",
            "metadata.jsonl",
            "evidence.jsonl",
            "retrieval-profile.json",
        }
    ),
    "provenance": frozenset({"activities.jsonl"}),
    "validation": frozenset({"report.json", "round-trip.json"}),
}
_SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


class KnowledgePackageError(ValueError):
    """Package structure, digest, or signature is invalid."""


class _SemanticModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SemanticAssetManifest(_SemanticModel):
    """One declarative blueprint asset bound into the package manifest."""

    path: Annotated[str, Field(min_length=3, max_length=240)]
    media_type: Annotated[str, Field(min_length=3, max_length=120)]
    size_bytes: Annotated[int, Field(ge=1, le=256 * 1024)]
    sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class SemanticBlueprintManifest(_SemanticModel):
    """Immutable receipt for a declarative Knowledge Blueprint module."""

    blueprint_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,79}$")]
    blueprint_version: Annotated[str, Field(pattern=r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")]
    module_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    assets: Annotated[tuple[SemanticAssetManifest, ...], Field(min_length=1, max_length=128)]
    prompt_assets: Annotated[tuple[SemanticAssetManifest, ...], Field(min_length=1)]
    validator_assets: Annotated[tuple[SemanticAssetManifest, ...], Field(min_length=1)]
    template_assets: Annotated[tuple[SemanticAssetManifest, ...], Field(min_length=1)]
    validator_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=20)]
    template_ids: Annotated[tuple[str, ...], Field(min_length=1, max_length=20)]
    export_profiles: Annotated[tuple[str, ...], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def bind_components_to_assets(self) -> SemanticBlueprintManifest:
        paths = [asset.path for asset in self.assets]
        if len(paths) != len(set(paths)):
            raise ValueError("semantic blueprint asset paths must be unique")
        declared = {(asset.path, asset.sha256) for asset in self.assets}
        for component, prefix in (
            (self.prompt_assets, "prompts/"),
            (self.validator_assets, "validators/"),
            (self.template_assets, "templates/"),
        ):
            if any((asset.path, asset.sha256) not in declared for asset in component):
                raise ValueError("semantic blueprint component is not present in assets")
            if any(not asset.path.startswith(prefix) for asset in component):
                raise ValueError("semantic blueprint component path is misclassified")
        for values in (self.validator_ids, self.template_ids, self.export_profiles):
            if len(values) != len(set(values)):
                raise ValueError("semantic blueprint identifiers must be unique")
        return self


class KnowledgePackageSemanticProfile(_SemanticModel):
    """Manifest-level proof that canonical semantics survived package export."""

    schema_version: Literal["akc.knowledge-package.semantic.v1"] = (
        "akc.knowledge-package.semantic.v1"
    )
    canonical_model_path: Literal["canonical/model.json"] = "canonical/model.json"
    canonical_model_schema_version: Annotated[str, Field(min_length=1, max_length=80)]
    canonical_model_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    object_count: Annotated[int, Field(ge=1)]
    object_counts: dict[str, Annotated[int, Field(ge=0)]]
    blueprint_modules: tuple[SemanticBlueprintManifest, ...] = ()

    @model_validator(mode="after")
    def validate_semantic_counts(self) -> KnowledgePackageSemanticProfile:
        if not self.object_counts or sum(self.object_counts.values()) != self.object_count:
            raise ValueError("semantic object counts must cover the canonical model")
        blueprint_ids = [module.blueprint_id for module in self.blueprint_modules]
        if len(blueprint_ids) != len(set(blueprint_ids)):
            raise ValueError("semantic blueprint module IDs must be unique")
        return self


class _ManifestEntry(TypedDict):
    path: str
    sha256: str
    size_bytes: int


@runtime_checkable
class PackageSigner(Protocol):
    signer_id: str
    algorithm: str

    def sign(self, payload: bytes) -> bytes: ...


@runtime_checkable
class PackageVerifier(Protocol):
    signer_id: str
    algorithm: str

    def verify(self, signature: bytes, payload: bytes) -> None: ...


@dataclass(frozen=True, slots=True)
class Ed25519Signer:
    signer_id: str
    _key: Ed25519PrivateKey
    algorithm: str = "Ed25519"

    @classmethod
    def from_pem(cls, *, signer_id: str, private_key_pem: bytes) -> Ed25519Signer:
        loaded = serialization.load_pem_private_key(private_key_pem, password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            raise KnowledgePackageError("package signer must use Ed25519")
        return cls(signer_id=signer_id, _key=loaded)

    def sign(self, payload: bytes) -> bytes:
        return self._key.sign(payload)

    def public_verifier(self) -> Ed25519Verifier:
        return Ed25519Verifier(signer_id=self.signer_id, _key=self._key.public_key())


@dataclass(frozen=True, slots=True)
class Ed25519Verifier:
    signer_id: str
    _key: Ed25519PublicKey
    algorithm: str = "Ed25519"

    @classmethod
    def from_pem(cls, *, signer_id: str, public_key_pem: bytes) -> Ed25519Verifier:
        loaded = serialization.load_pem_public_key(public_key_pem)
        if not isinstance(loaded, Ed25519PublicKey):
            raise KnowledgePackageError("package verifier must use Ed25519")
        return cls(signer_id=signer_id, _key=loaded)

    def verify(self, signature: bytes, payload: bytes) -> None:
        try:
            self._key.verify(signature, payload)
        except InvalidSignature as exc:
            raise KnowledgePackageError("knowledge package signature is invalid") from exc


@dataclass(frozen=True, slots=True)
class KnowledgePackageReceipt:
    package_sha256: str
    manifest_sha256: str
    file_count: int
    signed: bool
    signature_status: str
    signer_id: str | None
    semantic_model_sha256: str | None = None
    semantic_round_trip: bool = False


@dataclass(frozen=True, slots=True)
class ImportedKnowledgePackage:
    files: Mapping[str, bytes]
    receipt: KnowledgePackageReceipt
    manifest: Mapping[str, object]
    semantic_model: CanonicalKnowledgeModel | None = None
    semantic_profile: KnowledgePackageSemanticProfile | None = None


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def canonical_knowledge_model_bytes(model: CanonicalKnowledgeModel) -> bytes:
    """Serialize the authoritative semantic model in its only package form."""

    return (canonical_json(model) + "\n").encode("utf-8")


def _validate_blueprint_bindings(
    model: CanonicalKnowledgeModel,
    modules: tuple[SemanticBlueprintManifest, ...],
) -> None:
    bound = [
        item
        for item in model.objects
        if item.kind is KnowledgeObjectKind.ASSET
        and item.payload.get("semantic_role") == "knowledge_blueprint_module"
    ]
    if len(bound) != len(modules):
        raise KnowledgePackageError(
            "canonical model and semantic blueprint manifest coverage differ"
        )
    expected = {module.blueprint_id: module.model_dump(mode="json") for module in modules}
    actual: dict[str, object] = {}
    for item in bound:
        manifest = item.payload.get("manifest")
        if not isinstance(manifest, dict):
            raise KnowledgePackageError("canonical blueprint binding is malformed")
        blueprint_id = manifest.get("blueprint_id")
        if not isinstance(blueprint_id, str) or blueprint_id in actual:
            raise KnowledgePackageError("canonical blueprint binding identity is invalid")
        actual[blueprint_id] = manifest
    if actual != expected:
        raise KnowledgePackageError("canonical blueprint binding differs from the manifest")


def _validate_architecture_plan_binding(
    model: CanonicalKnowledgeModel,
    architecture_plan_sha256: str,
) -> None:
    roots = [item for item in model.objects if item.kind is KnowledgeObjectKind.COLLECTION]
    if len(roots) != 1:
        raise KnowledgePackageError(
            "semantic package requires exactly one canonical collection root"
        )
    architecture_plan = roots[0].payload.get("architecture_plan")
    bound_sha256 = roots[0].payload.get("architecture_plan_sha256")
    if not isinstance(architecture_plan, dict) or not isinstance(bound_sha256, str):
        raise KnowledgePackageError(
            "canonical collection root is missing its architecture plan binding"
        )
    calculated_sha256 = (
        "sha256:" + hashlib.sha256(canonical_json(architecture_plan).encode("utf-8")).hexdigest()
    )
    if bound_sha256 != calculated_sha256 or architecture_plan_sha256 != calculated_sha256:
        raise KnowledgePackageError(
            "architecture plan digest differs from the canonical collection root"
        )


def knowledge_package_semantic_profile(
    model: CanonicalKnowledgeModel,
    *,
    blueprint_modules: tuple[SemanticBlueprintManifest, ...] = (),
) -> KnowledgePackageSemanticProfile:
    """Derive a non-forgeable semantic profile from a validated canonical model."""

    _validate_blueprint_bindings(model, blueprint_modules)
    payload = canonical_knowledge_model_bytes(model)
    counts: dict[str, int] = {}
    for item in model.objects:
        counts[item.kind.value] = counts.get(item.kind.value, 0) + 1
    return KnowledgePackageSemanticProfile(
        canonical_model_schema_version=model.schema_version,
        canonical_model_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        object_count=len(model.objects),
        object_counts=dict(sorted(counts.items())),
        blueprint_modules=blueprint_modules,
    )


def _normalize_payload(groups: Mapping[str, Mapping[str, bytes]]) -> dict[str, bytes]:
    missing = [root for root in _REQUIRED_ROOTS if not groups.get(root)]
    if missing:
        raise KnowledgePackageError(f"knowledge package groups are missing: {', '.join(missing)}")
    unknown = set(groups) - set(_REQUIRED_ROOTS)
    if unknown:
        raise KnowledgePackageError(f"knowledge package groups are unknown: {sorted(unknown)}")
    for root, required in _REQUIRED_PROFILE_FILES.items():
        missing_files = required - set(groups[root])
        if missing_files:
            raise KnowledgePackageError(
                f"knowledge package {root} profile is incomplete: {sorted(missing_files)}"
            )
    payload: dict[str, bytes] = {}
    folded: set[str] = set()
    for root in _REQUIRED_ROOTS:
        for relative_path, content in groups[root].items():
            relative = safe_relative_path(relative_path)
            path = safe_relative_path(f"{root}/{relative}")
            if path.casefold() in folded:
                raise KnowledgePackageError("case-insensitive package path collision")
            folded.add(path.casefold())
            payload[path] = bytes(content)
    return payload


def build_knowledge_package(
    groups: Mapping[str, Mapping[str, bytes]],
    *,
    collection_id: str,
    architecture_plan_sha256: str,
    signer: PackageSigner | None = None,
    semantic_model: CanonicalKnowledgeModel | None = None,
    blueprint_modules: tuple[SemanticBlueprintManifest, ...] = (),
) -> tuple[bytes, KnowledgePackageReceipt]:
    if not collection_id.strip() or len(collection_id) > 240:
        raise KnowledgePackageError("collection_id must be a bounded non-empty identifier")
    if _SHA256_ID.fullmatch(architecture_plan_sha256) is None:
        raise KnowledgePackageError("architecture plan digest must be canonical SHA-256")
    payload = _normalize_payload(groups)
    semantic_profile: KnowledgePackageSemanticProfile | None = None
    if semantic_model is None:
        if blueprint_modules:
            raise KnowledgePackageError(
                "semantic blueprint manifests require a canonical knowledge model"
            )
    else:
        if semantic_model.collection_id != collection_id:
            raise KnowledgePackageError("canonical model collection scope differs from package")
        _validate_architecture_plan_binding(
            semantic_model,
            architecture_plan_sha256,
        )
        expected_canonical = canonical_knowledge_model_bytes(semantic_model)
        if payload.get("canonical/model.json") != expected_canonical:
            raise KnowledgePackageError(
                "canonical/model.json differs from the authoritative semantic model"
            )
        semantic_profile = knowledge_package_semantic_profile(
            semantic_model,
            blueprint_modules=blueprint_modules,
        )
    readme = (
        b"# Structara Knowledge Package\n\n"
        b"Open `obsidian/Home.md` to begin. The canonical model is the source of truth; "
        b"all other directories are portable renderers with source evidence. Verify "
        b"`manifest.json`, `checksums.sha256`, and `signature/` before import.\n"
    )
    signed_files = {**payload, "README.md": readme}
    entries: list[_ManifestEntry] = [
        {
            "path": path,
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        for path, content in sorted(signed_files.items())
    ]
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "package_type": "structara-knowledge-package",
        "collection_id": collection_id,
        "architecture_plan_sha256": architecture_plan_sha256,
        "roots": list(_REQUIRED_ROOTS),
        "files": entries,
        "signature": {
            "status": "signed" if signer is not None else "external_signer_required",
            "algorithm": signer.algorithm if signer is not None else None,
            "signer_id": signer.signer_id if signer is not None else None,
            "signature_path": "signature/manifest.ed25519" if signer is not None else None,
            "signer_record_path": "signature/signer.json" if signer is not None else None,
        },
    }
    if semantic_profile is not None:
        manifest["semantic_profile"] = semantic_profile.model_dump(mode="json")
    manifest_bytes = _canonical_json(manifest)
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    checksums = (
        "".join(
            f"{entry['sha256'].removeprefix('sha256:')}  {entry['path']}\n" for entry in entries
        )
        + f"{manifest_digest}  manifest.json\n"
    ).encode("utf-8")
    package_files = {
        **signed_files,
        "checksums.sha256": checksums,
        "manifest.json": manifest_bytes,
    }
    if signer is not None:
        signature = signer.sign(manifest_bytes)
        package_files["signature/manifest.ed25519"] = base64.b64encode(signature) + b"\n"
        package_files["signature/signer.json"] = _canonical_json(
            {"algorithm": signer.algorithm, "signer_id": signer.signer_id}
        )
    package = deterministic_zip(package_files)
    receipt = KnowledgePackageReceipt(
        package_sha256="sha256:" + hashlib.sha256(package).hexdigest(),
        manifest_sha256=f"sha256:{manifest_digest}",
        file_count=len(payload),
        signed=signer is not None,
        signature_status="signed" if signer is not None else "external_signer_required",
        signer_id=signer.signer_id if signer is not None else None,
        semantic_model_sha256=(
            semantic_profile.canonical_model_sha256 if semantic_profile is not None else None
        ),
        semantic_round_trip=semantic_profile is not None,
    )
    return package, receipt


def import_knowledge_package(
    package: bytes,
    *,
    verifier: PackageVerifier | None = None,
    require_signature: bool = False,
    require_semantic_profile: bool = False,
) -> ImportedKnowledgePackage:
    try:
        with zipfile.ZipFile(io.BytesIO(package), "r") as archive:
            names = archive.namelist()
            if len(names) != len({name.casefold() for name in names}):
                raise KnowledgePackageError("package contains duplicate paths")
            files = {safe_relative_path(name): archive.read(name) for name in names}
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        if isinstance(exc, KnowledgePackageError):
            raise
        raise KnowledgePackageError("knowledge package ZIP is invalid") from exc
    try:
        manifest_bytes = files["manifest.json"]
        manifest = json.loads(manifest_bytes)
        entries = manifest["files"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise KnowledgePackageError("knowledge package manifest is invalid") from exc
    if not isinstance(entries, list):
        raise KnowledgePackageError("knowledge package file manifest is invalid")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "1.0"
        or manifest.get("package_type") != "structara-knowledge-package"
        or manifest.get("roots") != list(_REQUIRED_ROOTS)
        or not isinstance(manifest.get("collection_id"), str)
        or not str(manifest["collection_id"]).strip()
        or _SHA256_ID.fullmatch(str(manifest.get("architecture_plan_sha256", ""))) is None
    ):
        raise KnowledgePackageError("knowledge package identity contract is invalid")
    expected_paths: set[str] = set()
    expected_folded_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise KnowledgePackageError("knowledge package manifest entry is invalid")
        path = safe_relative_path(str(entry.get("path", "")))
        if path.casefold() in expected_folded_paths:
            raise KnowledgePackageError("knowledge package manifest contains duplicate paths")
        expected_folded_paths.add(path.casefold())
        expected_paths.add(path)
        content = files.get(path)
        expected_digest = str(entry.get("sha256", ""))
        if (
            content is None
            or _SHA256_ID.fullmatch(expected_digest) is None
            or "sha256:" + hashlib.sha256(content).hexdigest() != expected_digest
            or entry.get("size_bytes") != len(content)
        ):
            raise KnowledgePackageError(f"knowledge package hash mismatch: {path}")
    expected_checksums = (
        "".join(
            f"{str(entry['sha256']).removeprefix('sha256:')}  {entry['path']}\n"
            for entry in entries
        )
        + f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json\n"
    ).encode("utf-8")
    if files.get("checksums.sha256") != expected_checksums:
        raise KnowledgePackageError("knowledge package checksum ledger is invalid")
    roots_present = all(
        any(path.startswith(f"{root}/") for path in expected_paths) for root in _REQUIRED_ROOTS
    )
    if not roots_present:
        raise KnowledgePackageError("knowledge package required root is empty")
    for root, required in _REQUIRED_PROFILE_FILES.items():
        present = {
            path.removeprefix(f"{root}/") for path in expected_paths if path.startswith(f"{root}/")
        }
        if not required.issubset(present):
            raise KnowledgePackageError(f"knowledge package {root} profile is incomplete")
    semantic_model: CanonicalKnowledgeModel | None = None
    semantic_profile: KnowledgePackageSemanticProfile | None = None
    raw_semantic_profile = manifest.get("semantic_profile")
    if raw_semantic_profile is None:
        if require_semantic_profile:
            raise KnowledgePackageError("knowledge package semantic profile is required")
    else:
        try:
            semantic_profile = KnowledgePackageSemanticProfile.model_validate(raw_semantic_profile)
            canonical_payload = files[semantic_profile.canonical_model_path]
            semantic_model = CanonicalKnowledgeModel.model_validate_json(canonical_payload)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise KnowledgePackageError("knowledge package semantic profile is invalid") from exc
        if semantic_model.collection_id != manifest["collection_id"]:
            raise KnowledgePackageError("semantic model collection scope differs from package")
        if canonical_knowledge_model_bytes(semantic_model) != canonical_payload:
            raise KnowledgePackageError("semantic model is not canonically serialized")
        _validate_architecture_plan_binding(
            semantic_model,
            str(manifest["architecture_plan_sha256"]),
        )
        expected_semantic_profile = knowledge_package_semantic_profile(
            semantic_model,
            blueprint_modules=semantic_profile.blueprint_modules,
        )
        if expected_semantic_profile != semantic_profile:
            raise KnowledgePackageError("semantic model profile does not match canonical content")
    signed = "signature/manifest.ed25519" in files and "signature/signer.json" in files
    allowed_support_files = {"manifest.json", "checksums.sha256"}
    if signed:
        allowed_support_files.update({"signature/manifest.ed25519", "signature/signer.json"})
    if set(files) != expected_paths | allowed_support_files:
        raise KnowledgePackageError("knowledge package contains unmanifested files")
    signature_meta = manifest.get("signature")
    if require_signature and not signed:
        raise KnowledgePackageError("production import requires a signed package")
    signer_id: str | None = None
    if signed:
        if verifier is None:
            raise KnowledgePackageError("signed package requires an approved verifier")
        try:
            signer_record = json.loads(files["signature/signer.json"])
            signer_id = str(signer_record["signer_id"])
            algorithm = str(signer_record["algorithm"])
            signature = base64.b64decode(files["signature/manifest.ed25519"].strip(), validate=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise KnowledgePackageError("package signer record is invalid") from exc
        if signer_id != verifier.signer_id or algorithm != verifier.algorithm:
            raise KnowledgePackageError("package signer identity is not approved")
        if not isinstance(signature_meta, dict) or signature_meta.get("status") != "signed":
            raise KnowledgePackageError("package signature manifest is inconsistent")
        verifier.verify(signature, manifest_bytes)
    receipt = KnowledgePackageReceipt(
        package_sha256="sha256:" + hashlib.sha256(package).hexdigest(),
        manifest_sha256="sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        file_count=len(expected_paths - {"README.md"}),
        signed=signed,
        signature_status="signed" if signed else "external_signer_required",
        signer_id=signer_id,
        semantic_model_sha256=(
            semantic_profile.canonical_model_sha256 if semantic_profile is not None else None
        ),
        semantic_round_trip=semantic_profile is not None,
    )
    return ImportedKnowledgePackage(
        files={path: files[path] for path in sorted(expected_paths)},
        receipt=receipt,
        manifest=manifest,
        semantic_model=semantic_model,
        semantic_profile=semantic_profile,
    )


__all__ = [
    "Ed25519Signer",
    "Ed25519Verifier",
    "ImportedKnowledgePackage",
    "KnowledgePackageError",
    "KnowledgePackageReceipt",
    "KnowledgePackageSemanticProfile",
    "PackageSigner",
    "PackageVerifier",
    "SemanticAssetManifest",
    "SemanticBlueprintManifest",
    "build_knowledge_package",
    "canonical_knowledge_model_bytes",
    "import_knowledge_package",
    "knowledge_package_semantic_profile",
]
