"""runtime.json is the owner; `model_registry.json` is a derived copy (D16).

ARENA_CONTRACT.md section 11.5 **D16** moved ownership of a model's identity out of
this package's frozen candidate specification and into
``runtimes/<model_key>/runtime.json``:

    runtime.json owns  model_repo, model_revision, the runtime repository/revision,
                       prompt_id and (D5) gpu_count_min
    model_registry     is regenerated from those values, and preflight fails when
                       the two disagree for any model

``prompt_sha256`` is not owned by either: it is read from
``prompt_registry/sha256.json`` (D17), which is keyed by the runtime.json
``prompt_id``. A ``prompt_id`` with no entry there is a hard failure — the worker
resolves the same file at run time and fails closed, so a registry that pointed at a
missing prompt would only move the failure to a paid pod.

``inference_config_sha256`` is derived here by calling the worker's own
:func:`arena.worker.util.config_sha256` over runtime.json's ``inference_config``
— literally the same function over the same object, not a second implementation
of it. It is distinct from ``official_inference_config_sha256``, which hashes
the *model card's* documented serve command and prompt vocabulary; the two were
conflated once and the GLM-OCR canary of 2026-09-03 spent a rented RTX 4090
discovering it, one HTTP 422 per page.

Nothing here reads the network and nothing here invents a value. A runtime.json that
omits a required field raises rather than defaulting.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from arena.constants import GPU_MODEL_KEYS, NAMESPACE_ROOT
from arena.registry.errors import RegistryError
from arena.worker.util import config_sha256

#: ARENA_CONTRACT section 7: the Opus lane has no runtime.json, and the contract names
#: its prompt id directly.
OPUS_MODEL_KEY: Final = "opus5_subscription"
OPUS_PROMPT_ID: Final = "opus5_transcription_v1"

#: The (repository, revision) key pairs a runtime.json may use inside
#: ``inference_config`` to pin the code that drives the model. Order is the lookup
#: order; a runtime declares at most one of them.
RUNTIME_SOURCE_KEYS: Final = (
    ("runtime_repository", "runtime_revision"),
    ("toolkit_repository", "toolkit_revision"),
    ("sdk_repository", "sdk_revision"),
)

#: The registry fields D16 derives from runtime.json. `preflight` compares exactly
#: these and nothing else: everything outside this tuple is the registry's own
#: resolution work (weights blob hashes, VRAM sizing, catalog pools) or lane F's.
DERIVED_FIELDS: Final = (
    "repo",
    "revision",
    "prompt_id",
    "official_prompt_id",
    "prompt_sha256",
    "prompt_kind",
    "inference_config_sha256",
    "gpu_count_min",
    "runtime_repository",
    "runtime_revision",
)

_REQUIRED_RUNTIME_FIELDS: Final = ("model_key", "model_repo", "model_revision", "prompt_id")


@dataclass(frozen=True, slots=True)
class RuntimeOverlay:
    """The D16-owned half of one model's registry record."""

    model_key: str
    model_repo: str
    model_revision: str
    prompt_id: str
    prompt_sha256: str
    prompt_kind: str | None
    inference_config_sha256: str
    gpu_count_min: int
    runtime_repository: str | None
    runtime_revision: str | None
    runtime_source_field: str | None
    runtime_json_path: str

    def as_registry_fields(self) -> dict[str, Any]:
        """The values ``model_registry.json`` must carry for this model."""
        return {
            "repo": self.model_repo,
            "revision": self.model_revision,
            "prompt_id": self.prompt_id,
            "official_prompt_id": self.prompt_id,
            "prompt_sha256": self.prompt_sha256,
            "prompt_kind": self.prompt_kind,
            "inference_config_sha256": self.inference_config_sha256,
            "gpu_count_min": self.gpu_count_min,
            "runtime_repository": self.runtime_repository,
            "runtime_revision": self.runtime_revision,
        }


