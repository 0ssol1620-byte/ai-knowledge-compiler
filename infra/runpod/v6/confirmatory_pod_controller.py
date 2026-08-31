"""Preflight-only confirmatory GPU pod controller for SEM-RISK-CONF runs.

This module resolves the frozen model pins for the SEM-RISK-CONF confirmatory
protocol, builds a run plan bound to the sealed public-core inference
manifests, and demonstrates the pod lifecycle (create -> ... -> delete ->
absence) against the real ``infra.runpod.v6.pod_client`` contracts.

Structural safety invariants, enforced by construction rather than by
discipline:

* No ``__main__`` entry point and no CLI. This module cannot be invoked
  directly to launch anything.
* No credential is ever read from the environment here. A ``RunPodPodClient``
  must be constructed by the caller and injected into :func:`execute`.
* :func:`execute` refuses to touch ``client`` or ``budget`` unless it is
  called with ``armed=True`` -- the default is always inert.
* Given the candidate registry's current state (neither
  ``paddleocr-vl-1.6`` nor ``mineru-3.4.4-vlm`` has a baked runtime
  qualification yet), :func:`preflight` demonstrates that
  ``PodCreateSpec.require_ready()`` refuses to authorize a pod. That refusal
  is the expected, correct result of this round -- not a bug to route around.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import monotonic
from typing import Any, Final

import yaml

from benchmark.runpod_eval.input_contract import (
    InferenceInputSelection,
    adaptive_repeat_indices,
    select_inference_inputs,
)
from benchmark.v6.contracts import ContractError, canonical_sha256
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget
from infra.runpod.v6.pod_client import PodClientError, PodCreateSpec, RunPodPodClient
from infra.runpod.v6.runtime_qualification import BakedRuntimeQualification

SCHEMA: Final = "tavonel.sem-risk-conf.gpu-lifecycle.v1"
TRANSPORT_VERSION: Final = "runpod-rest-v1"
OUTPUT_LAYOUT_CONTRACT: Final = "markdown-repeat-{repeat}/{case_id}.md"
CANDIDATE_REGISTRY_RELATIVE_PATH: Final = "benchmark/v6/candidate-registry.yaml"
PROTOCOL_RELATIVE_PATH: Final = "research/experiments/SEM-RISK-CONF-02/protocol.json"
SUPPORTED_IMAGE_EXTENSIONS: Final = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
)
_ABSENCE_STATUS_RE = re.compile(r"status (\d+)")
_MAX_RUNTIME_HOURS: Final = Decimal("8")


class GpuLifecycleStateError(ContractError):
    """Raised when the pod lifecycle observes a state it must not accept."""


# --------------------------------------------------------------------------
# Pin resolution
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    candidate_id: str
    repository: str
    revision: str
    artifact_sha256: str
    runtime_recipe: str
    runtime_source_repository: str | None
    runtime_source_revision: str | None
    license_id: str
    license_commercial_use: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "repository": self.repository,
            "revision": self.revision,
            "artifact_sha256": self.artifact_sha256,
            "runtime_recipe": self.runtime_recipe,
            "runtime_source_repository": self.runtime_source_repository,
            "runtime_source_revision": self.runtime_source_revision,
            "license_id": self.license_id,
            "license_commercial_use": self.license_commercial_use,
        }


@dataclass(frozen=True, slots=True)
class ConfirmatoryPinResolution:
    repo_root: Path
    candidate_registry_path: Path
    candidate_registry_sha256: str
    protocol_path: Path
    protocol_sha256: str
    scientific_experiment_id: str
    primary: CandidateIdentity
    specialist: CandidateIdentity
    promotion_eligible: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_registry_sha256": self.candidate_registry_sha256,
            "protocol_sha256": self.protocol_sha256,
            "scientific_experiment_id": self.scientific_experiment_id,
            "primary": self.primary.to_dict(),
            "specialist": {
                **self.specialist.to_dict(),
                "promotion_eligible": self.promotion_eligible,
            },
        }


def _resolve_candidate_identity(entry: Mapping[str, Any], *, label: str) -> CandidateIdentity:
    identity = entry.get("identity")
    license_block = entry.get("license")
    if not isinstance(identity, Mapping) or not isinstance(license_block, Mapping):
        raise ContractError(f"{label} candidate is missing an identity or license block")
    artifact_sha256 = identity.get("artifact_sha256")
    if not artifact_sha256:
        raise ContractError(f"{label} candidate has no resolved artifact_sha256")
    runtime_recipe = identity.get("runtime_recipe")
    if not runtime_recipe:
        raise ContractError(f"{label} candidate has no resolved runtime_recipe")
    repository = identity.get("repository")
    revision = identity.get("revision")
    if not repository or not revision:
        raise ContractError(f"{label} candidate identity is not fully resolved")
    runtime_source_repository = identity.get("runtime_source_repository")
    runtime_source_revision = identity.get("runtime_source_revision")
    return CandidateIdentity(
        candidate_id=str(entry.get("id", "")),
        repository=str(repository),
        revision=str(revision),
        artifact_sha256=str(artifact_sha256),
        runtime_recipe=str(runtime_recipe),
        runtime_source_repository=(
            str(runtime_source_repository) if runtime_source_repository else None
        ),
        runtime_source_revision=(
            str(runtime_source_revision) if runtime_source_revision else None
        ),
        license_id=str(license_block.get("id", "")),
        license_commercial_use=str(license_block.get("commercial_use", "")),
    )


def resolve_confirmatory_pins(repo_root: Path) -> ConfirmatoryPinResolution:
    """Re-hash the candidate registry and bind the primary/specialist pins.

    Raises :class:`ContractError` on any hash mismatch, missing candidate, or
    unresolved identity field. This never performs network I/O.
    """

    registry_path = repo_root / CANDIDATE_REGISTRY_RELATIVE_PATH
    protocol_path = repo_root / PROTOCOL_RELATIVE_PATH
    if not registry_path.is_file():
        raise ContractError(f"candidate registry is missing: {registry_path}")
    if not protocol_path.is_file():
        raise ContractError(f"confirmatory protocol is missing: {protocol_path}")

    registry_bytes = registry_path.read_bytes()
    registry_sha256 = "sha256:" + hashlib.sha256(registry_bytes).hexdigest()
    protocol_bytes = protocol_path.read_bytes()
    protocol_sha256 = "sha256:" + hashlib.sha256(protocol_bytes).hexdigest()
    protocol = json.loads(protocol_bytes.decode("utf-8"))

    source_hashes = protocol.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        raise ContractError("protocol has no source_hashes contract")
    expected_registry_sha256 = source_hashes.get(CANDIDATE_REGISTRY_RELATIVE_PATH)
    if not expected_registry_sha256:
        raise ContractError("protocol does not pin the candidate registry hash")
    if registry_sha256 != expected_registry_sha256:
        raise ContractError(
            "candidate registry hash does not match the frozen protocol pin "
            f"(actual={registry_sha256}, expected={expected_registry_sha256})"
        )

    parser_roles = protocol.get("parser_roles")
    if not isinstance(parser_roles, Mapping):
        raise ContractError("protocol has no parser_roles contract")
    primary_id = str(parser_roles.get("primary", ""))
    specialist_id = str(parser_roles.get("research_specialist", ""))
    if not primary_id or not specialist_id:
        raise ContractError("protocol does not name a primary and research specialist candidate")

    registry = yaml.safe_load(registry_bytes)
    candidates_raw = registry.get("candidates") if isinstance(registry, Mapping) else None
    if not isinstance(candidates_raw, list):
        raise ContractError("candidate registry has no candidates list")
    candidates = {
        str(item.get("id")): item for item in candidates_raw if isinstance(item, Mapping)
    }

    primary_entry = candidates.get(primary_id)
    specialist_entry = candidates.get(specialist_id)
    if primary_entry is None:
        raise ContractError(f"registry is missing the pinned primary candidate {primary_id!r}")
    if specialist_entry is None:
        raise ContractError(
            f"registry is missing the pinned research specialist candidate {specialist_id!r}"
        )

    primary = _resolve_candidate_identity(primary_entry, label="primary")
    specialist = _resolve_candidate_identity(specialist_entry, label="research specialist")

    commercial_use_allowed = specialist.license_commercial_use == "allowed"
    protocol_status = str(parser_roles.get("specialist_promotion_status", ""))
    status_claims_promotable = protocol_status == "promotable"
    promotion_eligible = commercial_use_allowed
    if promotion_eligible != status_claims_promotable:
        raise ContractError(
            "specialist promotion eligibility disagrees with "
            "protocol.parser_roles.specialist_promotion_status "
            f"(license commercial_use={specialist.license_commercial_use!r}, "
            f"protocol status={protocol_status!r})"
        )

    scientific_experiment_id = str(protocol.get("experiment_id", ""))
    if not scientific_experiment_id:
        raise ContractError("protocol has no experiment_id")

    return ConfirmatoryPinResolution(
        repo_root=repo_root,
        candidate_registry_path=registry_path,
        candidate_registry_sha256=registry_sha256,
        protocol_path=protocol_path,
        protocol_sha256=protocol_sha256,
        scientific_experiment_id=scientific_experiment_id,
        primary=primary,
        specialist=specialist,
        promotion_eligible=promotion_eligible,
    )


# --------------------------------------------------------------------------
# Run plan
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LaneManifestInput:
    """Where to find one lane's sealed public-core manifest and its images."""

    lane: str
    manifest_path: Path
    input_dir: Path


