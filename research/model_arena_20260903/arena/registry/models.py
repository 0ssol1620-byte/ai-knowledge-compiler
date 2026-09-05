"""Resolve `model_registry.json` (ARENA_CONTRACT section 3.7).

Every GPU model's exact revision comes from the official Hugging Face repository
(`GET /api/models/<repo>?blobs=true`) or, for the models whose identity is a code
release rather than a checkpoint, from the GitHub API. Nothing here guesses: a
repository that does not answer, or answers without a `sha`, raises.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from arena.constants import CAMPAIGN_ID, GPU_MODEL_KEYS, MODEL_KEYS, OPUS_DISPLAY_NAME
from arena.registry.candidates import CANDIDATES_BY_KEY, CandidateSpec, CodeSpec, WeightsSpec
from arena.registry.catalog import RUNPOD_GPU_CATALOG, VRAM_TIERS_GB, catalog_snapshot
from arena.registry.errors import RegistryError, SourceUnavailableError
from arena.registry.http import JsonFetcher
from arena.registry.runtimes import (
    OPUS_MODEL_KEY,
    RuntimeOverlay,
    load_overlays,
    load_prompt_sha256,
    opus_registry_fields,
    overlay_disagreements,
)
from arena.registry.serialize import canonical_sha256

HEX40 = re.compile(r"^[0-9a-f]{40}$")

MODEL_REGISTRY_SCHEMA_ID: Final = "tavonel.arena.model-registry.v1"
MODEL_RECORD_SCHEMA_ID: Final = "tavonel.arena.model-registry-record.v1"

HF_API = "https://huggingface.co/api/models/{repo}?blobs=true"
HF_PAGE = "https://huggingface.co/{repo}"
GH_REPO_API = "https://api.github.com/repos/{repo}"
GH_COMMIT_API = "https://api.github.com/repos/{repo}/commits/{ref}"
GH_TAGS_API = "https://api.github.com/repos/{repo}/tags?per_page=100"
GH_PAGE = "https://github.com/{repo}"

#: File suffixes that count as model weights for the largest-file pin.
WEIGHT_SUFFIXES: Final = (".safetensors", ".bin", ".pth", ".pt", ".onnx", ".pdiparams")

#: benchmark/v6/candidate-registry.yaml, read by lane A3 on 2026-09-03.
PREVIOUS_REGISTRY_SOURCE: Final = "benchmark/v6/candidate-registry.yaml"
PREVIOUS_REGISTRY_RESOLVED_AT: Final = "2026-08-01T00:00:00Z"


@dataclass(frozen=True, slots=True)
class ResolvedWeights:
    repo: str
    revision: str
    last_modified: str | None
    license_id: str | None
    largest_file: str | None
    largest_file_sha256: str | None
    size_bytes: int | None
    total_weight_bytes: int
    file_count: int
    gated: bool
    unresolved_reasons: tuple[str, ...]


def _require_str(payload: Any, key: str, source: str) -> str:
    value = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value:
        raise SourceUnavailableError(f"{source} did not carry a usable {key!r}")
    return value


def _is_weight_file(name: str) -> bool:
    return name.endswith(WEIGHT_SUFFIXES)


def resolve_hf_weights(fetcher: JsonFetcher, spec: WeightsSpec) -> ResolvedWeights:
    url = HF_API.format(repo=spec.repo)
    payload = fetcher.get_json(url)
    if not isinstance(payload, dict):
        raise SourceUnavailableError(f"{url} did not return a model object")

    revision = _require_str(payload, "sha", url)
    if not HEX40.match(revision):
        raise SourceUnavailableError(
            f"{url} returned sha {revision!r}, which is not a 40-hex commit id"
        )

    siblings = payload.get("siblings")
    if not isinstance(siblings, list) or not siblings:
        raise SourceUnavailableError(f"{url} returned no siblings; ?blobs=true is required")

    unresolved: list[str] = []
    weight_files = [
        sibling
        for sibling in siblings
        if isinstance(sibling, dict)
        and isinstance(sibling.get("rfilename"), str)
        and _is_weight_file(sibling["rfilename"])
    ]
    total_weight_bytes = sum(int(f.get("size") or 0) for f in weight_files)

    chosen: dict[str, Any] | None = None
    if spec.expected_largest_file is not None:
        chosen = next(
            (f for f in weight_files if f["rfilename"] == spec.expected_largest_file), None
        )
        if chosen is None:
            raise SourceUnavailableError(
                f"{url} does not contain the expected largest file "
                f"{spec.expected_largest_file!r}"
            )
    elif weight_files:
        chosen = max(weight_files, key=lambda f: int(f.get("size") or 0))
    else:
        unresolved.append(
            "no file with a weight suffix "
            f"({', '.join(WEIGHT_SUFFIXES)}) is published in {spec.repo}"
        )

    largest_file: str | None = None
    largest_sha: str | None = None
    size_bytes: int | None = None
    if chosen is not None:
        largest_file = str(chosen["rfilename"])
        raw_size = chosen.get("size")
        size_bytes = int(raw_size) if isinstance(raw_size, int) else None
        if size_bytes is None:
            unresolved.append(f"{spec.repo}:{largest_file} has no size in the HF blobs listing")
        lfs = chosen.get("lfs")
        lfs_sha = lfs.get("sha256") if isinstance(lfs, dict) else None
        if isinstance(lfs_sha, str) and lfs_sha:
            largest_sha = f"sha256:{lfs_sha}"
        else:
            unresolved.append(
                f"{spec.repo}:{largest_file} is not LFS-tracked, so the HF API publishes "
                "no sha256 for it; the runtime image must hash it after download"
            )

    card = payload.get("cardData")
    license_id = card.get("license") if isinstance(card, dict) else None
    if not isinstance(license_id, str) or not license_id:
        license_id = None
        unresolved.append(
            f"{spec.repo} declares no cardData.license; a repository without a stated "
            "licence grants no reuse right"
        )

    last_modified = payload.get("lastModified")
    gated_raw = payload.get("gated")
    gated = bool(gated_raw) and gated_raw != "False"

    return ResolvedWeights(
        repo=spec.repo,
        revision=revision,
        last_modified=last_modified if isinstance(last_modified, str) else None,
        license_id=license_id,
        largest_file=largest_file,
        largest_file_sha256=largest_sha,
        size_bytes=size_bytes,
        total_weight_bytes=total_weight_bytes,
        file_count=len(siblings),
        gated=gated,
        unresolved_reasons=tuple(unresolved),
    )


def resolve_github(fetcher: JsonFetcher, spec: CodeSpec) -> dict[str, Any]:
    repo_url = GH_REPO_API.format(repo=spec.repo)
    repo_payload = fetcher.get_json(repo_url)
    if not isinstance(repo_payload, dict):
        raise SourceUnavailableError(f"{repo_url} did not return a repository object")

    license_block = repo_payload.get("license")
    license_id = license_block.get("spdx_id") if isinstance(license_block, dict) else None
    default_branch = _require_str(repo_payload, "default_branch", repo_url)

    if spec.tag is not None:
        tags_url = GH_TAGS_API.format(repo=spec.repo)
        tags = fetcher.get_json(tags_url)
        if not isinstance(tags, list):
            raise SourceUnavailableError(f"{tags_url} did not return a tag list")
        match = next(
            (
                tag
                for tag in tags
                if isinstance(tag, dict) and tag.get("name") == spec.tag
            ),
            None,
        )
        if match is None:
            raise SourceUnavailableError(f"{spec.repo} has no tag named {spec.tag!r}")
        commit = match.get("commit")
        revision = _require_str(commit if isinstance(commit, dict) else {}, "sha", tags_url)
        resolved_from = f"tag {spec.tag}"
        source_url = tags_url
    else:
        commit_url = GH_COMMIT_API.format(repo=spec.repo, ref=default_branch)
        commit_payload = fetcher.get_json(commit_url)
        if not isinstance(commit_payload, dict):
            raise SourceUnavailableError(f"{commit_url} did not return a commit object")
        revision = _require_str(commit_payload, "sha", commit_url)
        resolved_from = f"default branch {default_branch}"
        source_url = commit_url

    if not HEX40.match(revision):
        raise SourceUnavailableError(
            f"{spec.repo} resolved to {revision!r}, which is not a 40-hex commit id"
        )

    return {
        "repo": spec.repo,
        "role": spec.role,
        "revision": revision,
        "tag": spec.tag,
        "default_branch": default_branch,
        "license_spdx_id": license_id if isinstance(license_id, str) else None,
        "html_url": GH_PAGE.format(repo=spec.repo),
        "resolved_from": resolved_from,
        "resolution_source_url": source_url,
    }


def estimate_min_vram_gb(spec: CandidateSpec, weights: ResolvedWeights | None) -> dict[str, Any]:
    """Apply the documented sizing rule; never silently return a bare number."""
    if spec.gpu_min_vram_gb_value is not None:
        return {
            "value": spec.gpu_min_vram_gb_value,
            "estimated": True,
            "basis": spec.gpu_min_vram_gb_basis,
        }
    if weights is None or weights.total_weight_bytes <= 0:
        return {
            "value": None,
            "estimated": False,
            "basis": (
                "unresolved: no weight byte total is available, so the sizing rule "
                "cannot be applied"
            ),
        }
    weights_gb = weights.total_weight_bytes / 1e9
    required = weights_gb * 1.6 + 4.0
    tier = next((t for t in VRAM_TIERS_GB if t >= required), None)
    if tier is None:
        raise RegistryError(
            f"{spec.model_key} needs about {required:.1f} GB, above every catalog tier "
            f"{VRAM_TIERS_GB}; set gpu_min_vram_gb_value explicitly"
        )
    return {
        "value": tier,
        "estimated": True,
        "basis": (
            f"{weights_gb:.2f} GB of published weight files x 1.6 + 4 GB headroom = "
            f"{required:.1f} GB, rounded up to the smallest RunPod catalog VRAM tier "
            f"({tier} GB). Replaced by the canary's measured peak VRAM."
        ),
    }


def _check_pool(model_key: str, pool: tuple[str, ...]) -> list[str]:
    unknown = [gpu for gpu in pool if gpu not in RUNPOD_GPU_CATALOG]
    if unknown:
        raise RegistryError(f"{model_key} names GPU types outside the catalog: {unknown}")
    return list(pool)


def build_model_record(
    spec: CandidateSpec,
    *,
    weights: ResolvedWeights | None,
    code: list[dict[str, Any]],
    resolved_at: str,
    resolution_method: str,
    overlay: RuntimeOverlay | None = None,
    opus_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    display_name = OPUS_DISPLAY_NAME if spec.model_key == "opus5_subscription" else (
        spec.display_name
    )

    if spec.model_key == "opus5_subscription":
        repo: str | None = None
        revision = "claude-opus-5 (confirm via lane D probe)"
    elif spec.model_key == "mineru_pipeline":
        primary = code[0]
        repo = primary["repo"]
        revision = primary["revision"]
    else:
        if weights is None:
            raise RegistryError(f"{spec.model_key} has no weights spec but is a GPU model")
        repo = weights.repo
        revision = weights.revision

    license_id = spec.extra.get("license_id")
    if not isinstance(license_id, str):
        license_id = weights.license_id if weights is not None else None
    weights_spec = spec.weights
    license_status = spec.license_status
    license_notes = spec.license_note
    if weights_spec is not None and weights_spec.license_status_override is not None:
        license_status = weights_spec.license_status_override
    if weights_spec is not None and weights_spec.license_note:
        license_notes = f"{license_notes} WEIGHTS: {weights_spec.license_note}"

    license_evidence_url = (
        HF_PAGE.format(repo=weights.repo) if weights is not None else spec.official_source_urls[0]
    )

    inference_config = dict(spec.official_inference_config)
    unresolved: list[str] = []
    if weights is not None:
        unresolved.extend(weights.unresolved_reasons)
    if spec.runtime_version is None:
        reason = spec.extra.get("runtime_version_unresolved_reason")
        unresolved.append(
            str(reason) if reason else f"{spec.model_key}: upstream pins no runtime version"
        )

    previous = spec.previous_registry_revision
    if spec.model_key == "opus5_subscription":
        revision_changed: bool | None = None
    elif previous is None:
        revision_changed = None
    else:
        revision_changed = previous != revision

    vram = estimate_min_vram_gb(spec, weights)
    license_string = (
        license_id
        if license_id
        else "unresolved: upstream declares no licence for this repository"
    )

    record: dict[str, Any] = {
        "schema": MODEL_RECORD_SCHEMA_ID,
        "model_key": spec.model_key,
        "display_name": display_name,
        "role": spec.role,
        "repo": repo,
        "revision": revision,
        "weights": (
            {
                "repo": weights.repo,
                "revision": weights.revision,
                "largest_file": weights.largest_file,
                "largest_file_sha256": weights.largest_file_sha256,
                "size_bytes": weights.size_bytes,
                "total_weight_bytes": weights.total_weight_bytes,
                "file_count": weights.file_count,
                "gated": weights.gated,
                "last_modified": weights.last_modified,
            }
            if weights is not None
            else None
        ),
        "code_repositories": code,
        # masterplan section 10 and arena/core/schemas type `license` as a string;
        # the campaign's structured licence evidence lives in `license_detail`.
        "license": license_string,
        "license_detail": {
            "id": license_id,
            "url": license_evidence_url,
            "status": license_status,
            "notes": license_notes,
        },
        "license_status": license_status,
        "license_evidence_url": license_evidence_url,
        "license_notes": license_notes,
        "runtime_type": spec.runtime_type,
        "runtime_version": spec.runtime_version,
        "runtime_version_source": spec.runtime_version_source,
        "container_image": spec.container_image,
        "container_image_source": spec.container_image_source,
        "container_digest": None,
        "container_digest_unresolved_reason": (
            "lane F resolves the immutable image digest during the build phase"
        ),
        "cuda": spec.cuda,
        "torch": spec.torch,
        # masterplan section 10 types this as a number; the estimate's provenance
        # lives in `gpu_min_vram_gb_detail` so no basis is lost.
        "gpu_min_vram_gb": vram["value"],
        "gpu_min_vram_gb_detail": vram,
        # Placeholder only. D16/D17 give prompt ownership to runtime.json plus
        # prompt_registry/sha256.json, and the overlay below replaces both of these
        # before the record is returned. `resolve_models` refuses to emit a document
        # where that did not happen, so no consumer ever sees this value.
        "prompt_id": None,
        "official_prompt_id": None,
        "prompt_sha256": None,
        "prompt_kind": None,
        "gpu_count_min": None,
        "runtime_repository": None,
        "runtime_revision": None,
        "preprocess_config_id": f"{spec.model_key}_official_preprocess_v1",
        "official_inference_config": inference_config,
        "official_inference_config_sha256": canonical_sha256(inference_config),
        "max_concurrency_per_worker": spec.max_concurrency_per_worker,
        "concurrency_policy": dict(spec.concurrency_policy),
        "concurrency_plan": dict(spec.concurrency_plan),
        "recommended_gpu_pool": _check_pool(spec.model_key, spec.recommended_gpu_pool),
        "gpu_pool_priority": _check_pool(spec.model_key, spec.gpu_pool_priority),
        "shard_size_hint": spec.shard_size_hint,
        "shard_size_hint_basis": spec.shard_size_hint_basis,
        "weights_strategy": spec.weights_strategy,
        "runtime_mode_allowed": list(spec.runtime_mode_allowed),
        "official_source_urls": list(spec.official_source_urls),
        "resolved_at": resolved_at,
        "resolution_method": resolution_method,
        "canary_status": "PENDING",
        "full_run_eligible": False,
        "historical_evidence": spec.historical_evidence,
        "previous_registry_revision": previous,
        "previous_registry_source": (
            None if previous is None else PREVIOUS_REGISTRY_SOURCE
        ),
        "previous_registry_resolved_at": (
            None if previous is None else PREVIOUS_REGISTRY_RESOLVED_AT
        ),
        "revision_changed_since_2026_08": revision_changed,
        "unresolved": unresolved,
        "notes": list(spec.notes),
    }
    for key, value in spec.extra.items():
        if key == "license_id":
            continue
        record[key] = value

    # D16: runtime.json owns model_repo, model_revision, the runtime repository/revision
    # and prompt_id; D17 supplies prompt_sha256. Applied last so it wins over both the
    # candidate specification and spec.extra -- this record is a derived copy.
    if overlay is not None:
        upstream_revision = record["revision"]
        upstream_repo = record["repo"]
        record.update(overlay.as_registry_fields())
        record["identity_source"] = overlay.runtime_json_path
        record["identity_source_decision"] = "ARENA_CONTRACT.md section 11.5 D16"
        record["prompt_source"] = "prompt_registry/sha256.json"
        record["prompt_source_decision"] = "ARENA_CONTRACT.md section 11.5 D17"
        record["upstream_resolved_repo"] = upstream_repo
        record["upstream_resolved_revision"] = upstream_revision
        if upstream_revision != overlay.model_revision or upstream_repo != overlay.model_repo:
            record["identity_pinned_behind_upstream"] = True
            record["identity_pinned_behind_upstream_note"] = (
                f"the live source resolves {upstream_repo}@{upstream_revision}; "
                f"{overlay.runtime_json_path} deliberately pins "
                f"{overlay.model_repo}@{overlay.model_revision} and D16 makes it the owner. "
                "Both revisions were confirmed to exist upstream on 2026-09-03."
            )
        else:
            record["identity_pinned_behind_upstream"] = False
        # Recomputed against the owned revision: the 2026-08 comparison is only
        # meaningful against the revision this campaign will actually run.
        record["revision_changed_since_2026_08"] = (
            None if previous is None else previous != overlay.model_revision
        )
    elif opus_fields is not None:
        record.update(opus_fields)
        record["prompt_source"] = "prompt_registry/sha256.json"
        record["prompt_source_decision"] = "ARENA_CONTRACT.md sections 7 and 11.5 D17"

    return record


def resolve_models(
    fetcher: JsonFetcher,
    *,
    now: datetime | None = None,
    resolution_method: str = "official_huggingface_and_github_api_read_only",
) -> dict[str, Any]:
    """Resolve every ``arena.constants.MODEL_KEYS`` record."""
    resolved_at = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    models: dict[str, Any] = {}

    # D16/D17: identity and prompt binding come from the runtime lane's files, not from
    # the candidate specification. Loaded before any network read so a broken runtime.json
    # or an unresolved prompt id fails the run for free.
    overlays = load_overlays()
    opus_fields = opus_registry_fields(load_prompt_sha256())

    for model_key in MODEL_KEYS:
        spec = CANDIDATES_BY_KEY.get(model_key)
        if spec is None:
            raise RegistryError(f"no candidate specification for model_key {model_key!r}")
        weights = resolve_hf_weights(fetcher, spec.weights) if spec.weights else None
        code = [resolve_github(fetcher, code_spec) for code_spec in spec.code]
        models[model_key] = build_model_record(
            spec,
            weights=weights,
            code=code,
            resolved_at=resolved_at,
            resolution_method=resolution_method,
            overlay=overlays.get(model_key),
            opus_fields=opus_fields if model_key == OPUS_MODEL_KEY else None,
        )

    missing_revision = [
        key
        for key in GPU_MODEL_KEYS
        if not HEX40.match(str(models[key]["revision"]))
    ]
    if missing_revision:
        raise RegistryError(
            f"GPU models without a 40-hex revision: {missing_revision}; the registry "
            "refuses to emit an unpinned model"
        )

    document = {
        "schema": MODEL_REGISTRY_SCHEMA_ID,
        "campaign_id": CAMPAIGN_ID,
        "generated_at": resolved_at,
        "resolution_method": resolution_method,
        "model_count": len(models),
        "gpu_catalog_snapshot": catalog_snapshot(),
        "models": models,
    }

    # Fail closed rather than emit a registry that already disagrees with its owner.
    disagreements = overlay_disagreements(document, overlays)
    if disagreements:
        raise RegistryError(
            "the resolved registry disagrees with runtime.json (D16): "
            + "; ".join(disagreements)
        )
    return document


__all__ = [
    "HEX40",
    "MODEL_RECORD_SCHEMA_ID",
    "MODEL_REGISTRY_SCHEMA_ID",
    "ResolvedWeights",
    "build_model_record",
    "estimate_min_vram_gb",
    "resolve_github",
    "resolve_hf_weights",
    "resolve_models",
]