def prompt_registry_dir(namespace_root: Path | None = None) -> Path:
    return (namespace_root or NAMESPACE_ROOT) / "prompt_registry"


def runtimes_dir(namespace_root: Path | None = None) -> Path:
    return (namespace_root or NAMESPACE_ROOT) / "runtimes"


def load_prompt_sha256(namespace_root: Path | None = None) -> dict[str, str]:
    """``prompt_registry/sha256.json`` as ``{prompt_id: "sha256:<hex>"}``."""
    path = prompt_registry_dir(namespace_root) / "sha256.json"
    if not path.is_file():
        raise RegistryError(f"{path} is missing; the prompt registry is required by D17")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RegistryError(f"{path} is not a JSON object")
    shas: dict[str, str] = {}
    for prompt_id, digest in payload.items():
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise RegistryError(
                f"{path}: prompt id {prompt_id!r} maps to {digest!r}, which is not a "
                "'sha256:<hex>' string. D17 leaves no prompt id unresolved."
            )
        shas[str(prompt_id)] = digest
    return shas


def load_runtime_spec(model_key: str, namespace_root: Path | None = None) -> dict[str, Any]:
    path = runtimes_dir(namespace_root) / model_key / "runtime.json"
    if not path.is_file():
        raise RegistryError(f"{path} is missing; D16 makes it the owner of {model_key}'s identity")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RegistryError(f"{path} is not a JSON object")
    missing = [field for field in _REQUIRED_RUNTIME_FIELDS if not payload.get(field)]
    if missing:
        raise RegistryError(f"{path} does not declare {missing}")
    if payload["model_key"] != model_key:
        raise RegistryError(
            f"{path} declares model_key {payload['model_key']!r} but lives under {model_key!r}"
        )
    return payload