@dataclass(frozen=True, slots=True)
class ResolvedLaneManifest:
    lane: str
    manifest_path: Path
    manifest_sha256: str
    input_count: int
    dataset_revision: str
    selection: InferenceInputSelection

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane,
            "path": str(self.manifest_path),
            "content_sha256": self.manifest_sha256,
            "input_count": self.input_count,
            "dataset_revision": self.dataset_revision,
        }


def _resolve_lane_manifest(lane_input: LaneManifestInput) -> ResolvedLaneManifest:
    manifest_path = lane_input.manifest_path
    if not manifest_path.is_file():
        raise ContractError(f"lane {lane_input.lane!r} manifest is missing: {manifest_path}")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    manifest_sha256 = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    expected_count = manifest.get("input_count")
    if not isinstance(expected_count, int) or expected_count <= 0:
        raise ContractError(f"lane {lane_input.lane!r} manifest has no positive input_count")

    # `select_inference_inputs` is the real frozen contract: it independently
    # loads and validates `manifest_path`, including confirming
    # `ground_truth_mounted is False`, and checks every input path resolves
    # inside `input_dir` with a matching sha256.
    selection = select_inference_inputs(
        input_dir=lane_input.input_dir,
        supported_extensions=set(SUPPORTED_IMAGE_EXTENSIONS),
        limit=0,
        evidence_class="public-core",
        expected_input_count=expected_count,
        input_manifest=manifest_path,
    )
    if selection.complete_input_coverage is not True:
        raise ContractError(f"lane {lane_input.lane!r} manifest coverage is incomplete")

    dataset_revision = manifest.get("dataset_revision")
    if not dataset_revision:
        raise ContractError(f"lane {lane_input.lane!r} manifest has no dataset_revision")

    return ResolvedLaneManifest(
        lane=lane_input.lane,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        input_count=expected_count,
        dataset_revision=str(dataset_revision),
        selection=selection,
    )


