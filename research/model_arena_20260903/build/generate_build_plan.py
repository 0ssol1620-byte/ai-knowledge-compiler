"""Generate ``build/build_plan.json`` (dry run; no writes to paid infra).

Reads each ``runtimes/<model_key>/runtime.json`` (read-only; other lanes own
those files and may be editing them concurrently -- this script tolerates a
missing file or an unexpected shape by recording the model as
``runtime_json_unavailable`` rather than crashing), attempts a best-effort
anonymous digest resolution for the base image (read-only HTTPS to Docker
Hub / GHCR / any docker-v2-compliant registry -- see ``registry_resolve.py``),
and merges the result with the hand-curated, explicitly-unmeasured estimates
in ``estimates.py``.

Nothing here spends money, creates a pod, or downloads model weights. Running
it twice with the network unavailable produces the same document except for
``generated_at`` and every ``base_image.digest`` becoming ``null`` -- the
schema and model-key coverage never depend on network reachability.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

BUILD_DIR: Final = Path(__file__).resolve().parent
NAMESPACE_ROOT: Final = BUILD_DIR.parent
if str(NAMESPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(NAMESPACE_ROOT))
if str(BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(BUILD_DIR))

from arena.constants import CAMPAIGN_ID, GPU_MODEL_KEYS  # noqa: E402
from estimates import PER_MODEL_ESTIMATES  # noqa: E402
from image_config_inspect import BaseImageConfigResult, inspect_base_image_config  # noqa: E402
from registry_resolve import RegistryLookup, resolve_digest  # noqa: E402

SCHEMA: Final = "tavonel.arena.build_plan.v1"
REGISTRY_NAMESPACE: Final = "ghcr.io/0ssol1620-byte/tavonel-arena"
_DISK_SAFETY_FACTOR: Final = 2.5
_MIN_DISK_GB: Final = 40


def _read_runtime_json(model_key: str) -> tuple[Mapping[str, Any] | None, str | None]:
    path = NAMESPACE_ROOT / "runtimes" / model_key / "runtime.json"
    if not path.is_file():
        return None, f"{path} does not exist yet (another lane owns it)"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path} could not be read/parsed: {exc.__class__.__name__}: {exc}"
    if not isinstance(value, dict):
        return None, f"{path} does not contain a JSON object"
    return value, None


def _resolve_base_image(base_image: str, *, offline: bool) -> RegistryLookup:
    if offline:
        return RegistryLookup(
            ref=base_image,
            digest=None,
            resolved=False,
            method="skipped_offline",
            detail="--offline was passed; no network call attempted",
            resolve_command=f"docker buildx imagetools inspect {base_image}",
        )
    try:
        return resolve_digest(base_image)
    except Exception as exc:
        return RegistryLookup(
            ref=base_image,
            digest=None,
            resolved=False,
            method="resolve_digest_raised",
            detail=f"{exc.__class__.__name__}: {exc}",
            resolve_command=f"docker buildx imagetools inspect {base_image}",
        )


def _base_image_config_for(
    base_image_name: str | None, digest: str | None, *, offline: bool
) -> dict[str, Any]:
    if not base_image_name:
        result = BaseImageConfigResult(
            entrypoint=None, cmd=None, python_on_path=None, inspected_at=None,
            source=None, resolved=False, detail="no base_image to inspect",
        )
    else:
        # Prefer the exact resolved digest so the config inspection is
        # pinned to the same image build_plan.json already recorded, not
        # whatever a floating tag happens to point at right now.
        ref = base_image_name
        if digest and "@sha256:" not in ref:
            name_and_tag = ref
            ref = f"{name_and_tag}@{digest}"
        try:
            result = inspect_base_image_config(ref, offline=offline)
        except Exception as exc:  # never let inspection crash the whole plan generation
            result = BaseImageConfigResult(
                entrypoint=None, cmd=None, python_on_path=None, inspected_at=None,
                source=None, resolved=False,
                detail=f"inspect_base_image_config raised: {exc.__class__.__name__}: {exc}",
            )
    return {
        "entrypoint": result.entrypoint,
        "cmd": result.cmd,
        "python_on_path": result.python_on_path,
        "inspected_at": result.inspected_at,
        "source": result.source,
        "resolved": result.resolved,
        "detail": result.detail,
    }


def _builder_pod_for(estimated_image_gb: float, gpu_min_vram_gb: float | None) -> dict[str, Any]:
    disk_gb = max(_MIN_DISK_GB, round(estimated_image_gb * _DISK_SAFETY_FACTOR))
    return {
        "type": "CPU (buildah/podman, no GPU driver needed to build a CUDA-runtime image)",
        "disk_gb": disk_gb,
        "gpu_required": False,
        "note": (
            f"sized as max({_MIN_DISK_GB}, estimated_image_gb * {_DISK_SAFETY_FACTOR}) "
            "to hold the pulled base layers, the new layer, and the pushed blobs "
            "concurrently; gpu_min_vram_gb "
            f"({gpu_min_vram_gb if gpu_min_vram_gb is not None else 'unknown'}) describes "
            "the eventual inference pod, not this builder pod."
        ),
    }


def _dockerfile_copies_prompt_registry(model_key: str) -> bool | None:
    """Best-effort, read-only check of whether the runtime's Dockerfile copies
    ``prompt_registry/`` into the image. Returns ``None`` (never crashes the
    plan) when the Dockerfile does not exist yet -- another lane may own it."""
    path = NAMESPACE_ROOT / "runtimes" / model_key / "Dockerfile"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return any(
        line.strip().startswith("COPY") and "prompt_registry/" in line
        for line in text.splitlines()
    )


def _model_plan(model_key: str, *, offline: bool) -> dict[str, Any]:
    runtime_doc, runtime_error = _read_runtime_json(model_key)
    estimate = PER_MODEL_ESTIMATES.get(model_key)

    base_image_name = None
    weights_strategy = None
    gpu_min_vram_gb = None
    runtime_mode_allowed = None
    if runtime_doc is not None:
        base_image_name = runtime_doc.get("base_image")
        weights_strategy = runtime_doc.get("weights_strategy")
        gpu_min_vram_gb = runtime_doc.get("gpu_min_vram_gb")
        runtime_mode_allowed = runtime_doc.get("runtime_mode_allowed")

    dockerfile_copies_prompt_registry = _dockerfile_copies_prompt_registry(model_key)

    base_image: dict[str, Any] = {"name": None, "tag": None, "digest": None}
    risks: list[str] = list(estimate.risks) if estimate is not None else []
    if runtime_error:
        risks.append(f"runtime.json unavailable at generation time: {runtime_error}")
    if dockerfile_copies_prompt_registry is None:
        risks.append(
            f"runtimes/{model_key}/Dockerfile does not exist yet (another lane owns it); "
            "cannot determine whether it copies prompt_registry/"
        )
    elif not dockerfile_copies_prompt_registry:
        risks.append(
            f"runtimes/{model_key}/Dockerfile does not COPY prompt_registry/ -- "
            "the worker's ARENA_PROMPT_FILE resolution will fail closed at runtime"
        )

    if isinstance(base_image_name, str) and base_image_name:
        if "@sha256:" in base_image_name:
            name_and_tag, _, digest = base_image_name.partition("@")
        else:
            name_and_tag, digest = base_image_name, ""
        if ":" in name_and_tag:
            name, _, tag = name_and_tag.rpartition(":")
        else:
            name, tag = name_and_tag, None
        base_image["name"] = name or name_and_tag
        base_image["tag"] = tag
        lookup = _resolve_base_image(base_image_name, offline=offline)
        base_image["digest"] = digest or lookup.digest
        base_image["resolved_at"] = None if offline else datetime.now(UTC).isoformat()
        base_image["resolution_method"] = "embedded_in_runtime_json" if digest else lookup.method
        base_image["resolution_detail"] = (
            "runtime.json already pins a digest" if digest else lookup.detail
        )
        base_image["resolve_command"] = lookup.resolve_command
        if not base_image["digest"]:
            risks.append(
                f"base image digest could not be resolved anonymously; resolve with: "
                f"{lookup.resolve_command}"
            )
        base_image_config = _base_image_config_for(
            base_image_name, base_image["digest"], offline=offline
        )
        if not base_image_config["resolved"]:
            risks.append(
                f"base_image_config not resolved: {base_image_config['detail']}"
            )
    else:
        base_image_config = _base_image_config_for(None, None, offline=offline)
        base_image["resolution_detail"] = (
            "no base_image available (runtime.json missing/unreadable)"
        )
        risks.append(
            "cannot plan a build without a base_image; see runtime.json availability above"
        )

    if estimate is not None:
        estimated_image_gb = estimate.estimated_image_gb
        estimated_build_minutes = estimate.estimated_build_minutes
        weights_block = {
            "strategy": weights_strategy or "unknown",
            "size_gb": estimate.weights_size_gb,
            "size_gb_reason": estimate.weights_size_reason,
        }
        estimate_meta = {
            "estimate_confidence": estimate.estimate_confidence,
            "estimate_method": estimate.estimate_method,
        }
    else:
        estimated_image_gb = None
        estimated_build_minutes = None
        weights_block = {
            "strategy": weights_strategy or "unknown",
            "size_gb": None,
            "size_gb_reason": "no estimate authored for this model_key in estimates.py",
        }
        estimate_meta = {"estimate_confidence": "none", "estimate_method": "not estimated"}
        risks.append(f"no entry in estimates.py for model_key={model_key!r}")

    return {
        "model_key": model_key,
        "dockerfile": f"runtimes/{model_key}/Dockerfile",
        "context": ".",
        "base_image": base_image,
        "base_image_config": base_image_config,
        "registry_target": f"{REGISTRY_NAMESPACE}/{model_key}",
        "estimated_image_gb": estimated_image_gb,
        "estimated_build_minutes": estimated_build_minutes,
        "builder_pod": _builder_pod_for(estimated_image_gb or 20.0, gpu_min_vram_gb),
        "weights": weights_block,
        **estimate_meta,
        "dockerfile_copies_prompt_registry": dockerfile_copies_prompt_registry,
        "runtime_mode_allowed": runtime_mode_allowed,
        "risks": risks,
    }


def build_plan_document(*, offline: bool = False) -> dict[str, Any]:
    models = {key: _model_plan(key, offline=offline) for key in GPU_MODEL_KEYS}
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "campaign_id": CAMPAIGN_ID,
        "registry_namespace": REGISTRY_NAMESPACE,
        "offline": offline,
        "models": models,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=BUILD_DIR / "build_plan.json",
        help="where to write build_plan.json (default: build/build_plan.json)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip every network call; all base_image.digest fields become null",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    document = build_plan_document(offline=args.offline)
    tmp_path = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    import os

    os.replace(tmp_path, args.output)
    print(f"wrote {args.output} ({len(document['models'])} model_keys)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_plan_document", "main"]
