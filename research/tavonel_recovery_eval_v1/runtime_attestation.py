#!/usr/bin/env python3
"""Build and verify Paper 2 research-runtime attestations without secrets.

The attestation binds reproducibility-relevant public/non-secret artifacts.  It
must never contain provider credentials, SSH private-key material, or raw secret
file paths.  Qualification receipts may record provider-observed hardware and
cost, but they remain DEVELOPMENT_ONLY until the fresh protocol is frozen.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "tavonel.recovery.research_runtime_attestation.v1"
DEVELOPMENT_ONLY = "DEVELOPMENT_RUNTIME_QUALIFICATION_ONLY"
_SECRET_MARKERS = (
    "secret",
    "token",
    "password",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "authorization",
)


class RuntimeAttestationRefused(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def is_sha(value: str) -> bool:
    return value.startswith("sha256:") and len(value) == 71


def reject_secret_like(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            folded = str(key).casefold()
            if any(marker in folded for marker in _SECRET_MARKERS):
                raise RuntimeAttestationRefused(f"secret-like field forbidden: {path}.{key}")
            reject_secret_like(nested, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            reject_secret_like(nested, path=f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class FilePin:
    role: str
    path: str
    sha256: str

    def validate(self, repository_root: Path) -> None:
        if not self.role or not self.path:
            raise RuntimeAttestationRefused("file pin role/path cannot be empty")
        candidate = Path(self.path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise RuntimeAttestationRefused(f"unsafe repository-relative path: {self.path}")
        resolved = (repository_root / candidate).resolve()
        try:
            resolved.relative_to(repository_root.resolve())
        except ValueError as error:
            raise RuntimeAttestationRefused(f"file pin escapes repository: {self.path}") from error
        if not resolved.is_file():
            raise RuntimeAttestationRefused(f"pinned file absent: {self.path}")
        if not is_sha(self.sha256):
            raise RuntimeAttestationRefused(f"invalid sha256 pin: {self.path}")
        observed = sha256_file(resolved)
        if observed != self.sha256:
            raise RuntimeAttestationRefused(f"pinned file digest mismatch: {self.path}")


@dataclass(frozen=True, slots=True)
class RuntimeAttestation:
    role: str
    model_id: str
    model_revision: str
    base_image: str
    base_image_digest: str
    model_artifact_digest: str
    prompt_schema_digest: str
    file_pins: tuple[FilePin, ...]
    qualification_input_manifest_digest: str
    observed_runtime: Mapping[str, Any]
    evidence_class: str = DEVELOPMENT_ONLY

    def validate(self, repository_root: Path) -> None:
        if self.evidence_class != DEVELOPMENT_ONLY:
            raise RuntimeAttestationRefused("runtime qualification must remain development-only")
        if not all((self.role, self.model_id, self.model_revision, self.base_image)):
            raise RuntimeAttestationRefused("runtime identity fields are incomplete")
        for name, value in (
            ("base_image_digest", self.base_image_digest),
            ("model_artifact_digest", self.model_artifact_digest),
            ("prompt_schema_digest", self.prompt_schema_digest),
            ("qualification_input_manifest_digest", self.qualification_input_manifest_digest),
        ):
            if not is_sha(value):
                raise RuntimeAttestationRefused(f"{name} is not a full sha256 pin")
        if not self.file_pins:
            raise RuntimeAttestationRefused("runtime attestation must bind implementation files")
        for pin in self.file_pins:
            pin.validate(repository_root)
        reject_secret_like(self.observed_runtime)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "evidence_class": self.evidence_class,
            "role": self.role,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "base_image": self.base_image,
            "base_image_digest": self.base_image_digest,
            "model_artifact_digest": self.model_artifact_digest,
            "prompt_schema_digest": self.prompt_schema_digest,
            "qualification_input_manifest_digest": self.qualification_input_manifest_digest,
            "file_pins": [
                {"role": pin.role, "path": pin.path, "sha256": pin.sha256}
                for pin in self.file_pins
            ],
            "observed_runtime": dict(self.observed_runtime),
            "sensitive_material_included": False,
            "fresh_confirmatory_observation": False,
        }

    def digest(self) -> str:
        return canonical_digest(self.as_dict())


def pin_files(
    repository_root: Path,
    roles_and_paths: Sequence[tuple[str, str]],
) -> tuple[FilePin, ...]:
    pins: list[FilePin] = []
    seen: set[str] = set()
    for role, relative in roles_and_paths:
        if relative in seen:
            raise RuntimeAttestationRefused(f"duplicate pinned path: {relative}")
        seen.add(relative)
        path = (repository_root / relative).resolve()
        try:
            path.relative_to(repository_root.resolve())
        except ValueError as error:
            raise RuntimeAttestationRefused(f"file pin escapes repository: {relative}") from error
        if not path.is_file():
            raise RuntimeAttestationRefused(f"file pin absent: {relative}")
        pins.append(FilePin(role=role, path=relative, sha256=sha256_file(path)))
    return tuple(pins)


def verify_attestation_payload(payload: Mapping[str, Any], repository_root: Path) -> str:
    reject_secret_like(payload)
    pins_raw = payload.get("file_pins")
    if not isinstance(pins_raw, list):
        raise RuntimeAttestationRefused("file_pins missing from attestation payload")
    attestation = RuntimeAttestation(
        role=str(payload.get("role", "")),
        model_id=str(payload.get("model_id", "")),
        model_revision=str(payload.get("model_revision", "")),
        base_image=str(payload.get("base_image", "")),
        base_image_digest=str(payload.get("base_image_digest", "")),
        model_artifact_digest=str(payload.get("model_artifact_digest", "")),
        prompt_schema_digest=str(payload.get("prompt_schema_digest", "")),
        qualification_input_manifest_digest=str(
            payload.get("qualification_input_manifest_digest", "")
        ),
        file_pins=tuple(
            FilePin(role=str(item["role"]), path=str(item["path"]), sha256=str(item["sha256"]))
            for item in pins_raw
            if isinstance(item, Mapping)
        ),
        observed_runtime=payload.get("observed_runtime", {}),
        evidence_class=str(payload.get("evidence_class", "")),
    )
    attestation.validate(repository_root)
    return attestation.digest()


__all__ = [
    "DEVELOPMENT_ONLY",
    "FilePin",
    "RuntimeAttestation",
    "RuntimeAttestationRefused",
    "canonical_digest",
    "pin_files",
    "reject_secret_like",
    "sha256_file",
    "verify_attestation_payload",
]