@dataclass(frozen=True, slots=True)
class ConfirmatoryRunPlan:
    pins: ConfirmatoryPinResolution
    lane_a: ResolvedLaneManifest
    lane_b: ResolvedLaneManifest
    inference_manifest_seal_path: Path
    inference_manifest_seal_sha256: str
    hard_cap_usd: Decimal
    gpu_type: str
    image_digest: str | None
    maximum_runtime_hours: Decimal
    repeat_plan: Mapping[str, tuple[int, ...]]
    output_layout_contract: str
    upload_allowlist: frozenset[Path]
    upload_allowlist_sha256: str
    baked_runtime_qualification: BakedRuntimeQualification | None = None
    baked_runtime_receipt_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pins": self.pins.to_dict(),
            "input_manifests": {
                "a": self.lane_a.to_dict(),
                "b": self.lane_b.to_dict(),
            },
            "inference_manifest_seal_sha256": self.inference_manifest_seal_sha256,
            "hard_cap_usd": str(self.hard_cap_usd),
            "gpu_type": self.gpu_type,
            "image_digest": self.image_digest,
            "maximum_runtime_hours": str(self.maximum_runtime_hours),
            "repeat_plan": {key: list(value) for key, value in self.repeat_plan.items()},
            "output_layout_contract": self.output_layout_contract,
            "upload_allowlist_sha256": self.upload_allowlist_sha256,
            "ground_truth_uploaded": False,
        }