def _runtime_source(spec: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    config = spec.get("inference_config")
    if not isinstance(config, Mapping):
        return None, None, None
    for repository_key, revision_key in RUNTIME_SOURCE_KEYS:
        repository = config.get(repository_key)
        revision = config.get(revision_key)
        if repository is None and revision is None:
            continue
        if not isinstance(repository, str) or not isinstance(revision, str):
            raise RegistryError(
                f"{spec['model_key']}: inference_config.{repository_key}/{revision_key} must "
                "both be strings when either is present"
            )
        return repository, revision, repository_key
    return None, None, None


def build_overlay(
    model_key: str,
    *,
    prompt_shas: Mapping[str, str],
    namespace_root: Path | None = None,
) -> RuntimeOverlay:
    spec = load_runtime_spec(model_key, namespace_root)
    prompt_id = str(spec["prompt_id"])
    digest = prompt_shas.get(prompt_id)
    if digest is None:
        raise RegistryError(
            f"{model_key}: runtime.json prompt_id {prompt_id!r} has no entry in "
            "prompt_registry/sha256.json. D17 requires every runtime.json prompt id to "
            "resolve to a prompt file; the worker resolves the same file and fails closed."
        )
    prompt_file = prompt_registry_dir(namespace_root) / f"{prompt_id}.txt"
    if not prompt_file.is_file():
        raise RegistryError(f"{prompt_file} is missing for prompt id {prompt_id!r}")

    gpu_count_min = spec.get("gpu_count_min", 1)
    if not isinstance(gpu_count_min, int) or isinstance(gpu_count_min, bool) or gpu_count_min < 1:
        raise RegistryError(f"{model_key}: gpu_count_min must be an integer >= 1")

    prompt_kind = spec.get("prompt_kind")
    if prompt_kind is not None and prompt_kind not in ("text", "toolkit", "none"):
        raise RegistryError(
            f"{model_key}: prompt_kind {prompt_kind!r} is not one of text|toolkit|none (D34)"
        )

    inference_config = spec.get("inference_config")
    if not isinstance(inference_config, Mapping):
        raise RegistryError(
            f"{model_key}: runtime.json has no inference_config object. The worker hashes it "
            "on every run and refuses a request that disagrees, so a registry that cannot "
            "state the hash would only move the refusal to a paid pod."
        )

    repository, revision, source_field = _runtime_source(spec)
    return RuntimeOverlay(
        model_key=model_key,
        model_repo=str(spec["model_repo"]),
        model_revision=str(spec["model_revision"]),
        prompt_id=prompt_id,
        prompt_sha256=digest,
        prompt_kind=str(prompt_kind) if isinstance(prompt_kind, str) else None,
        # The worker's function, over the worker's object. Not a copy of it.
        inference_config_sha256=config_sha256(inference_config),
        gpu_count_min=gpu_count_min,
        runtime_repository=repository,
        runtime_revision=revision,
        runtime_source_field=source_field,
        runtime_json_path=f"runtimes/{model_key}/runtime.json",
    )


def load_overlays(
    model_keys: Iterable[str] = GPU_MODEL_KEYS,
    *,
    namespace_root: Path | None = None,
) -> dict[str, RuntimeOverlay]:
    prompt_shas = load_prompt_sha256(namespace_root)
    return {
        model_key: build_overlay(
            model_key, prompt_shas=prompt_shas, namespace_root=namespace_root
        )
        for model_key in model_keys
    }


def opus_registry_fields(prompt_shas: Mapping[str, str]) -> dict[str, Any]:
    """The Opus lane's prompt binding. It has no runtime.json (ARENA_CONTRACT section 7).

    No ``inference_config_sha256`` either: that hash is defined as "what the
    on-pod worker computes from runtime.json", and the Opus lane has neither.
    ``arena.opus.command`` computes its own over the CLI invocation. Leaving the
    field absent makes ``load_model_registry("opus5_subscription")`` refuse,
    which is the right answer -- the controller cannot dispatch a page to a
    subscription surface.
    """
    digest = prompt_shas.get(OPUS_PROMPT_ID)
    if digest is None:
        raise RegistryError(
            f"prompt_registry/sha256.json has no {OPUS_PROMPT_ID!r} entry; the Opus lane "
            "cannot bind a prompt sha256 into its receipts without it"
        )
    return {
        "prompt_id": OPUS_PROMPT_ID,
        "official_prompt_id": OPUS_PROMPT_ID,
        "prompt_sha256": digest,
        "prompt_kind": "text",
        "gpu_count_min": None,
        "runtime_repository": None,
        "runtime_revision": None,
    }


def overlay_disagreements(
    registry_document: Mapping[str, Any],
    overlays: Mapping[str, RuntimeOverlay],
) -> tuple[str, ...]:
    """Every D16 field where ``model_registry.json`` and runtime.json differ.

    Returned as human-readable lines so preflight can print the reason instead of a
    boolean. Empty means the registry is a faithful derived copy.
    """
    models = registry_document.get("models")
    if not isinstance(models, Mapping):
        return ("model_registry.json has no 'models' object",)

    problems: list[str] = []
    for model_key, overlay in sorted(overlays.items()):
        record = models.get(model_key)
        if not isinstance(record, Mapping):
            problems.append(f"{model_key}: absent from model_registry.json")
            continue
        expected = overlay.as_registry_fields()
        for field in DERIVED_FIELDS:
            if field not in expected:
                continue
            actual = record.get(field, "<missing>")
            if actual != expected[field]:
                problems.append(
                    f"{model_key}.{field}: registry {actual!r} != "
                    f"{overlay.runtime_json_path} {expected[field]!r}"
                )
    return tuple(problems)


__all__ = [
    "DERIVED_FIELDS",
    "OPUS_MODEL_KEY",
    "OPUS_PROMPT_ID",
    "RUNTIME_SOURCE_KEYS",
    "RuntimeOverlay",
    "build_overlay",
    "load_overlays",
    "load_prompt_sha256",
    "load_runtime_spec",
    "opus_registry_fields",
    "overlay_disagreements",
    "prompt_registry_dir",
    "runtimes_dir",
]
