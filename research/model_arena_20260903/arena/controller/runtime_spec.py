"""What the controller needs out of ``runtimes/<model_key>/runtime.json``.

Three integration-pass decisions read from this file rather than from the
registry, because the C lanes own the runtime and the registry is a summary of
it:

- **D5** ``gpu_count_min`` (default 1) becomes the pod's ``gpuCount``.
- **D9** ``gpu_pool_priority`` is validated against the catalog snapshot.
- **D13** ``per_page_timeout_seconds`` is the floor of the stall threshold.
- **D7** ``license.status`` gates ``--execute``.
- ``min_cuda_version`` becomes the create payload's ``allowedCudaVersions``
  filter, and its absence refuses a GPU pod outright.

Nothing here defaults a value it could not read except ``gpu_count_min``, whose
default the contract states (1). A missing file is reported, never assumed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from arena.provider.safety import read_json

__all__ = [
    "CUDA_VERSION_RE",
    "DEFAULT_GPU_COUNT_MIN",
    "PROMPT_KINDS",
    "RuntimeSpecError",
    "RuntimeSpecView",
    "load_runtime_spec",
]

DEFAULT_GPU_COUNT_MIN: Final = 1
# ARENA_CONTRACT section 11 D7: only this status refuses --execute.
BLOCKED_LICENSE_STATUS: Final = "blocked"
# ARENA_CONTRACT 11.5 D34.
PROMPT_KINDS: Final = ("text", "toolkit", "none")
# major.minor, as RunPod reports and filters host CUDA versions.
CUDA_VERSION_RE: Final = re.compile(r"^\d+\.\d+$")


class RuntimeSpecError(RuntimeError):
    """``runtime.json`` is absent or does not carry what the controller needs."""


@dataclass(frozen=True, slots=True)
class RuntimeSpecView:
    """The controller's slice of one runtime's ``runtime.json``."""

    model_key: str
    path: Path
    base_image: str
    model_repo: str
    model_revision: str
    prompt_id: str
    gpu_count_min: int
    gpu_pool_priority: tuple[str, ...]
    per_page_timeout_seconds: int
    runtime_mode_allowed: tuple[str, ...]
    license_status: str | None
    license_id: str | None
    # D5 / D25: the VRAM floor the pool must clear, and D34's prompt kind.
    gpu_min_vram_gb: int | None = None
    prompt_kind: str | None = None
    # The host CUDA floor this runtime's base image needs. None means the
    # runtime has not declared one, which the provisioning gate refuses for a
    # runtime that rents a GPU -- it is never read as "any host will do".
    min_cuda_version: str | None = None

    @property
    def license_blocked(self) -> bool:
        return self.license_status == BLOCKED_LICENSE_STATUS

    def to_dict(self) -> dict[str, object]:
        return {
            "model_key": self.model_key,
            "runtime_json": self.path.name,
            "base_image": self.base_image,
            "model_repo": self.model_repo,
            "model_revision": self.model_revision,
            "prompt_id": self.prompt_id,
            "prompt_kind": self.prompt_kind,
            "min_cuda_version": self.min_cuda_version,
            "gpu_min_vram_gb": self.gpu_min_vram_gb,
            "gpu_count_min": self.gpu_count_min,
            "gpu_pool_priority": list(self.gpu_pool_priority),
            "per_page_timeout_seconds": self.per_page_timeout_seconds,
            "runtime_mode_allowed": list(self.runtime_mode_allowed),
            "license_id": self.license_id,
            "license_status": self.license_status,
        }


def load_runtime_spec(path: Path, model_key: str) -> RuntimeSpecView:
    """Read one ``runtime.json``. Every defect names the field it is about."""

    if not path.is_file():
        raise RuntimeSpecError(
            f"{path} is absent; the C lane that owns runtimes/{model_key}/ writes it"
        )
    document = read_json(path)
    if not isinstance(document, Mapping):
        raise RuntimeSpecError(f"{path.name} is not a JSON object")
    context = f"runtimes/{model_key}/runtime.json"
    declared = document.get("model_key")
    if declared is not None and declared != model_key:
        raise RuntimeSpecError(f"{context} declares model_key {declared!r}, not {model_key!r}")

    gpu_count = document.get("gpu_count_min", DEFAULT_GPU_COUNT_MIN)
    if isinstance(gpu_count, bool) or not isinstance(gpu_count, int) or gpu_count < 1:
        raise RuntimeSpecError(f"{context}.gpu_count_min must be an integer >= 1")

    timeout = document.get("per_page_timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise RuntimeSpecError(f"{context}.per_page_timeout_seconds must be an integer >= 1")

    pool = _string_sequence(document, "gpu_pool_priority", context)
    if not pool:
        raise RuntimeSpecError(f"{context}.gpu_pool_priority is empty; no GPU could be rented")
    modes = _string_sequence(document, "runtime_mode_allowed", context)
    if not modes:
        raise RuntimeSpecError(f"{context}.runtime_mode_allowed is empty")

    license_status: str | None = None
    license_id: str | None = None
    license_raw = document.get("license")
    if isinstance(license_raw, Mapping):
        status = license_raw.get("status")
        identifier = license_raw.get("id")
        license_status = status if isinstance(status, str) and status else None
        license_id = identifier if isinstance(identifier, str) and identifier else None

    vram = document.get("gpu_min_vram_gb")
    if vram is not None and (isinstance(vram, bool) or not isinstance(vram, int) or vram < 1):
        raise RuntimeSpecError(f"{context}.gpu_min_vram_gb must be an integer >= 1 or absent")
    kind = document.get("prompt_kind")
    if kind is not None and (not isinstance(kind, str) or kind not in PROMPT_KINDS):
        raise RuntimeSpecError(f"{context}.prompt_kind must be one of {list(PROMPT_KINDS)} (D34)")
    cuda = document.get("min_cuda_version")
    if cuda is not None and (not isinstance(cuda, str) or not CUDA_VERSION_RE.fullmatch(cuda)):
        raise RuntimeSpecError(
            f"{context}.min_cuda_version must be major.minor (e.g. \"12.9\") or absent"
        )

    return RuntimeSpecView(
        model_key=model_key,
        path=path,
        base_image=_required_str(document, "base_image", context),
        model_repo=_required_str(document, "model_repo", context),
        model_revision=_required_str(document, "model_revision", context),
        prompt_id=_required_str(document, "prompt_id", context),
        gpu_min_vram_gb=vram,
        prompt_kind=kind,
        min_cuda_version=cuda,
        gpu_count_min=gpu_count,
        gpu_pool_priority=pool,
        per_page_timeout_seconds=timeout,
        runtime_mode_allowed=modes,
        license_status=license_status,
        license_id=license_id,
    )


def registry_license_status(record: Mapping[str, Any] | None) -> str | None:
    """The registry's view of a licence status, whichever field carries it."""

    if not record:
        return None
    detail = record.get("license_detail")
    if isinstance(detail, Mapping):
        status = detail.get("status")
        if isinstance(status, str) and status:
            return status
    for key in ("license_status", "license"):
        value = record.get(key)
        if isinstance(value, Mapping):
            status = value.get("status")
            if isinstance(status, str) and status:
                return status
        if isinstance(value, str) and value:
            return value
    return None


def _required_str(document: Mapping[str, Any], key: str, context: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeSpecError(f"{context}.{key} is missing or not a non-empty string")
    return value


def _string_sequence(document: Mapping[str, Any], key: str, context: str) -> tuple[str, ...]:
    value = document.get(key)
    if value is None:
        raise RuntimeSpecError(f"{context}.{key} is missing")
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise RuntimeSpecError(f"{context}.{key} must be an array of strings")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise RuntimeSpecError(f"{context}.{key} must hold non-empty strings")
        items.append(item)
    return tuple(items)