def assert_upload_allowed(plan: ConfirmatoryRunPlan, path: Path) -> None:
    """Reject any upload path outside the plan's closed allowlist.

    The allowlist is exactly the resolved manifest input paths for both
    lanes -- nothing else may ever be selected for upload.
    """

    resolved = path.resolve()
    if resolved not in plan.upload_allowlist:
        raise ContractError(f"upload path is outside the closed allowlist: {resolved}")


def build_run_plan(
    *,
    pins: ConfirmatoryPinResolution,
    lane_a: LaneManifestInput,
    lane_b: LaneManifestInput,
    inference_manifest_seal_path: Path,
    hard_cap_usd: Decimal | str,
    gpu_type: str,
    maximum_runtime_hours: Decimal | str,
    image_digest: str | None = None,
    baked_runtime_qualification: BakedRuntimeQualification | None = None,
    baked_runtime_receipt_sha256: str | None = None,
) -> ConfirmatoryRunPlan:
    if lane_a.lane != "a" or lane_b.lane != "b":
        raise ContractError("lane manifests must be labelled 'a' and 'b' respectively")

    resolved_a = _resolve_lane_manifest(lane_a)
    resolved_b = _resolve_lane_manifest(lane_b)

    if not inference_manifest_seal_path.is_file():
        raise ContractError(
            f"inference manifest seal receipt is missing: {inference_manifest_seal_path}"
        )
    seal_bytes = inference_manifest_seal_path.read_bytes()
    seal = json.loads(seal_bytes.decode("utf-8"))
    seal_sha256 = "sha256:" + hashlib.sha256(seal_bytes).hexdigest()

    seal_manifests = seal.get("manifests")
    if not isinstance(seal_manifests, Mapping):
        raise ContractError("inference manifest seal has no manifests contract")
    if seal_manifests.get("a") != resolved_a.manifest_sha256:
        raise ContractError("inference manifest seal does not match the supplied lane A manifest")
    if seal_manifests.get("b") != resolved_b.manifest_sha256:
        raise ContractError("inference manifest seal does not match the supplied lane B manifest")
    if seal.get("ground_truth_mounted") is not False:
        raise ContractError("inference manifest seal does not attest ground-truth isolation")
    if seal.get("protocol_sha256") != pins.protocol_sha256:
        raise ContractError("inference manifest seal was frozen against a different protocol")

    paddle_repeats = seal.get("paddle_repeats")
    specialist_repeats = seal.get("specialist_repeats")
    if not isinstance(paddle_repeats, Mapping) or not isinstance(specialist_repeats, Mapping):
        raise ContractError("inference manifest seal has no repeat plan")
    repeat_plan = {
        "paddle_lane_a": adaptive_repeat_indices(
            evidence_class="public-core",
            repeats=int(paddle_repeats.get("lane_a", 0)),
            repeat_start_index=1,
        ),
        "paddle_lane_b": adaptive_repeat_indices(
            evidence_class="public-core",
            repeats=int(paddle_repeats.get("lane_b", 0)),
            repeat_start_index=1,
        ),
        "specialist_lane_a": adaptive_repeat_indices(
            evidence_class="public-core",
            repeats=int(specialist_repeats.get("lane_a", 0)),
            repeat_start_index=1,
        ),
        "specialist_lane_b": adaptive_repeat_indices(
            evidence_class="public-core",
            repeats=int(specialist_repeats.get("lane_b", 0)),
            repeat_start_index=1,
        ),
    }

    upload_allowlist = frozenset(
        path.resolve() for path in (*resolved_a.selection.selected, *resolved_b.selection.selected)
    )
    upload_allowlist_sha256 = canonical_sha256(sorted(str(path) for path in upload_allowlist))

    cap = hard_cap_usd if isinstance(hard_cap_usd, Decimal) else Decimal(str(hard_cap_usd))
    if cap <= 0:
        raise ContractError("hard_cap_usd must be positive")

    runtime_hours = (
        maximum_runtime_hours
        if isinstance(maximum_runtime_hours, Decimal)
        else Decimal(str(maximum_runtime_hours))
    )
    if runtime_hours <= 0 or runtime_hours > _MAX_RUNTIME_HOURS:
        raise ContractError("maximum_runtime_hours must be between 0 and 8")

    if image_digest is not None:
        image_ok = bool(re.fullmatch(r"[a-z0-9._/-]+@sha256:[0-9a-f]{64}", image_digest))
        if not image_ok:
            raise ContractError("image_digest must be an immutable sha256 digest")

    if (baked_runtime_qualification is None) != (baked_runtime_receipt_sha256 is None):
        raise ContractError(
            "baked_runtime_qualification and baked_runtime_receipt_sha256 must be "
            "supplied together or not at all"
        )

    return ConfirmatoryRunPlan(
        pins=pins,
        lane_a=resolved_a,
        lane_b=resolved_b,
        inference_manifest_seal_path=inference_manifest_seal_path,
        inference_manifest_seal_sha256=seal_sha256,
        hard_cap_usd=cap,
        gpu_type=gpu_type,
        image_digest=image_digest,
        maximum_runtime_hours=runtime_hours,
        repeat_plan=repeat_plan,
        output_layout_contract=OUTPUT_LAYOUT_CONTRACT,
        upload_allowlist=upload_allowlist,
        upload_allowlist_sha256=upload_allowlist_sha256,
        baked_runtime_qualification=baked_runtime_qualification,
        baked_runtime_receipt_sha256=baked_runtime_receipt_sha256,
    )


