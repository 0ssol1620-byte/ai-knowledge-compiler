"""WP-R5 portfolio: bind an execution lane to a concrete model, or refuse to.

A lane (`ExecutionLane`) is a job. A model is a worker. This module is the only
place the two meet, and it will only join them when the evidence for that model
is actually present.

Three rules it exists to enforce:

* **Never infer capability from a name.** "OCR" in a repository id is not
  evidence that a model reads tables. Only the fields in `ModelEvidence` count,
  and every one of them is copied from a registry artifact, never guessed.
* **Missing evidence is `CANDIDATE`, not "probably fine".** WP-R4 says an
  unqualified model is a candidate; `missing_evidence` names exactly which
  receipts are absent, so the gap is a work item and not a vibe.
* **An unapproved licence is `EXCLUDED`.** Code, weights, dataset and hosted-API
  terms are four separate licences; this checks the one the registry recorded
  and claims nothing about the other three.

Nothing here reads the filesystem. `evidence_from_runtime_manifest` takes an
already-parsed mapping so the caller owns path policy and the tests stay
hermetic.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .execution_plan import ExecutionLane
from .models import Route

#: Registry licence states that permit a model to be promoted at all.
APPROVED_LICENCE_STATUS: frozenset[str] = frozenset({"approved", "verified"})

#: Lanes served by something other than an Arena model: the native parsers in
#: this repository, and a person. They need no model evidence.
NON_MODEL_LANES: frozenset[ExecutionLane] = frozenset(
    {ExecutionLane.NATIVE, ExecutionLane.HUMAN_REVIEW}
)

#: Lanes whose execution sends tenant content to a third party. Bound routes for
#: these must be in `data_policy.EXTERNAL_ROUTES`, and only these.
EXTERNAL_LANES: frozenset[ExecutionLane] = frozenset({ExecutionLane.EXTERNAL_ADJUDICATOR})

#: WP-R4 (§5) evidence a model needs before it can be a champion for a lane.
REQUIRED_EVIDENCE: tuple[str, ...] = (
    "weights_repo",
    "weights_revision",
    "container_digest_observed",
    "runtime_version",
    "inference_args_sha256",
    "gpu_min_vram_gb",
    "gpu_count_min",
    "licence_status",
    "prompt_id",
    "warm_latency_seconds",
    "cold_start_seconds",
    "throughput_pages_per_gpu_hour",
    "failure_modes",
    "page_class_evidence",
    "data_policy",
)


class Qualification(StrEnum):
    QUALIFIED = "QUALIFIED"
    CANDIDATE = "CANDIDATE"
    EXCLUDED = "EXCLUDED"


@dataclass(frozen=True, slots=True)
class ModelEvidence:
    """What is actually known about one model. `None` means "no receipt"."""

    model_key: str
    weights_repo: str | None = None
    weights_revision: str | None = None
    container_reference: str | None = None
    container_digest_observed: str | None = None
    runtime_version: str | None = None
    inference_args_sha256: str | None = None
    gpu_min_vram_gb: int | None = None
    gpu_count_min: int | None = None
    licence_id: str | None = None
    licence_status: str | None = None
    licence_url: str | None = None
    prompt_id: str | None = None
    warm_latency_seconds: float | None = None
    cold_start_seconds: float | None = None
    throughput_pages_per_gpu_hour: float | None = None
    failure_modes: tuple[str, ...] = ()
    page_class_evidence: tuple[str, ...] = ()
    data_policy: str | None = None
    founder_excluded: bool = False
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.model_key:
            raise ValueError("model evidence requires a model key")

    @property
    def missing_evidence(self) -> tuple[str, ...]:
        """The §5 receipts this model does not have. Empty tuple = complete."""
        missing: list[str] = []
        for name in REQUIRED_EVIDENCE:
            value = getattr(self, name)
            if value is None or (isinstance(value, tuple) and not value):
                missing.append(name)
        if self.licence_status is not None and self.licence_status not in APPROVED_LICENCE_STATUS:
            missing.append("licence_status")
        return tuple(missing)

    @property
    def qualification(self) -> Qualification:
        if self.founder_excluded:
            return Qualification.EXCLUDED
        if self.licence_status not in APPROVED_LICENCE_STATUS:
            return Qualification.EXCLUDED
        return Qualification.QUALIFIED if not self.missing_evidence else Qualification.CANDIDATE


def evidence_from_runtime_manifest(
    manifest: Mapping[str, object],
    *,
    founder_excluded: bool = False,
    exclusion_reason: str | None = None,
    warm_latency_seconds: float | None = None,
    cold_start_seconds: float | None = None,
    throughput_pages_per_gpu_hour: float | None = None,
    failure_modes: Sequence[str] = (),
    page_class_evidence: Sequence[str] = (),
    data_policy: str | None = None,
) -> ModelEvidence:
    """Read one Arena `runtimes/<model>/runtime.json` mapping into evidence.

    The measured fields the manifest does not carry -- latency, throughput,
    observed failure modes, per-page-class evidence, data policy -- are keyword
    arguments precisely so that leaving them out leaves the model a CANDIDATE
    rather than silently qualifying it.
    """
    licence = manifest.get("license")
    licence_map: Mapping[str, object] = licence if isinstance(licence, Mapping) else {}
    reference = _as_str(manifest.get("base_image"))
    weights = manifest.get("weights")
    weights_map: Mapping[str, object] = weights if isinstance(weights, Mapping) else {}
    return ModelEvidence(
        model_key=str(manifest.get("model_key") or ""),
        weights_repo=_as_str(weights_map.get("repo")) or _as_str(manifest.get("model_repo")),
        weights_revision=(
            _as_str(weights_map.get("revision")) or _as_str(manifest.get("model_revision"))
        ),
        container_reference=reference,
        container_digest_observed=container_digest(reference),
        runtime_version=_as_str(manifest.get("runtime_version")),
        inference_args_sha256=_inference_args_sha256(manifest.get("inference_config")),
        gpu_min_vram_gb=_as_int(manifest.get("gpu_min_vram_gb")),
        gpu_count_min=_as_int(manifest.get("gpu_count_min")),
        licence_id=_as_str(licence_map.get("id")),
        licence_status=_as_str(licence_map.get("status")),
        licence_url=_as_str(licence_map.get("url")),
        prompt_id=_as_str(manifest.get("prompt_id")),
        warm_latency_seconds=warm_latency_seconds,
        cold_start_seconds=cold_start_seconds,
        throughput_pages_per_gpu_hour=throughput_pages_per_gpu_hour,
        failure_modes=tuple(failure_modes),
        page_class_evidence=tuple(page_class_evidence),
        data_policy=data_policy,
        founder_excluded=founder_excluded,
        exclusion_reason=exclusion_reason,
    )


def container_digest(reference: str | None) -> str | None:
    """Pull the resolved `sha256:` digest out of an image reference.

    A tag is not a digest: `vllm/vllm-openai:v0.19.0` names something that can
    change under you, so a reference without `@sha256:` yields `None`.
    """
    if not reference or "@sha256:" not in reference:
        return None
    digest = reference.split("@", 1)[1]
    body = digest.removeprefix("sha256:")
    if len(body) != 64 or any(character not in "0123456789abcdef" for character in body):
        return None
    return digest


class UnboundLaneError(ValueError):
    """Raised instead of silently routing a lane nothing is qualified for."""


@dataclass(frozen=True, slots=True)
class LaneBinding:
    lane: ExecutionLane
    route: Route
    model_key: str | None
    qualification: Qualification
    missing_evidence: tuple[str, ...] = ()

    @property
    def is_promotable(self) -> bool:
        return self.qualification is Qualification.QUALIFIED


@dataclass(frozen=True, slots=True)
class Portfolio:
    """Lane -> route/model bindings plus the revision that identifies them."""

    bindings: tuple[LaneBinding, ...] = ()
    revision: str = "portfolio-empty"
    _by_lane: dict[ExecutionLane, LaneBinding] = field(default_factory=dict, repr=False)

    def binding(self, lane: ExecutionLane) -> LaneBinding | None:
        return self._by_lane.get(lane)

    def route_for(self, lane: ExecutionLane, *, promotable_only: bool = True) -> Route:
        """The route bound to a lane. Fails closed rather than guessing one."""
        found = self._by_lane.get(lane)
        if found is None:
            raise UnboundLaneError(f"no portfolio binding for lane {lane.value}")
        if promotable_only and not found.is_promotable:
            raise UnboundLaneError(
                f"lane {lane.value} binds {found.model_key or 'n/a'} at "
                f"{found.qualification.value}; missing {', '.join(found.missing_evidence) or 'n/a'}"
            )
        return found.route

    @property
    def promotable_lanes(self) -> frozenset[ExecutionLane]:
        return frozenset(
            binding.lane for binding in self._by_lane.values() if binding.is_promotable
        )


def build_portfolio(
    proposals: Mapping[ExecutionLane, tuple[Route, str | None]],
    evidence: Mapping[str, ModelEvidence],
) -> Portfolio:
    """Qualify each proposed lane binding against the evidence supplied.

    A proposal is a *request*, not a promotion: the qualification is computed
    from the evidence, and a lane whose model has none comes back CANDIDATE.
    """
    bindings: list[LaneBinding] = []
    for lane in sorted(proposals, key=lambda item: item.value):
        route, model_key = proposals[lane]
        if lane in NON_MODEL_LANES:
            bindings.append(
                LaneBinding(
                    lane=lane,
                    route=route,
                    model_key=model_key,
                    qualification=Qualification.QUALIFIED,
                )
            )
            continue
        if model_key is None:
            bindings.append(
                LaneBinding(
                    lane=lane,
                    route=route,
                    model_key=None,
                    qualification=Qualification.CANDIDATE,
                    missing_evidence=("model_key",),
                )
            )
            continue
        known = evidence.get(model_key)
        if known is None:
            bindings.append(
                LaneBinding(
                    lane=lane,
                    route=route,
                    model_key=model_key,
                    qualification=Qualification.CANDIDATE,
                    missing_evidence=REQUIRED_EVIDENCE,
                )
            )
            continue
        bindings.append(
            LaneBinding(
                lane=lane,
                route=route,
                model_key=model_key,
                qualification=known.qualification,
                missing_evidence=known.missing_evidence,
            )
        )
    ordered = tuple(bindings)
    return Portfolio(
        bindings=ordered,
        revision=portfolio_revision(ordered),
        _by_lane={binding.lane: binding for binding in ordered},
    )


def portfolio_revision(bindings: Sequence[LaneBinding]) -> str:
    """Stable identity for a binding set, for `DocumentExecutionPlan`."""
    payload = json.dumps(
        [
            [
                binding.lane.value,
                binding.route.value,
                binding.model_key,
                binding.qualification.value,
                list(binding.missing_evidence),
            ]
            for binding in bindings
        ],
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "portfolio_" + hashlib.sha256(payload).hexdigest()[:16]


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _inference_args_sha256(config: object) -> str | None:
    """Hash the recorded inference arguments so a change to them is visible."""
    if not isinstance(config, Mapping) or not config:
        return None
    payload = json.dumps(config, separators=(",", ":"), sort_keys=True, default=str).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


__all__ = [
    "APPROVED_LICENCE_STATUS",
    "EXTERNAL_LANES",
    "NON_MODEL_LANES",
    "REQUIRED_EVIDENCE",
    "LaneBinding",
    "ModelEvidence",
    "Portfolio",
    "Qualification",
    "UnboundLaneError",
    "build_portfolio",
    "container_digest",
    "evidence_from_runtime_manifest",
    "portfolio_revision",
]
