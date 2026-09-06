"""Build the campaign plan: shards and inference job ids.

Inputs are lane A2's ``source_manifest.jsonl`` and lane A3's
``model_registry.json``. Both are produced in parallel with this lane, so the
readers here are written against the ARENA_CONTRACT shapes (sections 3.7, 2)
and validate rather than assume: a missing required field is a refusal naming
the field, never a default.

Determinism is the property that matters. The same manifest and registry
produce the same shards, in the same order, with the same job ids, on any host.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from arena.constants import BENCHMARK_KEYS, CAMPAIGN_ID
from arena.controller.ids_local import ids_source, inference_job_id, shard_id
from arena.controller.paths import CampaignPaths
from arena.controller.queue import JobRecord, ShardRecord
from arena.controller.scheduler import effective_concurrency
from arena.provider.safety import iter_jsonl, read_json

__all__ = [
    "MANIFEST_FIELD_MAP",
    "CampaignPlan",
    "ModelPlanEntry",
    "PlanError",
    "SourceSample",
    "build_plan",
    "load_model_registry",
    "load_source_manifest",
]

# ARENA_CONTRACT section 2: anything that identifies bytes is spelled this way.
SHA256_REF_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")

DEFAULT_SHARD_SIZE: Final = 100
# Masterplan section 15.6 bands. A hint outside them is refused, not clamped.
SHARD_SIZE_MIN: Final = 10
SHARD_SIZE_MAX: Final = 250
# Masterplan section 19 historical sec/page, used only to order shards when the
# registry gives no measurement and no canary has run yet.
FALLBACK_PREDICTED_SECONDS_PER_PAGE: Final = 10.0


class PlanError(RuntimeError):
    """The manifest or the registry does not satisfy the contract."""


@dataclass(frozen=True, slots=True)
class SourceSample:
    sample_id: str
    case_key: str
    benchmark: str
    source_sha256: str
    benchmark_revision: str
    image_path: str
    width: int | None = None
    height: int | None = None
    media_type: str | None = None
    page_index: int | None = None

    def metadata(self) -> dict[str, object]:
        return {"page_index": self.page_index, "media_type": self.media_type}


@dataclass(frozen=True, slots=True)
class ModelPlanEntry:
    model_key: str
    model_repo: str
    model_revision: str
    runtime_image_digest: str
    prompt_id: str
    prompt_sha256: str
    inference_config_sha256: str
    shard_size: int
    per_worker_concurrency: int
    predicted_seconds_per_page: float
    predicted_seconds_source: str
    canary_status: str
    full_run_eligible: bool
    runtime_mode_allowed: tuple[str, ...]
    gpu_pool_priority: tuple[str, ...]
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CampaignPlan:
    model_key: str
    shards: tuple[ShardRecord, ...]
    jobs: tuple[JobRecord, ...]
    ids_source: str
    entry: ModelPlanEntry

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.arena.campaign_plan.v1",
            "campaign_id": CAMPAIGN_ID,
            "model_key": self.model_key,
            "ids_source": self.ids_source,
            "shard_count": len(self.shards),
            "job_count": len(self.jobs),
            "shard_size": self.entry.shard_size,
            "per_worker_concurrency": self.entry.per_worker_concurrency,
            "predicted_seconds_per_page": self.entry.predicted_seconds_per_page,
            "predicted_seconds_source": self.entry.predicted_seconds_source,
            "runtime_image_digest": self.entry.runtime_image_digest,
            "shards": [
                {
                    "shard_id": shard.shard_id,
                    "benchmark": shard.benchmark,
                    "job_count": shard.job_count,
                    "predicted_seconds": round(shard.predicted_seconds, 3),
                }
                for shard in self.shards
            ],
        }


# ARENA_CONTRACT 11.5 D14. Lane A2 owns the manifest and keeps its own field
# names; the controller maps them here, in exactly one place, with no aliases.
# ``original_source_sha256`` is provenance (which PDF a page came from) and
# never enters an inference_job_id: the bytes the model actually sees are the
# PNG, so ``input_png_sha256`` is the job-id input.
MANIFEST_FIELD_MAP: Final = MappingProxyType(
    {
        "source_sha256": "input_png_sha256",
        "benchmark_revision": "dataset_revision",
        "image_path": "input_relative_path",
    }
)


def load_source_manifest(path: Path) -> tuple[SourceSample, ...]:
    """Read lane A2's source manifest (D14). Every field it needs must be present.

    Fails closed: a row missing any of the three mapped names is refused by
    name, never defaulted and never read from a similarly-spelled key.
    """

    if not path.is_file():
        raise PlanError(
            f"{path.name} is absent; run `python -m arena.manifest build` (lane A2) first"
        )
    samples: list[SourceSample] = []
    seen: set[str] = set()
    for index, record in enumerate(iter_jsonl(path), start=1):
        if not isinstance(record, Mapping):
            raise PlanError(f"{path.name}:{index} is not a JSON object")
        where = f"{path.name}:{index}"
        sample = SourceSample(
            sample_id=_required_str(record, "sample_id", where),
            case_key=_required_str(record, "case_key", where),
            benchmark=_required_str(record, "benchmark", where),
            source_sha256=_manifest_field(record, "source_sha256", where),
            benchmark_revision=_manifest_field(record, "benchmark_revision", where),
            image_path=_manifest_field(record, "image_path", where),
            width=_optional_int(record, "width"),
            height=_optional_int(record, "height"),
            media_type=_optional_str(record, "media_type"),
            page_index=_optional_int(record, "page_index"),
        )
        if sample.benchmark not in BENCHMARK_KEYS:
            raise PlanError(
                f"{path.name}:{index} benchmark {sample.benchmark!r} is not in {BENCHMARK_KEYS}"
            )
        if sample.case_key in seen:
            raise PlanError(f"{path.name}:{index} duplicates case_key {sample.case_key!r}")
        seen.add(sample.case_key)
        samples.append(sample)
    if not samples:
        raise PlanError(f"{path.name} holds no samples")
    return tuple(samples)


def load_model_registry(
    path: Path,
    model_key: str,
    *,
    runtime_image_digest: str | None = None,
    prompt_id: str | None = None,
    prompt_sha256: str | None = None,
) -> ModelPlanEntry:
    """Read one model's record from lane R's registry (contract section 3.7).

    ARENA_CONTRACT 11.5 D15: a bootstrap canary has no container image at all,
    so its ``runtime_image_digest`` is ``bootstrap:<bundle sha256>`` and comes
    from the bundle receipt, never from the registry. The registry's
    ``container_digest`` stays ``null`` with its reason until lane F bakes
    images, and requiring it here would block Phase 1 on a field Phase 1 does
    not have. When the caller supplies a digest it is used; when it does not,
    the registry must carry one.

    ``prompt_id`` / ``prompt_sha256`` follow the same rule for D15/D17: the
    runtime owns the prompt id and ``prompt_registry/sha256.json`` owns its
    hash, so the caller may resolve both and hand them in. Nothing is
    defaulted -- an unsupplied value that the registry also lacks is a refusal.
    """

    if not path.is_file():
        raise PlanError(
            f"{path.name} is absent; run `python -m arena.registry resolve` (lane A3) first"
        )
    document = read_json(path)
    record = _find_model_record(document, model_key, path.name)
    context = f"{path.name}[{model_key}]"

    shard_hint = record.get("shard_size_hint", DEFAULT_SHARD_SIZE)
    if not isinstance(shard_hint, int) or isinstance(shard_hint, bool):
        raise PlanError(f"{context}.shard_size_hint must be an integer")
    if not SHARD_SIZE_MIN <= shard_hint <= SHARD_SIZE_MAX:
        raise PlanError(
            f"{context}.shard_size_hint {shard_hint} is outside the masterplan 15.6 band "
            f"{SHARD_SIZE_MIN}-{SHARD_SIZE_MAX}"
        )

    concurrency_policy = record.get("concurrency_policy")
    if concurrency_policy is not None and not isinstance(concurrency_policy, Mapping):
        raise PlanError(f"{context}.concurrency_policy must be an object")
    concurrency = effective_concurrency(model_key, concurrency_policy)

    predicted, predicted_source = _predicted_seconds(record, context)
    runtime_modes = record.get("runtime_mode_allowed", ["baked"])
    if not isinstance(runtime_modes, Sequence) or isinstance(runtime_modes, str):
        raise PlanError(f"{context}.runtime_mode_allowed must be an array")
    gpu_pool = record.get("gpu_pool_priority", [])
    if not isinstance(gpu_pool, Sequence) or isinstance(gpu_pool, str):
        raise PlanError(f"{context}.gpu_pool_priority must be an array")

    canary_status = str(record.get("canary_status", "PENDING"))
    if canary_status not in {"PENDING", "PASS", "FAIL"}:
        raise PlanError(f"{context}.canary_status must be PENDING, PASS or FAIL")

    return ModelPlanEntry(
        model_key=model_key,
        model_repo=_required_str(record, "model_repo", context, alternatives=("repo",)),
        model_revision=_required_str(
            record, "model_revision", context, alternatives=("revision",)
        ),
        runtime_image_digest=(
            runtime_image_digest
            if runtime_image_digest
            else _required_str(
                record,
                "runtime_image_digest",
                context,
                alternatives=("container_digest",),
                supplied_by=(
                    "pass runtime_image_digest= for a bootstrap canary "
                    "(arena.core.ids.bootstrap_image_digest, D15)"
                ),
            )
        ),
        prompt_id=(
            prompt_id
            if prompt_id
            else _required_str(
                record, "official_prompt_id", context, alternatives=("prompt_id",)
            )
        ),
        prompt_sha256=(
            prompt_sha256
            if prompt_sha256
            else _required_str(
                record,
                "prompt_sha256",
                context,
                supplied_by="resolve it from prompt_registry/sha256.json (D17)",
            )
        ),
        # NOT official_inference_config_sha256. That field hashes the model
        # card's documented serve command and prompt vocabulary; this one
        # hashes runtime.json's operational inference_config, which is what the
        # worker hashes and compares against on every run (D16). Sending the
        # first where the second is meant is what made the 2026-09-03 GLM-OCR
        # canary answer HTTP 422 CONFIG_MISMATCH to all 13 pages it received.
        inference_config_sha256=_required_sha256_ref(
            record,
            "inference_config_sha256",
            context,
            supplied_by=(
                "lane R derives it from runtimes/<key>/runtime.json "
                "(`python -m arena.registry resolve --offline`)"
            ),
        ),
        shard_size=shard_hint,
        per_worker_concurrency=concurrency,
        predicted_seconds_per_page=predicted,
        predicted_seconds_source=predicted_source,
        canary_status=canary_status,
        full_run_eligible=bool(record.get("full_run_eligible", False)),
        runtime_mode_allowed=tuple(str(mode) for mode in runtime_modes),
        gpu_pool_priority=tuple(str(pool) for pool in gpu_pool),
        raw=dict(record),
    )


def build_plan(
    *,
    model_key: str,
    samples: Sequence[SourceSample],
    entry: ModelPlanEntry,
    job_kind: str = "inference",
    campaign_id: str = CAMPAIGN_ID,
) -> CampaignPlan:
    """Deterministic shards and job ids for one model.

    Samples are ordered by ``(benchmark, case_key)`` so a re-plan on a different
    machine yields byte-identical shard membership.
    """

    ordered = sorted(samples, key=lambda sample: (sample.benchmark, sample.case_key))
    shards: list[ShardRecord] = []
    jobs: list[JobRecord] = []
    for benchmark in BENCHMARK_KEYS:
        in_benchmark = [sample for sample in ordered if sample.benchmark == benchmark]
        for index, start in enumerate(range(0, len(in_benchmark), entry.shard_size)):
            chunk = in_benchmark[start : start + entry.shard_size]
            identifier = shard_id(model_key, benchmark, index)
            shards.append(
                ShardRecord(
                    shard_id=identifier,
                    model_key=model_key,
                    benchmark=benchmark,
                    shard_index=index,
                    job_count=len(chunk),
                    predicted_seconds=len(chunk) * entry.predicted_seconds_per_page,
                )
            )
            for sample in chunk:
                jobs.append(
                    JobRecord(
                        inference_job_id=inference_job_id(
                            campaign_id=campaign_id,
                            benchmark_revision=sample.benchmark_revision,
                            sample_id=sample.sample_id,
                            source_sha256=sample.source_sha256,
                            model_repo=entry.model_repo,
                            model_revision=entry.model_revision,
                            runtime_image_digest=entry.runtime_image_digest,
                            prompt_sha256=entry.prompt_sha256,
                            inference_config_sha256=entry.inference_config_sha256,
                        ),
                        model_key=model_key,
                        benchmark=benchmark,
                        sample_id=sample.sample_id,
                        case_key=sample.case_key,
                        shard_id=identifier,
                        job_kind=job_kind,
                    )
                )
    _refuse_duplicate_job_ids(jobs)
    return CampaignPlan(
        model_key=model_key,
        shards=tuple(shards),
        jobs=tuple(jobs),
        ids_source=ids_source(),
        entry=entry,
    )


def dispatch_order(shards: Iterable[ShardRecord]) -> tuple[ShardRecord, ...]:
    """Masterplan section 35: slowest predicted shard first."""

    return tuple(
        sorted(shards, key=lambda shard: (-shard.predicted_seconds, shard.shard_id))
    )


def plan_paths(root: Path | None = None) -> CampaignPaths:
    return CampaignPaths(root=root) if root is not None else CampaignPaths.default()


# ------------------------------------------------------------------ helpers


def _refuse_duplicate_job_ids(jobs: Sequence[JobRecord]) -> None:
    seen: dict[str, str] = {}
    for job in jobs:
        previous = seen.get(job.inference_job_id)
        if previous is not None:
            raise PlanError(
                "two samples derive the same inference_job_id "
                f"({previous} and {job.case_key}); the manifest is not unique"
            )
        seen[job.inference_job_id] = job.case_key


def _find_model_record(document: object, model_key: str, name: str) -> Mapping[str, Any]:
    """Accept either a mapping keyed by model_key or a list of records."""

    if isinstance(document, Mapping):
        models = document.get("models", document)
        if isinstance(models, Mapping):
            record = models.get(model_key)
            if isinstance(record, Mapping):
                return record
        if isinstance(models, Sequence) and not isinstance(models, str):
            for item in models:
                if isinstance(item, Mapping) and item.get("model_key") == model_key:
                    return item
    elif isinstance(document, Sequence) and not isinstance(document, str):
        for item in document:
            if isinstance(item, Mapping) and item.get("model_key") == model_key:
                return item
    raise PlanError(f"{name} has no record for model_key {model_key!r}")


def _predicted_seconds(record: Mapping[str, Any], context: str) -> tuple[float, str]:
    for key, label in (
        ("canary_warm_sec_per_page", "canary warm median"),
        ("historical_sec_per_page", "masterplan section 19 historical measurement"),
    ):
        value = record.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value), label
    # Never invent a measurement: this is an ordering hint only, and it says so.
    return (
        FALLBACK_PREDICTED_SECONDS_PER_PAGE,
        f"{context}: no measurement available; ordering hint only, not a projection",
    )


def _manifest_field(record: Mapping[str, Any], controller_name: str, context: str) -> str:
    """One D14 mapping lookup. The manifest name is the only name accepted."""

    manifest_name = MANIFEST_FIELD_MAP[controller_name]
    value = record.get(manifest_name)
    if not isinstance(value, str) or not value:
        raise PlanError(
            f"{context} is missing a non-empty {manifest_name!r} "
            f"(the manifest field the controller reads as {controller_name}); "
            "ARENA_CONTRACT 11.5 D14 allows no alias for it"
        )
    return value


def _required_str(
    record: Mapping[str, Any],
    key: str,
    context: str,
    *,
    alternatives: tuple[str, ...] = (),
    supplied_by: str | None = None,
) -> str:
    for candidate in (key, *alternatives):
        value = record.get(candidate)
        if isinstance(value, str) and value:
            return value
    names = " / ".join((key, *alternatives))
    message = f"{context} is missing a non-empty {names}"
    if supplied_by is not None:
        message = f"{message}; {supplied_by}"
    raise PlanError(message)


def _required_sha256_ref(
    record: Mapping[str, Any],
    key: str,
    context: str,
    *,
    supplied_by: str | None = None,
) -> str:
    """``_required_str`` plus the ``sha256:<64 hex>`` shape the worker demands.

    The worker rejects any other spelling with ``INVALID_REQUEST`` before it
    compares anything, so a bare-hex or truncated digest in the registry is a
    refusal here rather than a 422 from a rented pod.
    """

    value = _required_str(record, key, context, supplied_by=supplied_by)
    if not SHA256_REF_RE.fullmatch(value):
        raise PlanError(f"{context}.{key} must be 'sha256:<64 lowercase hex>', got {value!r}")
    return value


def _optional_str(record: Mapping[str, Any], key: str) -> str | None:
    value = record.get(key)
    return value if isinstance(value, str) and value else None


def _optional_int(record: Mapping[str, Any], key: str) -> int | None:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