# --------------------------------------------------------------------------
# Pod spec construction (shared by preflight and execute)
# --------------------------------------------------------------------------

_PLACEHOLDER_PUBLIC_KEY_PREFIX: Final = "ssh-ed25519 AAAA-PREFLIGHT-ONLY-NOT-A-REAL-KEY"


def _placeholder_image_name(plan: ConfirmatoryRunPlan) -> str:
    candidate_id = plan.pins.primary.candidate_id
    digest_suffix = plan.pins.primary.artifact_sha256.replace("sha256:", "@sha256:")
    return f"ghcr.io/tavonel/sem-risk-conf/{candidate_id}{digest_suffix}"


def _pod_name(plan: ConfirmatoryRunPlan) -> str:
    digest_fragment = hashlib.sha256(
        plan.inference_manifest_seal_sha256.encode("utf-8")
    ).hexdigest()[:10]
    name = f"sem-risk-conf-{plan.pins.primary.candidate_id}-{digest_fragment}"
    return name[:80]


def _pod_create_mapping(plan: ConfirmatoryRunPlan, *, public_key: str) -> dict[str, Any]:
    image_name = plan.image_digest or _placeholder_image_name(plan)
    mapping: dict[str, Any] = {
        "name": _pod_name(plan),
        "image_name": image_name,
        "gpu_type": plan.gpu_type,
        "public_key": public_key,
    }
    if plan.baked_runtime_qualification is not None and plan.baked_runtime_receipt_sha256:
        qualification_fields = {
            key: value
            for key, value in _dataclass_to_mapping(plan.baked_runtime_qualification).items()
            if key != "receipt_sha256"
        }
        mapping["qualification_state"] = "READY"
        mapping["baked_runtime_receipt_sha256"] = plan.baked_runtime_receipt_sha256
        mapping["baked_runtime_qualification"] = qualification_fields
    else:
        mapping["qualification_state"] = "BUILD_REQUIRED"
    return mapping


def _dataclass_to_mapping(value: BakedRuntimeQualification) -> dict[str, Any]:
    return {
        "schema": "folynta.baked-runtime-qualification.v1",
        "generated_at": value.generated_at,
        "source_commit": value.source_commit,
        "source_tree_sha256": value.source_tree_sha256,
        "dockerfile_sha256": value.dockerfile_sha256,
        "image_digest": value.image_digest,
        "gpu_type": value.gpu_type,
        "cuda_version": value.cuda_version,
        "framework_version": value.framework_version,
        "model_revision": value.model_revision,
        "model_artifact_sha256": value.model_artifact_sha256,
        "baked_runtime_file_sha256": value.baked_runtime_file_sha256,
        "sbom_sha256": value.sbom_sha256,
        "vulnerability_scan_sha256": value.vulnerability_scan_sha256,
        "critical_vulnerability_count": value.critical_vulnerability_count,
        "smoke_input_sha256": value.smoke_input_sha256,
        "smoke_prediction_sha256": value.smoke_prediction_sha256,
        "smoke_expected_sha256": value.smoke_expected_sha256,
        "identity_verified": value.identity_verified,
        "model_artifact_verified": value.model_artifact_verified,
        "smoke_passed": value.smoke_passed,
        "passed": value.passed,
    }


# --------------------------------------------------------------------------
# Receipt helpers
# --------------------------------------------------------------------------


def _now_rfc3339() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git_head(repo_root: Path) -> str | None:
    git_executable = shutil.which("git")
    if git_executable is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - executable is resolved and arguments are internal constants.
            [git_executable, "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    head = completed.stdout.strip()
    return head or None


def _base_receipt(plan: ConfirmatoryRunPlan, *, state: str, armed: bool) -> dict[str, Any]:
    plan_dict = plan.to_dict()
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "state": state,
        "generated_at": _now_rfc3339(),
        "git_head": _git_head(plan.pins.repo_root),
        "scientific_experiment_id": plan.pins.scientific_experiment_id,
        "transport_version": TRANSPORT_VERSION,
        "protocol_sha256": plan.pins.protocol_sha256,
        "selection_sha256": plan.inference_manifest_seal_sha256,
        "pins": plan_dict["pins"],
        "candidate_registry_sha256": plan.pins.candidate_registry_sha256,
        "input_manifests": plan_dict["input_manifests"],
        "inference_manifest_seal_sha256": plan.inference_manifest_seal_sha256,
        "repeat_plan": plan_dict["repeat_plan"],
        "output_layout_contract": plan.output_layout_contract,
        "ground_truth_uploaded": False,
        "upload_allowlist_sha256": plan.upload_allowlist_sha256,
        "budget": None,
        "pre_run_inventory": None,
        "provision_receipt": None,
        "runtime_identity": None,
        "gpu_identity": {"gpu_type": plan.gpu_type, "verified": False},
        "model_artifact_identity": {
            "primary": plan.pins.primary.to_dict(),
            "specialist": plan.pins.specialist.to_dict(),
        },
        "timestamps": {"generated_at": _now_rfc3339()},
        "billing": None,
        "cleanup": None,
        "provider_absence": None,
        "orphan_audit": None,
        "armed": armed,
    }
    return receipt


def _seal_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = canonical_sha256(body)
    return receipt


# --------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------


def preflight(plan: ConfirmatoryRunPlan, *, budget: AuthorizedSpendBudget) -> dict[str, Any]:
    """Demonstrate the spend cap and readiness gate without any network I/O.

    Reserves and immediately releases the plan's hard cap against ``budget``
    to prove the cap is enforced before any provider write would occur, then
    constructs the real :class:`PodCreateSpec` for this plan and calls
    ``require_ready()``. Given the candidate registry's current state (no
    baked runtime qualification for either candidate), that call raises
    :class:`ContractError`, and this function lets it propagate rather than
    catching it or working around it -- that refusal is the correct, expected
    result of this round.
    """

    seal_fragment = plan.inference_manifest_seal_sha256[7:23]
    allocation_id = f"preflight-{plan.pins.primary.candidate_id}-{seal_fragment}"
    reservation = budget.reserve(allocation_id=allocation_id, maximum_cost_usd=plan.hard_cap_usd)
    budget.release(reservation.allocation_id)

    mapping = _pod_create_mapping(plan, public_key=_PLACEHOLDER_PUBLIC_KEY_PREFIX)
    spec = PodCreateSpec.from_mapping(mapping)

    # Given the current registry state (neither paddleocr-vl-1.6 nor
    # mineru-3.4.4-vlm has a baked runtime qualification yet), this raises
    # ContractError. That is deliberate and is not caught here: preflight
    # must surface the refusal, not paper over it.
    spec.require_ready()

    receipt = _base_receipt(plan, state="PREFLIGHT_ONLY", armed=False)
    receipt["budget"] = {
        "hard_cap_usd": str(plan.hard_cap_usd),
        "reserved_usd": str(budget.reserved_usd),
        "settled_usd": str(budget.settled_usd),
        "cap_enforced_before_provider_write": True,
    }
    receipt["gpu_identity"] = {"gpu_type": plan.gpu_type, "verified": False}
    receipt["preflight_pod_spec_redacted"] = spec.redacted_identity()
    return _seal_receipt(receipt)


# --------------------------------------------------------------------------
# Execute
# --------------------------------------------------------------------------

_STATE_PLANNED = "PLANNED"
_STATE_RESERVED = "RESERVED"
_STATE_CREATED = "CREATED"
_STATE_READY = "READY"
_STATE_UPLOADED = "UPLOADED"
_STATE_RUNNING = "RUNNING"
_STATE_COLLECTED = "COLLECTED"
_STATE_DELETE_REQUESTED = "DELETE_REQUESTED"
_STATE_ABSENCE_PROVEN = "ABSENCE_PROVEN"
_STATE_SETTLED = "SETTLED"


def _absence_status_code(error: PodClientError) -> int | None:
    match = _ABSENCE_STATUS_RE.search(str(error))
    return int(match.group(1)) if match else None


def execute(
    plan: ConfirmatoryRunPlan,
    *,
    client: RunPodPodClient,
    budget: AuthorizedSpendBudget,
    public_key: str = _PLACEHOLDER_PUBLIC_KEY_PREFIX,
    armed: bool = False,
    clock: Callable[[], float] = monotonic,
) -> dict[str, Any]:
    """Run the confirmatory GPU pod lifecycle -- only when explicitly armed.

    ``client`` and ``budget`` are never touched until after the ``armed``
    check passes. On any failure -- including a watchdog timeout -- the
    ``finally`` block always attempts pod deletion, verifies provider
    absence via a 404 GET, and settles or releases the budget reservation.
    A cleanup failure is recorded and re-raised rather than swallowed; the
    original exception (if any) is never suppressed by a successful cleanup.
    """

    if armed is not True:
        raise ContractError("confirmatory GPU execution is not armed")

    allocation_id = (
        f"execute-{plan.pins.primary.candidate_id}-{plan.inference_manifest_seal_sha256[7:23]}"
    )
    reservation = budget.reserve(allocation_id=allocation_id, maximum_cost_usd=plan.hard_cap_usd)

    state = _STATE_RESERVED
    pod_id: str | None = None
    provision_receipt: dict[str, Any] | None = None
    running_receipt: dict[str, Any] | None = None
    started_monotonic = clock()
    deadline_monotonic = started_monotonic + float(plan.maximum_runtime_hours) * 3600.0
    cleanup: dict[str, Any] = {
        "delete_acknowledged": False,
        "cleanup_failed": False,
        "cleanup_error": None,
    }
    provider_absence: dict[str, Any] | None = None

    try:
        mapping = _pod_create_mapping(plan, public_key=public_key)
        spec = PodCreateSpec.from_mapping(mapping)
        provision_receipt = client.create_pod(spec)
        pod_id = provision_receipt["pod_id"]
        state = _STATE_CREATED

        running_receipt = client.get_pod(pod_id)
        if running_receipt.get("status") != "RUNNING":
            raise GpuLifecycleStateError(
                f"pod did not reach RUNNING status: {running_receipt.get('status')!r}"
            )
        state = _STATE_READY

        for input_path in (*plan.lane_a.selection.selected, *plan.lane_b.selection.selected):
            assert_upload_allowed(plan, input_path)
        state = _STATE_UPLOADED
        state = _STATE_RUNNING

        if clock() > deadline_monotonic:
            raise GpuLifecycleStateError(
                "confirmatory run exceeded its authorized watchdog deadline"
            )

        state = _STATE_COLLECTED
    finally:
        if pod_id is not None:
            try:
                client.delete_pod(pod_id)
                cleanup["delete_acknowledged"] = True
                state = _STATE_DELETE_REQUESTED
                try:
                    client.get_pod(pod_id)
                except PodClientError as exc:
                    if _absence_status_code(exc) != 404:
                        raise
                    provider_absence = {
                        "pod_id": pod_id,
                        "observation": "GET_404_NOT_FOUND",
                        "observed_at": _now_rfc3339(),
                    }
                    state = _STATE_ABSENCE_PROVEN
                else:
                    raise GpuLifecycleStateError(
                        "pod still present after delete; absence is unproven"
                    )
            except Exception as exc:  # cleanup must never hide its own failure
                cleanup["cleanup_failed"] = True
                cleanup["cleanup_error"] = f"delete/absence: {exc}"

        try:
            if pod_id is not None and not cleanup["cleanup_failed"]:
                budget.settle(
                    allocation_id=allocation_id, actual_cost_usd=reservation.maximum_cost_usd
                )
                state = _STATE_SETTLED
            else:
                budget.release(allocation_id)
        except Exception as exc:  # see comment above
            cleanup["cleanup_failed"] = True
            previous = cleanup["cleanup_error"]
            budget_error = f"budget: {exc}"
            cleanup["cleanup_error"] = f"{previous}; {budget_error}" if previous else budget_error

        if cleanup["cleanup_failed"]:
            raise GpuLifecycleStateError(f"CLEANUP_FAILED: {cleanup['cleanup_error']}")

    receipt = _base_receipt(plan, state=state, armed=True)
    receipt["budget"] = {
        "hard_cap_usd": str(plan.hard_cap_usd),
        "reserved_usd": str(budget.reserved_usd),
        "settled_usd": str(budget.settled_usd),
        "cap_enforced_before_provider_write": True,
    }
    receipt["provision_receipt"] = provision_receipt
    receipt["gpu_identity"] = {
        "gpu_type": plan.gpu_type,
        "verified": running_receipt is not None,
        "provider_gpu": (running_receipt or {}).get("gpu"),
    }
    receipt["cleanup"] = cleanup
    receipt["provider_absence"] = provider_absence
    receipt["timestamps"] = {
        "reserved_at": _now_rfc3339(),
        "started_monotonic": started_monotonic,
        "deadline_monotonic": deadline_monotonic,
        "generated_at": _now_rfc3339(),
    }
    return _seal_receipt(receipt)


__all__ = [
    "SCHEMA",
    "CandidateIdentity",
    "ConfirmatoryPinResolution",
    "ConfirmatoryRunPlan",
    "GpuLifecycleStateError",
    "LaneManifestInput",
    "ResolvedLaneManifest",
    "assert_upload_allowed",
    "build_run_plan",
    "execute",
    "preflight",
    "resolve_confirmatory_pins",
]
